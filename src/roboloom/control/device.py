"""JointDevice: control-law groups in front of a bus, presenting the plain bus contract.

`FollowerSafety` (and an actuated leader) talk to a JointDevice exactly as to a
bus: `read_state`, `write_positions(target)`, `enable_torque`, `disable_torque`.
The device routes each joint to its law and writes position and current goals.

Torque-on sequence: verify operating modes (never written here), zero Goal
Current and read it back for current-mode joints, seed position goals, reset the
laws, then enable torque on non-free joints.

On any failure while commanding, current-mode joints go limp (zero current,
torque off) before the error propagates: their last goal current would otherwise
stay applied at a pose it was not computed for. Position-mode joints keep torque
and hold their last goal, so a follower does not drop; `disable_torque` releases all.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

import yaml

from ..core.checks import names as check_names
from ..drivers.base import Health, JointState, read_health, read_state
from ..drivers.dynamixel_table import OPERATING_MODES
from ..dynamics.base import GravityModel, load_gravity_model
from . import LAWS
from .laws import ControlLaw, _per_joint
from .trace import Trace


@dataclass
class GroupSpec:
    name: str
    law: str
    joints: tuple[str, ...]
    cfg: dict


def parse_groups(
    raw: object, joint_names: tuple[str, ...], owner: str
) -> list[GroupSpec]:
    """`control: [{group, law, joints, ...}]`; every joint in exactly one group."""
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{owner}.control must be a non-empty list of groups")
    groups: list[GroupSpec] = []
    seen: list[str] = []
    for item in raw:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("group"), str)
            or item.get("law") not in LAWS
        ):
            raise ValueError(
                f"{owner}.control: each group needs a name and law in {sorted(LAWS)}"
            )
        joints = check_names(
            item.get("joints"), f"{owner}.control.{item['group']}.joints"
        )
        if not set(joints) <= set(joint_names):
            raise ValueError(
                f"{owner}.control.{item['group']}: unknown joints {sorted(set(joints) - set(joint_names))}"
            )
        seen += joints
        groups.append(GroupSpec(item["group"], item["law"], joints, item))
    if sorted(seen) != sorted(joint_names):
        raise ValueError(f"{owner}.control must cover every joint exactly once")
    if len({g.name for g in groups}) != len(groups):
        raise ValueError(f"{owner}.control group names must be unique")
    return groups


def law_class(law: str) -> type[ControlLaw]:
    module, _, cls = LAWS[law].partition(":")
    return getattr(import_module(module), cls)


def build_laws(
    groups: list[GroupSpec],
    joint_names: tuple[str, ...],
    base_dir: str | None = None,
    models: Mapping[str, GravityModel] | None = None,
) -> list[ControlLaw]:
    """Instantiate each group's law. `models` injects gravity models by group name (tests, tools)."""
    laws = []
    for g in groups:
        gravity: GravityModel | None = (models or {}).get(g.name)
        if gravity is None and g.cfg.get("gravity_model"):
            path = Path(g.cfg["gravity_model"])
            gravity = load_gravity_model(
                str(
                    path
                    if path.is_absolute() or base_dir is None
                    else Path(base_dir) / path
                )
            )
        cfg = g.cfg
        if isinstance(cfg.get("range"), str):
            cfg = {**cfg, "range": load_travel(cfg["range"], g.joints, base_dir)}
        if cfg.get("tuning") is not None:
            cfg = {**cfg, **load_tuning(cfg["tuning"], g.joints, base_dir, g.name, cfg)}
        indices = [joint_names.index(j) for j in g.joints]
        laws.append(law_class(g.law)(g.name, indices, joint_names, cfg, gravity))
    return laws


TUNED = ("gravity_gain", "hold_mA", "hold_kp")


def tuning_path(path: str, base_dir: str | None = None) -> Path:
    file = Path(path)
    return file if file.is_absolute() or base_dir is None else Path(base_dir) / file


def load_tuning(
    path: str, joints: Sequence[str], base_dir: str | None, group: str, cfg: dict
) -> dict:
    """gravity_gain / hold_mA per joint and hold_kp from a file written by `roboloom tune-gravity`."""
    inline = [k for k in TUNED if k in cfg]
    if inline:
        raise ValueError(f"{group}: {inline} are set both inline and in tuning {path}")
    file = tuning_path(path, base_dir)
    if not file.exists():
        raise ValueError(f"{file}: no tuning file; run roboloom tune-gravity")
    data = yaml.safe_load(file.read_text()) or {}
    per_joint = data.get("joints") or {}
    missing = [j for j in joints if j not in per_joint]
    if missing:
        raise ValueError(f"{file}: no tuning for {missing}")
    return {
        "gravity_gain": [float(per_joint[j].get("gain", 0.0)) for j in joints],
        "hold_mA": [float(per_joint[j].get("hold_mA", 0.0)) for j in joints],
        "hold_kp": float(data.get("hold_kp", 1.0)),
    }


def load_travel(
    path: str, joints: Sequence[str], base_dir: str | None = None
) -> list[list[float]]:
    """[min, max] counts per joint from a travel file written by `roboloom measure-travel`."""
    file = Path(path)
    if not file.is_absolute() and base_dir is not None:
        file = Path(base_dir) / file
    if not file.exists():
        raise ValueError(f"{file}: not measured yet; run roboloom measure-travel")
    travel = (yaml.safe_load(file.read_text()) or {}).get("travel") or {}
    missing = [j for j in joints if j not in travel]
    if missing:
        raise ValueError(f"{file}: no measured travel for {missing}")
    return [[float(v) for v in travel[j]] for j in joints]


def expected_modes(groups: list[GroupSpec]) -> dict[str, float]:
    """Operating Mode each joint must already have (free joints are not checked)."""
    out = {}
    for g in groups:
        mode = law_class(g.law).mode
        if mode is not None:
            out.update({j: float(OPERATING_MODES[mode]) for j in g.joints})
    return out


def check_hardware(
    groups: list[GroupSpec], cfg: dict, owner: str, current_limits_mA: dict[str, float]
) -> None:
    """Refuse current-mode laws on hardware without watchdog and EEPROM current limits."""
    for g in groups:
        cls = law_class(g.law)
        if not cls.hardware_validated and g.cfg.get("allow_unvalidated") is not True:
            raise ValueError(
                f"{owner}.control.{g.name}: {g.law} is not validated on hardware; set allow_unvalidated: true to override"
            )
        if cls.current_mode:
            if not cfg.get("bus_watchdog_ms"):
                raise ValueError(
                    f"{owner}: current-mode law {g.law} needs bus_watchdog_ms"
                )
            per_joint = _per_joint(
                g.cfg.get("max_current_mA"), len(g.joints), f"{g.name}.max_current_mA"
            )
            for joint, allowed in zip(g.joints, per_joint, strict=True):
                eeprom = current_limits_mA.get(joint)
                if eeprom is None or eeprom > allowed:
                    raise ValueError(
                        f"{owner}: {joint} needs registers.current_limit <= {allowed} mA for {g.law} (motor-side clip)"
                    )


class WatchdogFired(RuntimeError):
    """The motors stopped accepting goals because the control loop went silent too long."""


class JointDevice:
    def __init__(
        self,
        bus,
        joint_names: tuple[str, ...],
        laws: list[ControlLaw],
        name: str = "device",
    ):
        missing = sorted(
            {
                f"{law.name} ({type(law).__name__}) needs {m}"
                for law in laws
                for m in law.needs
                if not hasattr(bus, m)
            }
        )
        if missing:
            raise TypeError(
                f"{name}: {type(bus).__name__} cannot run these control laws: "
                + "; ".join(missing)
            )
        self.bus, self.joint_names, self.laws, self.name = bus, joint_names, laws, name
        self.state: JointState | None = None
        self.target: list[float] | None = None
        self.enabled = False
        self.last_ns: int | None = None
        self.trace: Trace | None = None
        self.last_currents: dict[int, float] = {}

    def _indices(self, predicate) -> list[int]:
        return sorted(i for law in self.laws if predicate(law) for i in law.joints)

    # -- bus contract ------------------------------------------------------------

    def read_positions(self) -> list[float]:
        return self.read_state().positions

    def read_state(self) -> JointState:
        self.state = read_state(self.bus)
        return self.state

    def read_health(self) -> Health | None:
        return read_health(self.bus)

    def write_positions(self, values: list[float] | None) -> None:
        self.target = None if values is None else list(values)
        if self.enabled:
            self.command(self.target)

    def enable_torque(self) -> None:
        self.check_modes()
        state = self.read_state()
        current = self._indices(lambda law: law.current_mode)
        if current:
            self.bus.write_goal_currents(current, [0.0] * len(current))
            reader = getattr(self.bus, "read_goal_currents", None)
            if reader is not None and any(abs(reader()[i]) > 1e-6 for i in current):
                raise ConnectionError(
                    f"{self.name}: goal current did not read back as zero"
                )
        for law in self.laws:
            law.reset(state)
        self.enabled = True
        self.last_ns = None
        try:
            self.command(self.target)
            self.bus.set_torque(self._indices(lambda law: law.mode is not None), True)
            free = self._indices(lambda law: law.mode is None)
            if free:
                self.bus.set_torque(free, False)
        except BaseException:
            self._safe(self.limp)
            raise

    def disable_torque(self) -> None:
        """Release every joint (operator supports the arm)."""
        self.enabled = False
        self._safe(self.limp)
        self.bus.set_torque(list(range(len(self.joint_names))), False)

    def close(self) -> None:
        try:
            self._safe(self.limp)
        finally:
            self.bus.close()

    @staticmethod
    def _safe(action) -> None:
        """Best effort during error handling: never mask the original error."""
        try:
            action()
        except Exception:  # noqa: BLE001, S110 - the bus may be the thing that failed
            pass

    # -- control -------------------------------------------------------------------

    def check_modes(self) -> None:
        reader = getattr(self.bus, "read_register", None)
        if reader is None:
            return
        modes = reader("operating_mode")
        wrong = [
            f"{self.joint_names[i]} is mode {modes[i]}, {law.name} needs {law.mode}"
            for law in self.laws
            if law.mode is not None
            for i in law.joints
            if modes[i] != OPERATING_MODES[law.mode]
        ]
        if wrong:
            raise RuntimeError(
                f"{self.name}: operating modes differ; run `roboloom commission`:\n  "
                + "\n  ".join(wrong)
            )

    def check_watchdog(self) -> None:
        """A fired Bus Watchdog freezes Goal Current at its last value (the motor keeps
        pushing; bench-tested on XC330, 2026-10-23) and rejects new goals silently, so a
        stalled control loop must be caught here: the caller limps the joints."""
        reader = getattr(self.bus, "read_register", None)
        if reader is None:
            return
        watchdog = reader("bus_watchdog")
        fired = [
            self.joint_names[i]
            for i in self._indices(lambda law: law.current_mode)
            if watchdog[i] < 0
        ]
        if fired:
            raise WatchdogFired(
                f"{self.name}: bus watchdog fired on {fired} (control loop stalled); "
                "goal currents are frozen, releasing"
            )

    def command(self, target: list[float] | None, now_ns: int | None = None) -> None:
        if not self.enabled:
            raise RuntimeError(f"{self.name}: torque is not enabled")
        if self.state is None:
            raise RuntimeError(f"{self.name}: read the state before commanding")
        now = time.monotonic_ns() if now_ns is None else now_ns
        dt = 0.0 if self.last_ns is None else (now - self.last_ns) / 1e9
        self.last_ns = now
        try:
            positions: dict[int, float] = {}
            currents: dict[int, float] = {}
            for law in self.laws:
                goals = law.compute(self.state, target, dt)
                positions.update(goals.positions)
                currents.update(goals.currents_mA)
            self.last_currents = currents
            if self.trace is not None:
                model = {
                    i: v
                    for law in self.laws
                    for i, v in getattr(law, "model_mA", {}).items()
                }
                self.trace.add(now, self.state, model, currents)
            if currents:
                self.check_watchdog()
                keys = sorted(currents)
                self.bus.write_goal_currents(keys, [currents[i] for i in keys])
            if positions:
                keys = sorted(positions)
                self.bus.write_goal_positions(keys, [positions[i] for i in keys])
        except BaseException:
            self._safe(self.limp)
            raise

    def limp(self) -> None:
        """Zero current and torque off on current-mode joints; other joints keep their goals."""
        current = self._indices(lambda law: law.current_mode)
        if not current:
            return
        self.enabled = False
        try:
            self.bus.write_goal_currents(current, [0.0] * len(current))
        finally:
            self.bus.set_torque(current, False)

    def switch(self, group: str, law: ControlLaw) -> None:
        """Replace one group's law at runtime (leader use). Its joints go limp, change mode, re-enable."""
        index = next((k for k, x in enumerate(self.laws) if x.name == group), None)
        if index is None or sorted(self.laws[index].joints) != sorted(law.joints):
            raise ValueError(f"{self.name}: no group {group!r} with the same joints")
        old = self.laws[index]
        joints = sorted(old.joints)
        if old.current_mode:
            self.bus.write_goal_currents(joints, [0.0] * len(joints))
        self.bus.set_torque(joints, False)
        if law.mode is not None and law.mode != old.mode:
            self.bus.write_eeprom(
                "operating_mode", joints, [OPERATING_MODES[law.mode]] * len(joints)
            )
        if law.current_mode:
            self.bus.write_goal_currents(joints, [0.0] * len(joints))
        self.laws[index] = law
        law.reset(self.read_state())
        if law.mode is not None and self.enabled:
            self.command(self.target)
            self.bus.set_torque(joints, True)
