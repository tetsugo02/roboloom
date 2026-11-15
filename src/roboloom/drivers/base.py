"""Bus contract shared by robots and actuated inputs.

`JointBus` is the minimum every bus implements. Richer buses add `read_state`,
`read_health` (and `read_health_field`, one register at a time) and `disable_torque`; callers use the helpers below so a minimal
bus (e.g. one passed to `InProcessSession.from_components`) keeps working.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Protocol


class JointBus(Protocol):
    def read_positions(self) -> list[float]: ...
    def write_positions(self, values: list[float]) -> None: ...
    def enable_torque(self) -> None: ...
    def close(self) -> None: ...


@dataclass
class JointState:
    positions: list[float]
    velocities: list[float] | None = None  # position units per second
    currents_mA: list[float] | None = None
    efforts_Nm: list[float] | None = None  # joint torque, for buses that report it


@dataclass
class Health:
    hardware_error: list[int] = field(default_factory=list)  # per motor, 0 = none
    temperature_c: list[float] = field(default_factory=list)
    watchdog_fired: bool = False
    # problems the bus already put into words (e.g. "joint3: driver over-current"); any
    # entry latches FAULT
    faults: list[str] = field(default_factory=list)


def read_state(bus: JointBus) -> JointState:
    reader = getattr(bus, "read_state", None)
    return reader() if reader else JointState(bus.read_positions())


def read_health(bus: JointBus) -> Health | None:
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


def claim_serial(fd: int, port: str) -> None:
    """Take an opened serial port for this process alone, or raise ConnectionError.

    Two processes on one bus (a running dataflow and a `probe` or `tune-gravity`, two
    runs) garble each other's packets and both then see a failing bus. The lock tells
    that another roboloom process (or anything that locks its port, such as pyserial's
    exclusive mode) already has it; TIOCEXCL then keeps programs that open the port
    later out."""
    try:
        import fcntl
        import termios
    except ImportError:  # not a POSIX system: no such lock
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        raise ConnectionError(
            f"{port} is in use by another process (a running roboloom dataflow, "
            "probe or tune-gravity?); end it first"
        ) from exc
    with contextlib.suppress(OSError):  # not every serial driver knows it
        fcntl.ioctl(fd, termios.TIOCEXCL)


def disable_torque(bus: JointBus) -> None:
    off = getattr(bus, "disable_torque", None)
    if off is None:
        raise RuntimeError(f"{type(bus).__name__} cannot release torque")
    off()
