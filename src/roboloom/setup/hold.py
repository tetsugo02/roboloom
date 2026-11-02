"""Bench test: does a follower keep its pose once roboloom stops commanding it?

This fills in a follower model's `unattended: unknown` safety trait (core.traits) for one
unit: hold the arm at its pose, then stop writing to it without releasing torque (as a
quit with the followers holding, an ESTOP or a FAULT do) and watch the joints.

The bus stays open and is only read while watching: closing and reopening a CAN
interface within one process is not reliable with piper_sdk. What a driver's own
`close()` does to the motors is known from its code; a model whose `close()` releases
them declares `unattended: torque_off` instead of measuring it.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..config import RobotConfig
from ..drivers.base import JointBus, disable_torque
from ..errors import Cancelled, ConfigError
from ..operator import Operator
from ..robots.base import Follower
from ..robots.safety import FollowerSafety
from .common import load, require_hardware

HOLD_BEFORE_S = 2.0  # commanded hold before letting go
READ_HZ = 20.0


@dataclass
class HoldResult:
    follower: str
    unit: str
    seconds: float  # how long it was watched (shorter when it moved away)
    tolerance: float
    drift: dict[str, float]  # largest change per joint while left alone
    enabled: list[bool] | None  # the motors' enable state at the end, when the bus says

    @property
    def worst(self) -> tuple[str, float]:
        joint = max(self.drift, key=lambda j: abs(self.drift[j]))
        return joint, self.drift[joint]

    @property
    def holds(self) -> bool:
        return abs(self.worst[1]) <= self.tolerance and all(self.enabled or [True])

    @property
    def unattended(self) -> str:
        return "holds" if self.holds else "torque_off"

    def lines(self) -> list[str]:
        joint, drift = self.worst
        out = [
            (
                f"{self.follower}: left alone for {self.seconds:.1f} s; largest change "
                f"{drift:+.4g} {self.unit} at {joint} (tolerance {self.tolerance:g})"
            )
        ]
        if self.enabled is not None:
            off = [i + 1 for i, on in enumerate(self.enabled) if not on]
            out.append(
                "motors still enabled" if not off else f"motors {off} became disabled"
            )
        out.append(
            f"result: unattended: {self.unattended}"
            + ("" if self.holds else " (it does not hold: keep supporting it)")
        )
        return out


def hold_trial(
    follower: Follower,
    bus: JointBus,
    seconds: float,
    tolerance: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> HoldResult:
    """Hold for HOLD_BEFORE_S, stop writing (torque stays on), then watch for up to
    `seconds`, stopping early once a joint moved beyond `tolerance`. The motors are left
    as they ended up; the caller decides whether to release them."""
    safety = FollowerSafety(follower.safety_config(), bus)
    safety.start()  # the current pose becomes the target, then torque on
    if safety.mode != "HOLD":
        raise ConfigError(f"{follower.name}: could not hold ({safety.mode})")
    end = clock() + HOLD_BEFORE_S
    while clock() < end:
        safety.tick()
        sleep(1 / follower.control_hz)
    if safety.mode != "HOLD":
        raise ConfigError(
            f"{follower.name}: {safety.mode} while holding ({safety.reason})"
        )
    start = list(safety.hold_target or bus.read_positions())
    drift = dict.fromkeys(follower.joint_names, 0.0)
    began = clock()
    while clock() - began < seconds:  # from here on nothing is written
        now = bus.read_positions()
        for joint, a, b in zip(follower.joint_names, start, now, strict=True):
            if abs(b - a) > abs(drift[joint]):
                drift[joint] = b - a
        if max(abs(d) for d in drift.values()) > tolerance:
            break  # it is moving away: stop and tell the operator
        sleep(1 / READ_HZ)
    status = getattr(bus, "enable_status", None)
    enabled = list(status()) if status is not None else None
    return HoldResult(
        follower.name, follower.unit, clock() - began, tolerance, drift, enabled
    )


def record_unattended(path: Path, value: str, note: str) -> None:
    """Write `unattended: <value>  # note` into the follower YAML, keeping the rest."""
    text = path.read_text()
    line = f"unattended: {value}  # {note}"
    pattern = re.compile(r"^unattended:.*$", re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(line, text, count=1)
    else:
        text = text.rstrip("\n") + "\n" + line + "\n"
    path.write_text(text)


def check_hold(
    config: str | Path | RobotConfig,
    follower: str,
    operator: Operator,
    tolerance: float,
    seconds: float = 10.0,
) -> HoldResult:
    cfg = load(config)
    model = cfg.followers.get(follower)
    if model is None:
        raise ConfigError(f"{follower}: no such follower in {cfg.path}")
    require_hardware(cfg, "check-hold")
    if not model.torque:
        raise ConfigError(f"{follower}: torque: false; check-hold needs torque")
    declared = model.declared_traits().unattended
    if declared != "unknown":
        raise ConfigError(
            f"{follower}: {model.model} declares unattended: {declared}; "
            "check-hold measures only an unknown one"
        )
    if tolerance <= 0 or seconds <= 0:
        raise ConfigError("check-hold: tolerance and seconds must be positive")
    if not operator.confirm(
        f"{follower} will hold its current pose for {HOLD_BEFORE_S:g} s, then roboloom "
        f"stops commanding it for up to {seconds:g} s. It may fall: support it and "
        "clear the space around it."
    ):
        raise Cancelled("check-hold cancelled")
    bus = model.open_device(False)
    try:
        result = hold_trial(model, bus, seconds, tolerance)
        for line in result.lines():
            operator.notify(line)
        path = Path(str(model.cfg.get("__file__", "")))
        answer = operator.prompt(
            f"Type 'record' to write 'unattended: {result.unattended}' to {path.name}; "
            "Enter skips: "
        )
        if answer == "record":
            if not path.is_file():
                raise ConfigError(f"{follower}: its YAML file is unknown; not recorded")
            joint, drift = result.worst
            record_unattended(
                path,
                result.unattended,
                f"roboloom check-hold {datetime.now().astimezone().date().isoformat()}: "
                f"{drift:+.4g} {result.unit} at {joint} over {result.seconds:.1f} s",
            )
            operator.notify(f"recorded in {path}")
        answer = operator.prompt(
            f"Enter leaves {follower} as it is; 'release' turns its torque off "
            "(support it first): "
        )
        if answer == "release":
            disable_torque(bus)
            operator.notify(f"{follower}: torque off")
    except BaseException:
        # whatever failed, the motors may still be on with nothing commanding them
        operator.notify(
            f"{follower} may still have torque with nothing commanding it: support it, "
            "then power it off or run roboloom again"
        )
        raise
    finally:
        bus.close()
    return result
