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
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

from ..core.checks import names as check_names
from ..drivers.base import Health, JointState, read_health, read_state
from ..drivers.dynamixel_table import OPERATING_MODES
from ..dynamics.base import GravityModel, load_gravity_model
from . import LAWS
from .laws import ControlLaw


@dataclass
class GroupSpec:
    name: str
    law: str
    joints: tuple[str, ...]
    cfg: dict


def parse_groups(raw: object, joint_names: tuple[str, ...], owner: str) -> list[GroupSpec]:
    """`control: [{group, law, joints, ...}]`; every joint in exactly one group."""
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{owner}.control must be a non-empty list of groups")
    groups: list[GroupSpec] = []
    seen: list[str] = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("group"), str) or item.get("law") not in LAWS:
            raise ValueError(f"{owner}.control: each group needs a name and law in {sorted(LAWS)}")
        joints = check_names(item.get("joints"), f"{owner}.control.{item['group']}.joints")
        if not set(joints) <= set(joint_names):
            raise ValueError(f"{owner}.control.{item['group']}: unknown joints {sorted(set(joints) - set(joint_names))}")
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


def build_laws(groups: list[GroupSpec], joint_names: tuple[str, ...], base_dir: str | None = None,
               models: dict[str, GravityModel] | None = None) -> list[ControlLaw]:
    """Instantiate each group's law. `models` injects gravity models by group name (tests, tools)."""
    laws = []
    for g in groups:
        gravity: GravityModel | None = (models or {}).get(g.name)
        if gravity is None and g.cfg.get("gravity_model"):
            path = Path(g.cfg["gravity_model"])
            gravity = load_gravity_model(str(path if path.is_absolute() or base_dir is None else Path(base_dir) / path))
        indices = [joint_names.index(j) for j in g.joints]
        laws.append(law_class(g.law)(g.name, indices, joint_names, g.cfg, gravity))
    return laws


def expected_modes(groups: list[GroupSpec]) -> dict[str, float]:
    """Operating Mode each joint must already have (free joints are not checked)."""
    out = {}
    for g in groups:
        mode = law_class(g.law).mode
        if mode is not None:
            out.update({j: float(OPERATING_MODES[mode]) for j in g.joints})
    return out


def check_hardware(groups: list[GroupSpec], cfg: dict, owner: str, current_limits_mA: dict[str, float]) -> None:
    """Refuse current-mode laws on hardware without watchdog and EEPROM current limits."""
    for g in groups:
        cls = law_class(g.law)
        if not cls.hardware_validated and g.cfg.get("allow_unvalidated") is not True:
            raise ValueError(f"{owner}.control.{g.name}: {g.law} is not validated on hardware; set allow_unvalidated: true to override")
        if cls.current_mode:
            if not cfg.get("bus_watchdog_ms"):
                raise ValueError(f"{owner}: current-mode law {g.law} needs bus_watchdog_ms")
            limits = g.cfg.get("max_current_mA")
            per_joint = limits if isinstance(limits, list) else [limits] * len(g.joints)
            for joint, allowed in zip(g.joints, per_joint, strict=True):
                eeprom = current_limits_mA.get(joint)
                if eeprom is None or eeprom > allowed:
                    raise ValueError(f"{owner}: {joint} needs registers.current_limit <= {allowed} mA for {g.law} (motor-side clip)")


class JointDevice:
    def __init__(self, bus, joint_names: tuple[str, ...], laws: list[ControlLaw], name: str = "device"):
        missing = sorted({f"{law.name} ({type(law).__name__}) needs {m}" for law in laws for m in law.needs if not hasattr(bus, m)})
        if missing:
            raise TypeError(f"{name}: {type(bus).__name__} cannot run these control laws: " + "; ".join(missing))
        self.bus, self.joint_names, self.laws, self.name = bus, joint_names, laws, name
        self.state: JointState | None = None
        self.target: list[float] | None = None
        self.enabled = False
        self.last_ns: int | None = None

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
                raise ConnectionError(f"{self.name}: goal current did not read back as zero")
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
            for law in self.laws if law.mode is not None for i in law.joints
            if modes[i] != OPERATING_MODES[law.mode]
        ]
        if wrong:
            raise RuntimeError(f"{self.name}: operating modes differ; run `roboloom commission`:\n  " + "\n  ".join(wrong))

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
            if currents:
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
            self.bus.write_eeprom("operating_mode", joints, [OPERATING_MODES[law.mode]] * len(joints))
        if law.current_mode:
            self.bus.write_goal_currents(joints, [0.0] * len(joints))
        self.laws[index] = law
        law.reset(self.read_state())
        if law.mode is not None and self.enabled:
            self.command(self.target)
            self.bus.set_torque(joints, True)
