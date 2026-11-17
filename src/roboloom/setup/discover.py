"""What is plugged into this host, for `roboloom setup`: read-only.

Each function lists one kind of device or opens it to read. Nothing is enabled, moved or
written. `Devices` bundles them so the setup steps can be run against fakes in tests.
"""

from __future__ import annotations

import importlib.util
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..drivers import can as can_link

BY_PATH = Path("/dev/serial/by-path")
# keys each Pika device streams (`drivers.pika_gripper`, `drivers.pika_sense`)
GRIPPER_KEYS = ("motor", "motorstatus")
SENSE_KEYS = ("AS5047", "Command")
UDEV_DIRS = (Path("/etc/udev/rules.d"), Path("/lib/udev/rules.d"))


class ArmLink(Protocol):
    """A PiPER read over CAN (`drivers.piper.PiperBus`)."""

    def read_positions(self) -> list[float]: ...
    def enable_status(self) -> list[bool]: ...
    def close(self) -> None: ...


class SerialLink(Protocol):
    """A Pika serial link (`drivers.pika_serial.PikaSerial`)."""

    def latest(self, key: str) -> tuple[Any, float] | None: ...
    def count(self, key: str) -> int: ...
    def close(self) -> None: ...


class TrackerLink(Protocol):
    """Every tracker libsurvive sees (`drivers.survive.SurviveSystem`)."""

    def read(self) -> dict[str, Any]: ...
    def close(self) -> None: ...


def serial_ports(root: Path = BY_PATH) -> list[str]:
    """The stable path of every USB serial port (`/dev/serial/by-path/...`)."""
    if not root.is_dir():
        return []
    return sorted(str(p) for p in root.iterdir())


def open_arm(interface: str) -> ArmLink:
    from ..drivers.piper import PiperBus

    return PiperBus(interface, speed_percent=1)  # opening only reads


def open_serial(port: str) -> SerialLink:
    from ..drivers.pika_serial import PikaSerial

    return PikaSerial(port)


def open_trackers(args: Sequence[str] = ()) -> TrackerLink:
    from ..drivers.survive import SurviveSystem

    return SurviveSystem(args)


def kind_of(link: SerialLink) -> str | None:
    """`pika_gripper`, `pika_sense` or None, from the keys the device streamed."""
    if all(link.count(k) for k in GRIPPER_KEYS):
        return "pika_gripper"
    if all(link.count(k) for k in SENSE_KEYS):
        return "pika_sense"
    return None


def jaw_angle(link: SerialLink) -> float | None:
    got = link.latest("AS5047")
    if got is None or not isinstance(got[0], dict) or "rad" not in got[0]:
        return None
    return float(got[0]["rad"])


def gripper_state(link: SerialLink) -> dict[str, Any] | None:
    """Angle (rad), enabled and homed of a Pika Gripper, from its latest feedback."""
    from ..drivers.pika_gripper import ENABLED, HOMED, status_bits

    motor, status = link.latest("motor"), link.latest("motorstatus")
    if motor is None or status is None:
        return None
    try:
        code = status_bits(status[0].get("Status", 0))
        angle = float(motor[0]["Position"])
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    return {
        "angle": angle,
        "enabled": bool(code & ENABLED),
        "homed": bool(code & HOMED),
    }


def survive_calibrated(home: Path | None = None) -> bool:
    """Whether libsurvive saved a base-station calibration for this user."""
    return ((home or Path.home()) / ".config" / "libsurvive" / "config.json").is_file()


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def vive_rules(dirs: Sequence[Path] = UDEV_DIRS) -> list[str]:
    """udev rule files that look like the Vive / libsurvive ones (`81-vive.rules`)."""
    found = []
    for directory in dirs:
        if directory.is_dir():
            found += [
                str(p)
                for p in sorted(directory.iterdir())
                if "vive" in p.name.lower() or "survive" in p.name.lower()
            ]
    return found


def unreadable(ports: Sequence[str]) -> list[str]:
    """Ports this user may not open (not in the `dialout` group, typically)."""
    return [p for p in ports if not os.access(p, os.R_OK | os.W_OK)]


@dataclass
class Devices:
    """How the setup steps reach the hardware; tests replace each with a fake."""

    can_interfaces: Callable[[], list[can_link.CanInterface]] = can_link.interfaces
    serial_ports: Callable[[], list[str]] = serial_ports
    open_arm: Callable[[str], ArmLink] = open_arm
    open_serial: Callable[[str], SerialLink] = open_serial
    open_trackers: Callable[[Sequence[str]], TrackerLink] = open_trackers
    has_module: Callable[[str], bool] = has_module
    survive_calibrated: Callable[[], bool] = survive_calibrated
    vive_rules: Callable[[], list[str]] = vive_rules
    unreadable: Callable[[Sequence[str]], list[str]] = unreadable
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    settle_s: float = 1.0  # how long a freshly opened link is read before judging it
