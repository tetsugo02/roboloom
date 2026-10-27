"""Bus contract shared by robots and actuated inputs.

`RobotBus` is the minimum every bus implements. Richer buses add `read_state`,
`read_health` (and `read_health_field`, one register at a time) and `disable_torque`; callers use the helpers below so a minimal
bus (e.g. one passed to `Experiment.from_components`) keeps working.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class RobotBus(Protocol):
    def read_positions(self) -> list[float]: ...
    def write_positions(self, values: list[float]) -> None: ...
    def enable_torque(self) -> None: ...
    def close(self) -> None: ...


@dataclass
class JointState:
    positions: list[float]
    velocities: list[float] | None = None  # position units per second
    currents_mA: list[float] | None = None


@dataclass
class Health:
    hardware_error: list[int] = field(default_factory=list)  # per motor, 0 = none
    temperature_c: list[float] = field(default_factory=list)
    watchdog_fired: bool = False


def read_state(bus: RobotBus) -> JointState:
    reader = getattr(bus, "read_state", None)
    return reader() if reader else JointState(bus.read_positions())


def read_health(bus: RobotBus) -> Health | None:
    reader = getattr(bus, "read_health", None)
    return reader() if reader else None


# Registers a bus may read one at a time (`read_health_field`), most urgent first.
HEALTH_FIELDS = ("bus_watchdog", "hardware_error", "present_temperature")


def health_from(values: dict[str, list[int]]) -> Health:
    """Health from the HEALTH_FIELDS read so far (missing ones count as healthy)."""
    return Health(
        hardware_error=list(values.get("hardware_error", [])),
        temperature_c=[float(x) for x in values.get("present_temperature", [])],
        watchdog_fired=any(x < 0 for x in values.get("bus_watchdog", [])),
    )


def disable_torque(bus: RobotBus) -> None:
    off = getattr(bus, "disable_torque", None)
    if off is None:
        raise RuntimeError(f"{type(bus).__name__} cannot release torque")
    off()
