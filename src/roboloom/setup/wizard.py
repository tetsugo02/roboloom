"""`roboloom setup`: find which device is which and write it into the configuration.

The steps go in order, and each can be run alone (`--step`):

1. `check`: the Python extras, serial-port permissions and the tracker's udev rules.
2. `can`: the CAN interfaces, their state and their USB adapter's serial. Bringing one
   up needs root, so the commands are shown, never run.
3. `arms`: which CAN interface is which PiPER. The person turns a joint of the named
   arm by hand; the one interface whose joints changed is that arm. Arms with motors
   enabled are refused (a disabled PiPER falls, so setup never disables one).
4. `senses`: which serial port is which Pika Sense (open and close the named one).
5. `trackers`: which tracker serial (`LHR-...`) is in which Sense (move the named one),
   after a base-station calibration if libsurvive has none.
6. `grippers`: which serial port is which Pika Gripper (unplug the named one's USB, as
   LeRobot's `lerobot-find-port` does: it cannot be turned by hand).
7. `validate`: load the configuration for the hardware and list what is left.

Identification follows one rule: exactly one candidate must change; with none or several
the step says so and asks again. When one device is left and one candidate, it is
taken without asking. A value the configuration already holds is shown first: Enter
keeps it, `r` finds it again (a quick re-check after swapping a cable or a device).

Setup only reads: nothing is enabled, moved, zeroed or written to a device. Values go
into the node files, each line marked `# roboloom setup <date>`; the rest of the file,
comments included, stays.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import load_config, read_config, resolve_config
from ..drivers import can as can_link
from ..errors import ConfigError, RoboloomError, SetupError
from ..operator import Operator
from .discover import Devices, gripper_state, jaw_angle, kind_of

STEPS = ("check", "can", "arms", "senses", "trackers", "grippers", "validate")
ARM_TYPE, GRIPPER_TYPE, SENSE_TYPE = (
    "piper_follower",
    "pika_gripper_follower",
    "pika_sense",
)
ARM_MOVED_RAD = 0.15  # a joint turned by hand (about 9 degrees)
JAW_MOVED_RAD = 0.3
TRACKER_MOVED_M = 0.15
TRACKER_PREFIX = "LHR-"  # trackers; base stations report other serials
TRACKER_WAIT_S = 5.0
CALIBRATION_WAIT_S = 60.0
POLL_S = 0.05
GRIPPER_ZERO_SLACK_RAD = 0.01  # a closed gripper reading below -this is off zero


@dataclass
class Slot:
    """One node whose device setup identifies."""

    name: str
    type: str
    file: Path
    node: dict

    @property
    def value(self) -> Any:
        if self.type == ARM_TYPE:
            return self.node.get("can")
        return self.node.get("port")

    @property
    def tracker(self) -> dict:
        tracker = self.node.get("tracker")
        return tracker if isinstance(tracker, dict) else {}


def is_set(value: Any) -> bool:
    if isinstance(value, dict):
        value = value.get(can_link.SERIAL_KEY)
    return isinstance(value, str) and bool(value) and not value.startswith("SET_")


def write_value(path: Path, key: str, text: str, note: str) -> None:
    """Set the top-level `key:` line of a node file to `text`, keeping everything else."""
    content = path.read_text()
    line = f"{key}: {text}  # {note}"
    pattern = re.compile(rf"^{re.escape(key)}:.*$", re.MULTILINE)
    if pattern.search(content):
        content = pattern.sub(lambda _: line, content, count=1)
    else:
        content = content.rstrip("\n") + "\n" + line + "\n"
    path.write_text(content)


def quoted(value: str) -> str:
    return json.dumps(
        value
    )  # a YAML double-quoted scalar: serials never turn into numbers


@dataclass
class SetupReport:
    """What a run found and wrote, for the caller to print or check."""

    written: list[str] = field(default_factory=list)  # "node.key = value"
    notes: list[str] = field(default_factory=list)
    valid: bool | None = None


class Setup:
    def __init__(
        self,
        config: str | Path,
        operator: Operator,
        devices: Devices | None = None,
        *,
        today: str | None = None,
    ):
        self.path = (
            resolve_config(config) if not Path(config).is_file() else Path(config)
        )
        self.operator = operator
        self.devices = devices or Devices()
        self.note = f"roboloom setup {today or time.strftime('%Y-%m-%d')}"
        self.report = SetupReport()
        self.slots = self._slots()
        self.links: dict[str, Any] = {}  # serial port -> open link (closed at the end)
        self.kinds: dict[
            str, str | None
        ] = {}  # serial port -> pika_gripper / pika_sense
        self.busy: dict[str, str] = {}  # serial port -> why it could not be opened

    # -- the configuration --------------------------------------------------------

    def _slots(self) -> dict[str, list[Slot]]:
        tree = read_config(self.path, mock=False)
        out: dict[str, list[Slot]] = {ARM_TYPE: [], GRIPPER_TYPE: [], SENSE_TYPE: []}
        for role in ("followers", "inputs"):
            for name, node in (tree.get(role) or {}).items():
                kind = node.get("type")
                if kind in out:
                    out[kind].append(Slot(name, kind, Path(node["__file__"]), node))
        if not any(out.values()):
            raise ConfigError(
                f"{self.path}: no PiPER, Pika Gripper or Pika Sense nodes for setup to "
                "find (it knows piper_follower, pika_gripper_follower and pika_sense)"
            )
        return out

    def _write(self, slot: Slot, key: str, text: str, shown: str) -> None:
        write_value(slot.file, key, text, self.note)
        self.report.written.append(f"{slot.name}.{key} = {shown}")
        self.operator.notify(f"  wrote {slot.name}.{key} = {shown} ({slot.file.name})")

    def _keep(self, slot: Slot, shown: str) -> bool:
        answer = self.operator.prompt(
            f"{slot.name}: {shown} is configured. Enter keeps it, r finds it again: "
        )
        return answer.strip().lower() != "r"

    def _note(self, text: str) -> None:
        self.report.notes.append(text)
        self.operator.notify(f"  note: {text}")

    # -- running ------------------------------------------------------------------

    def run(self, steps: Iterable[str] | None = None) -> SetupReport:
        chosen = list(STEPS if steps is None else steps)
        unknown = [s for s in chosen if s not in STEPS]
        if unknown:
            raise ConfigError(
                f"unknown setup steps {unknown}; steps: {', '.join(STEPS)}"
            )
        try:
            for step in STEPS:
                if step in chosen:
                    self.operator.notify(f"\n== {step} ==")
                    getattr(self, f"step_{step}")()
        finally:
            for link in self.links.values():
                link.close()
            self.links.clear()
        return self.report

    # -- 1. check -----------------------------------------------------------------

    def step_check(self) -> None:
        d = self.devices
        needs = []
        if self.slots[ARM_TYPE]:
            needs.append(("piper_sdk", "the `piper` extra (PiPER over CAN)"))
        if self.slots[GRIPPER_TYPE] or self.slots[SENSE_TYPE]:
            needs.append(("serial", "pyserial (Pika serial links)"))
        if self.slots[SENSE_TYPE]:
            needs.append(
                ("pysurvive", "the `pika` extra (Vive trackers, Linux x86_64)")
            )
        missing = [what for module, what in needs if not d.has_module(module)]
        for what in missing:
            self._note(f"missing {what}: `uv sync --extra piper --extra pika`")
        ports = d.serial_ports()
        blocked = d.unreadable(ports)
        if blocked:
            self._note(
                f"this user cannot open {len(blocked)} serial port(s) (e.g. {blocked[0]}); "
                "ask an administrator to add you to the dialout group, then log in again"
            )
        if self.slots[SENSE_TYPE] and not d.vive_rules():
            self._note(
                "no Vive udev rules found (81-vive.rules from libsurvive); without them "
                "libsurvive cannot open the trackers: ask an administrator"
            )
        if not missing and not blocked:
            self.operator.notify(
                f"  ok: {len(ports)} serial port(s) under /dev/serial/by-path"
            )

    # -- 2. CAN -------------------------------------------------------------------

    def _ready_interfaces(self) -> list[can_link.CanInterface]:
        while True:
            found = self.devices.can_interfaces()
            for i in found:
                rate = "unknown bitrate" if i.bitrate is None else f"{i.bitrate} bit/s"
                self.operator.notify(
                    f"  {i.name}: {'up' if i.up else 'down'}, {rate}, adapter "
                    f"{i.serial or 'without a serial'} on USB {i.usb_path or '?'}"
                )
            if len(found) < len(self.slots[ARM_TYPE]):
                problem = (
                    f"{len(found)} CAN interface(s) for {len(self.slots[ARM_TYPE])} arm(s): "
                    "plug in every arm's USB-CAN adapter"
                )
            elif any(not i.ready for i in found):
                problem = (
                    "bring these interfaces up at 1 Mbps (needs root):\n"
                    + "\n".join(
                        f"    {c}"
                        for i in found
                        if not i.ready
                        for c in can_link.bring_up_commands(i.name)
                    )
                )
            else:
                return found
            self.operator.notify(f"  {problem}")
            answer = self.operator.prompt(
                "  Run them yourself or ask an administrator, then Enter checks again "
                "(q stops): "
            )
            if answer.strip().lower() == "q":
                raise SetupError("CAN interfaces not ready")

    def step_can(self) -> None:
        if not self.slots[ARM_TYPE]:
            self.operator.notify("  no PiPER in this configuration")
            return
        self._ready_interfaces()
        self.operator.notify("  ok: every CAN interface is up at 1 Mbps")

    # -- identification by change ---------------------------------------------------

    def _watch(
        self,
        instruction: str,
        candidates: Sequence[str],
        read: Callable[[str], Any],
        change: Callable[[Any, Any], float],
        threshold: float,
        unit: str,
    ) -> str:
        """Ask for one device to be moved; return the one candidate that changed."""
        while True:
            self.operator.notify(f"  {instruction}; press Enter when done")
            start = {c: read(c) for c in candidates}
            moved = dict.fromkeys(candidates, 0.0)
            while not self.operator.finished():
                for c in candidates:
                    value = read(c)
                    if value is not None and start[c] is not None:
                        moved[c] = max(moved[c], change(start[c], value))
                    elif start[c] is None:
                        start[c] = value
                self.operator.progress(
                    "  "
                    + ", ".join(
                        f"{_short(c)} {moved[c]:.2f} {unit}" for c in candidates
                    )
                )
                self.devices.sleep(POLL_S)
            changed = [c for c in candidates if moved[c] >= threshold]
            if len(changed) == 1:
                return changed[0]
            what = "nothing changed" if not changed else f"{len(changed)} changed"
            self.operator.notify(f"  {what} (needs exactly one); again")

    def _take_last(self, slots: list[Slot], candidates: list[str]) -> str | None:
        if len(slots) == 1 and len(candidates) == 1:
            self.operator.notify(
                f"  {slots[0].name}: the only one left is {_short(candidates[0])}"
            )
            return candidates[0]
        return None

    # -- 3. arms ------------------------------------------------------------------

    def step_arms(self) -> None:
        slots = self.slots[ARM_TYPE]
        if not slots:
            self.operator.notify("  no PiPER in this configuration")
            return
        found = {i.name: i for i in self._ready_interfaces()}
        by_serial = {i.serial: i.name for i in found.values() if i.serial}
        todo, taken = [], set()
        for slot in slots:
            value = slot.value
            if is_set(value) and self._keep(slot, can_link.describe(value)):
                name = (
                    value if isinstance(value, str) else by_serial.get(value["serial"])
                )
                if name is None:
                    self._note(f"{slot.name}: its adapter is not plugged in now")
                taken.add(name)
            else:
                todo.append(slot)
        if not todo:
            return
        links = {}
        try:
            for name in found:
                if name not in taken:
                    links[name] = self.devices.open_arm(name)
            for name, link in links.items():
                if any(link.enable_status()):
                    raise SetupError(
                        f"the arm on {name} has its motors enabled; setup identifies arms "
                        "with motors off and never disables one (it would fall). Support "
                        "it and release it (`roboloom check-hold` ends with release), or "
                        "power the arm off and on at its rest pose, then run setup again"
                    )

            def read(name: str) -> list[float] | None:
                try:
                    return links[name].read_positions()
                except (ConnectionError, RuntimeError):
                    return None

            def change(a: list[float], b: list[float]) -> float:
                return max(abs(x - y) for x, y in zip(a, b, strict=True))

            for i, slot in enumerate(todo):
                left = [n for n in links if n not in taken]
                name = self._take_last(todo[i:], left) or self._watch(
                    f"turn joint1 (the base) of arm {slot.name!r} by hand, about 20 "
                    "degrees, and back",
                    left,
                    read,
                    change,
                    ARM_MOVED_RAD,
                    "rad",
                )
                taken.add(name)
                serial = found[name].serial
                if serial:
                    self._write(
                        slot,
                        "can",
                        f"{{serial: {quoted(serial)}}}",
                        f"adapter {serial} ({name} now)",
                    )
                else:
                    self._write(slot, "can", name, name)
                    self._note(
                        f"{slot.name}: {name}'s adapter reports no serial, so the interface "
                        "name is written; it may change after a reconnect"
                    )
        finally:
            for link in links.values():
                link.close()

    # -- serial ports ---------------------------------------------------------------

    def _classify(self) -> None:
        """Open every serial port once and tell grippers from Senses by what they stream."""
        ports = self.devices.serial_ports()
        fresh = [p for p in ports if p not in self.kinds]
        for port in fresh:
            try:
                self.links[port] = self.devices.open_serial(port)
            except (ConnectionError, OSError) as exc:
                self.busy[port] = str(exc)
                self.kinds[port] = None
        if fresh:
            self.devices.sleep(self.devices.settle_s)
        for port in fresh:
            if port in self.links:
                self.kinds[port] = kind_of(self.links[port])
                if self.kinds[port] is None:  # not a Pika: leave it alone
                    self.links.pop(port).close()
        for port in fresh:
            if port in self.busy:
                self._note(f"could not open {_short(port)}: {self.busy[port]}")
        counts = {
            k: sum(1 for p in ports if self.kinds.get(p) == k)
            for k in ("pika_sense", "pika_gripper")
        }
        self.operator.notify(
            f"  {len(ports)} serial port(s): {counts['pika_sense']} Pika Sense, "
            f"{counts['pika_gripper']} Pika Gripper"
        )

    def _ports(self, kind: str) -> list[str]:
        return [p for p, k in self.kinds.items() if k == kind]

    def _todo(self, slots: list[Slot]) -> tuple[list[Slot], set[str]]:
        todo, taken = [], set()
        for slot in slots:
            if is_set(slot.value) and self._keep(slot, _short(slot.value)):
                taken.add(slot.value)
            else:
                todo.append(slot)
        return todo, taken

    # -- 4. Senses ------------------------------------------------------------------

    def step_senses(self) -> None:
        slots = self.slots[SENSE_TYPE]
        if not slots:
            self.operator.notify("  no Pika Sense in this configuration")
            return
        todo, taken = self._todo(slots)
        if not todo:
            return
        self._classify()
        for i, slot in enumerate(todo):
            left = [p for p in self._ports("pika_sense") if p not in taken]
            if not left:
                raise SetupError(f"{slot.name}: no Pika Sense port left; plug it in")
            port = self._take_last(todo[i:], left) or self._watch(
                f"open and close Pika Sense {slot.name!r} a few times",
                left,
                lambda p: jaw_angle(self.links[p]),
                lambda a, b: abs(b - a),
                JAW_MOVED_RAD,
                "rad",
            )
            taken.add(port)
            self._write(slot, "port", port, port)

    # -- 5. trackers ----------------------------------------------------------------

    def _tracker_serials(self, link: Any, wait_s: float) -> list[str]:
        end = self.devices.clock() + wait_s
        while True:
            serials = sorted(s for s in link.read() if s.startswith(TRACKER_PREFIX))
            if serials or self.devices.clock() >= end:
                return serials
            self.devices.sleep(0.2)

    def step_trackers(self) -> None:
        slots = self.slots[SENSE_TYPE]
        if not slots:
            self.operator.notify("  no Pika Sense in this configuration")
            return
        todo, taken = [], set()
        for slot in slots:
            serial = slot.tracker.get("serial")
            if is_set(serial) and self._keep(slot, f"tracker {serial}"):
                taken.add(serial)
            else:
                todo.append(slot)
        if not todo:
            return
        # libsurvive allows one context per process and host: decide on a calibration
        # before opening it, not by opening a second one
        args: tuple[str, ...] = ()
        if not self.devices.survive_calibrated():
            self.operator.notify(
                "  libsurvive has no calibration here yet (~/.config/libsurvive). The base "
                "stations need one (`--force-calibrate`): put every Sense still where "
                "both base stations see it."
            )
            if not self.operator.confirm("  Calibrate now?"):
                raise SetupError(
                    "no libsurvive calibration; run setup again to calibrate"
                )
            args = ("--force-calibrate",)
        try:
            link = self.devices.open_trackers(args)
        except RoboloomError:
            raise
        except Exception as exc:
            raise SetupError(f"libsurvive did not start: {exc}") from exc
        try:
            wait = CALIBRATION_WAIT_S if args else TRACKER_WAIT_S
            serials = self._tracker_serials(link, wait)
            if not serials:
                raise SetupError(
                    "libsurvive sees no tracker: check the Senses' USB, the base stations' "
                    "power and the udev rules (`roboloom setup --step check`); after "
                    "moving the base stations, remove ~/.config/libsurvive/config.json "
                    "and run setup again to calibrate"
                )
            self.operator.notify(f"  trackers: {', '.join(serials)}")

            def read(serial: str) -> tuple[float, float, float] | None:
                pose = link.read().get(serial)
                if pose is None or not getattr(pose, "tracking", True):
                    return None
                return tuple(pose.position)

            def change(a: Sequence[float], b: Sequence[float]) -> float:
                return sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) ** 0.5

            for i, slot in enumerate(todo):
                left = [s for s in serials if s not in taken]
                if not left:
                    raise SetupError(
                        f"{slot.name}: no tracker left; is its Sense plugged in?"
                    )
                serial = self._take_last(todo[i:], left) or self._watch(
                    f"move Pika Sense {slot.name!r} around (about 30 cm), the others still",
                    left,
                    read,
                    change,
                    TRACKER_MOVED_M,
                    "m",
                )
                taken.add(serial)
                system = slot.tracker.get("system") or "lighthouse"
                self._write(
                    slot,
                    "tracker",
                    f"{{system: {system}, serial: {quoted(serial)}}}",
                    f"tracker {serial}",
                )
        finally:
            link.close()

    # -- 6. grippers ----------------------------------------------------------------

    def _unplugged(self, slot: Slot, candidates: list[str]) -> str:
        for port in candidates:  # let go of the ports before they disappear
            link = self.links.pop(port, None)
            if link is not None:
                link.close()
        while True:
            self.operator.prompt(
                f"  Unplug the USB cable of Pika Gripper {slot.name!r}, then press Enter: "
            )
            now = set(self.devices.serial_ports())
            gone = [p for p in candidates if p not in now]
            if len(gone) == 1:
                break
            what = "no port went away" if not gone else f"{len(gone)} ports went away"
            self.operator.notify(
                f"  {what} (needs exactly one); plug everything back in"
            )
            self.operator.prompt("  Press Enter when every cable is back: ")
        while True:
            self.operator.prompt(
                "  Plug it back into the same USB port, then press Enter: "
            )
            if gone[0] in set(self.devices.serial_ports()):
                return gone[0]
            self.operator.notify(
                f"  {_short(gone[0])} is not back: use the same USB port (the path names the port)"
            )

    def step_grippers(self) -> None:
        slots = self.slots[GRIPPER_TYPE]
        if not slots:
            self.operator.notify("  no Pika Gripper in this configuration")
            return
        todo, taken = self._todo(slots)
        if todo:
            self._classify()
            candidates = [p for p in self._ports("pika_gripper") if p not in taken]
            for i, slot in enumerate(todo):
                left = [p for p in candidates if p not in taken]
                if not left:
                    raise SetupError(
                        f"{slot.name}: no Pika Gripper port left; plug it in"
                    )
                port = self._take_last(todo[i:], left) or self._unplugged(slot, left)
                taken.add(port)
                self._write(slot, "port", port, port)
        for slot in slots:
            self._report_gripper(slot)

    def _report_gripper(self, slot: Slot) -> None:
        written = self._written(slot, "port")
        port = written or (str(slot.value) if is_set(slot.value) else None)
        if port is None:
            return
        link = self.links.get(port)
        opened = False
        if link is None:
            try:
                link = self.devices.open_serial(port)
                opened = True
                self.devices.sleep(self.devices.settle_s)
            except (ConnectionError, OSError) as exc:
                self._note(f"{slot.name}: cannot read {_short(port)}: {exc}")
                return
        try:
            state = gripper_state(link)
        finally:
            if opened:
                link.close()
        if state is None:
            self._note(f"{slot.name}: no gripper feedback on {_short(port)}")
            return
        self.operator.notify(
            f"  {slot.name}: angle {state['angle']:+.4f} rad, enabled {state['enabled']}, "
            f"homed {state['homed']}"
        )
        if state["angle"] < -GRIPPER_ZERO_SLACK_RAD:
            self._note(
                f"{slot.name}: reads {state['angle']:+.4f} rad, below 0 (closed); if it is "
                "closed now, its zero is off (pika_sdk's set_zero; roboloom does not write it)"
            )

    def _written(self, slot: Slot, key: str) -> str | None:
        """The value written for `slot.key` in this run, if any."""
        prefix = f"{slot.name}.{key} = "
        hits = [w[len(prefix) :] for w in self.report.written if w.startswith(prefix)]
        return hits[-1] if hits else None

    # -- 7. validate ----------------------------------------------------------------

    def step_validate(self) -> None:
        try:
            cfg = load_config(self.path, mock=False)
        except (ConfigError, ValueError, TypeError) as exc:
            self.report.valid = False
            self.operator.notify(f"  not ready for the hardware yet:\n  {exc}")
            return
        self.report.valid = True
        for controller in cfg.controllers.values():
            for note in getattr(controller, "notes", list)():
                self._note(note)
        robot = self.path.parent.name
        arms = [s.name for s in self.slots[ARM_TYPE]]
        self.operator.notify(
            "  valid for the hardware. Next (see the tutorial):\n"
            + "".join(
                f"    uv run roboloom check-hold {robot} {arm} --tolerance 0.02\n"
                for arm in arms
            )
            + f"    uv run roboloom run {robot}   # Move home, then double-click a Sense to engage"
        )


def _short(value: Any) -> str:
    text = str(value)
    return text.rsplit("/", 1)[-1] if text.startswith("/dev/") else text


def run_setup(
    config: str | Path,
    operator: Operator,
    steps: Iterable[str] | None = None,
    devices: Devices | None = None,
    today: str | None = None,
) -> SetupReport:
    """Run the setup steps (all of them by default) on configuration `config`."""
    return Setup(config, operator, devices, today=today).run(steps)
