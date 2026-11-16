"""CAN interfaces of this host, read from sysfs: no sudo and nothing written.

A follower names its CAN interface either directly (`can: can0`) or by the serial number
of its USB-CAN adapter (`can: {serial: 0029002F5746570A20383839}`). Interface names
follow the order in which adapters enumerate, so `can0` and `can1` can swap after a
reconnect or a reboot; the adapter's serial stays. `resolve` turns the serial into the
interface name when the bus opens.

Bringing an interface up (`ip link set ... type can bitrate 1000000 up`) needs root:
`bring_up_commands` prints the commands for the person or administrator to run.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

SYS_NET = Path("/sys/class/net")
ARPHRD_CAN = 280  # /sys/class/net/<if>/type of a CAN interface
IFF_UP = 0x1
BITRATE = 1_000_000  # PiPER's CAN bitrate
SERIAL_KEY = "serial"


@dataclass(frozen=True)
class CanInterface:
    name: str
    up: bool
    bitrate: int | None  # None: unknown (the `ip` command is unavailable)
    serial: str | None  # the USB adapter's serial number, if it has one
    usb_path: str | None  # the USB port it is plugged into (e.g. 1-5.4), if USB

    @property
    def ready(self) -> bool:
        return self.up and self.bitrate == BITRATE


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def _usb(device: Path) -> tuple[str | None, str | None]:
    """(serial, USB port) of the USB device an interface hangs off: the interface's
    `device` is the USB interface (`1-5.4:1.0`); its parent holds `serial`."""
    try:
        here = device.resolve(strict=True)
    except OSError:
        return None, None
    for directory in (here, *list(here.parents)[:3]):
        serial = _read(directory / "serial")
        if serial is not None:
            return serial, directory.name
    return None, None


def ip_bitrate(name: str) -> int | None:
    """The bitrate `ip -details -json link show` reports (reading needs no root)."""
    ip = shutil.which("ip")
    if ip is None:
        return None
    try:
        out = subprocess.run(
            [ip, "-details", "-json", "link", "show", name],
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        ).stdout
        info = json.loads(out)[0]["linkinfo"]["info_data"]
        return int(info["bittiming"]["bitrate"])
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError):
        return None


def interfaces(
    root: Path = SYS_NET, bitrate: Callable[[str], int | None] = ip_bitrate
) -> list[CanInterface]:
    """Every CAN interface (up or down), sorted by name."""
    found: list[CanInterface] = []
    if not root.is_dir():
        return found
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if _read(entry / "type") != str(ARPHRD_CAN):
            continue
        flags = _read(entry / "flags")
        up = flags is not None and bool(int(flags, 16) & IFF_UP)
        serial, usb_path = _usb(entry / "device")
        found.append(
            CanInterface(entry.name, up, bitrate(entry.name), serial, usb_path)
        )
    return found


def parse_spec(value: object, where: str) -> str | dict[str, str]:
    """A follower's `can`: an interface name, or `{serial: ...}` (the adapter's)."""
    if isinstance(value, dict):
        if set(value) != {SERIAL_KEY}:
            raise ValueError(
                f"{where}: an interface name (can0) or {{serial: <adapter serial>}}"
            )
        serial = value[SERIAL_KEY]
        if not isinstance(serial, str) or not serial or serial.startswith("SET_"):
            raise ValueError(f"{where}.serial: explicit device identity required")
        return {SERIAL_KEY: serial}
    if not isinstance(value, str) or not value or value.startswith("SET_"):
        raise ValueError(f"{where}: explicit device identity required")
    return value


def spec_id(spec: str | dict[str, str]) -> str:
    """One device id per adapter, whichever way a configuration names it."""
    return spec if isinstance(spec, str) else f"can-serial:{spec[SERIAL_KEY]}"


def describe(spec: str | dict[str, str]) -> str:
    return spec if isinstance(spec, str) else f"CAN adapter {spec[SERIAL_KEY]}"


def resolve(
    spec: str | dict[str, str],
    root: Path = SYS_NET,
    bitrate: Callable[[str], int | None] = ip_bitrate,
) -> str:
    """The interface name to open: `spec` itself, or the interface whose adapter has
    the serial. Refuses an adapter that is not plugged in."""
    if isinstance(spec, str):
        return spec
    serial = spec[SERIAL_KEY]
    hits = [i for i in interfaces(root, bitrate) if i.serial == serial]
    if not hits:
        seen = ", ".join(
            f"{i.name} ({i.serial or 'no serial'})" for i in interfaces(root, bitrate)
        )
        raise ConnectionError(
            f"no CAN interface has the adapter {serial} (found: {seen or 'none'}); "
            "check its USB cable, or run `roboloom setup` to find the adapters again"
        )
    if len(hits) > 1:
        raise ConnectionError(f"several CAN interfaces have the adapter {serial}")
    return hits[0].name


def bring_up_commands(name: str, bitrate: int = BITRATE) -> list[str]:
    """What root runs to bring `name` up at `bitrate` (not run by roboloom)."""
    return [
        f"sudo ip link set {name} down",
        f"sudo ip link set {name} type can bitrate {bitrate}",
        f"sudo ip link set {name} up",
    ]
