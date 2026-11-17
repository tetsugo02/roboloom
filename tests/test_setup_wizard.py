"""`roboloom setup`: identifying PiPER arms, Pika Senses, trackers and grippers by change,
against fake devices, and writing them into a project made from the piper-pika template."""

from __future__ import annotations

import re
from collections.abc import Callable
from types import SimpleNamespace

import pytest
import yaml

from roboloom.drivers.can import CanInterface
from roboloom.errors import SetupError
from roboloom.project import init_project
from roboloom.setup.discover import Devices
from roboloom.setup.wizard import Setup, write_value

BY_PATH = "/dev/serial/by-path/pci-0000:00:14.0-usb-0:"


class FakeArm:
    def __init__(self) -> None:
        self.positions = [0.0, -0.03, 0.07, 0.0, 0.35, 0.28]
        self.enabled = [False] * 6
        self.closed = False

    def read_positions(self) -> list[float]:
        return list(self.positions)

    def enable_status(self) -> list[bool]:
        return list(self.enabled)

    def close(self) -> None:
        self.closed = True


class FakeSerial:
    def __init__(self, kind: str) -> None:
        if kind == "sense":
            self.values = {"AS5047": {"rad": 0.0}, "Command": 0}
        elif kind == "other":
            self.values = {}
        else:
            self.values = {
                "motor": {"Position": -0.0146},
                "motorstatus": {"Status": "0x00"},
            }

    def latest(self, key):
        return (self.values[key], 0.0) if key in self.values else None

    def count(self, key) -> int:
        return 10 if key in self.values else 0

    def close(self) -> None:
        pass


class FakeTrackers:
    def __init__(self, serials) -> None:
        self.poses = {
            s: SimpleNamespace(position=(0.0, 0.0, 1.0), tracking=True) for s in serials
        }
        self.opened_with: list[tuple] = []

    def read(self):
        return dict(self.poses)

    def close(self) -> None:
        pass


class Bench:
    """The lab table: which physical device sits behind which interface or port."""

    def __init__(self) -> None:
        self.arms = {
            "can0": FakeArm(),
            "can1": FakeArm(),
        }  # right on can0, left on can1
        self.side_of_can = {"can0": "right", "can1": "left"}
        self.ports = {
            BY_PATH + "2.4:1.0-port0": FakeSerial("sense"),  # right Sense
            BY_PATH + "3.4:1.0-port0": FakeSerial("sense"),  # left Sense
            BY_PATH + "5.3.4:1.0-port0": FakeSerial("gripper"),  # left gripper
            BY_PATH + "5.4.4:1.0-port0": FakeSerial("gripper"),  # right gripper
            BY_PATH + "9.9:1.0-port0": None,  # something else (not a Pika)
        }
        self.sense = {
            "right": BY_PATH + "2.4:1.0-port0",
            "left": BY_PATH + "3.4:1.0-port0",
        }
        self.gripper = {
            "left": BY_PATH + "5.3.4:1.0-port0",
            "right": BY_PATH + "5.4.4:1.0-port0",
        }
        self.trackers = FakeTrackers(["LHR-CB8E8A3D", "LHR-F7BA2042", "LHB-BASE01"])
        self.tracker = {"right": "LHR-CB8E8A3D", "left": "LHR-F7BA2042"}
        self.unplugged: set[str] = set()
        self.tracker_args: list[tuple] = []

    def devices(self) -> Devices:
        def open_serial(port):
            link = self.ports[port]
            return link if link is not None else FakeSerial("other")

        def open_trackers(args):
            self.tracker_args.append(tuple(args))
            return self.trackers

        ticks = iter(range(10**6))
        return Devices(
            can_interfaces=lambda: [
                CanInterface(
                    "can0", True, 1_000_000, "001D00285746571620383839", "1-5.1"
                ),
                CanInterface(
                    "can1", True, 1_000_000, "0029002F5746570A20383839", "1-5.2"
                ),
            ],
            serial_ports=lambda: [p for p in self.ports if p not in self.unplugged],
            open_arm=lambda name: self.arms[name],
            open_serial=open_serial,
            open_trackers=open_trackers,
            has_module=lambda name: True,
            survive_calibrated=lambda: True,
            vive_rules=lambda: ["/etc/udev/rules.d/81-vive.rules"],
            unreadable=lambda ports: [],
            clock=lambda: float(next(ticks)),
            sleep=lambda s: None,
            settle_s=0.0,
        )

    # what the person at the table does when asked
    def turn(self, side: str) -> None:
        can = next(c for c, s in self.side_of_can.items() if s == side)
        self.arms[can].positions[0] += 0.35

    def squeeze(self, side: str) -> None:
        self.ports[self.sense[side]].values["AS5047"] = {"rad": 1.2}

    def wave(self, side: str) -> None:
        self.trackers.poses[self.tracker[side]].position = (0.3, 0.1, 1.2)


class Person:
    """An `Operator` that does what the instructions ask on the bench."""

    def __init__(
        self,
        bench: Bench,
        answers=(),
        confirm: bool = True,
        act: Callable | None = None,
    ):
        self.bench, self.answers, self.answer = bench, list(answers), confirm
        self.pending: Callable[[], None] | None = None
        self.log: list[str] = []
        self.act = act or self.default

    def default(self, message: str) -> Callable[[], None] | None:
        for pattern, action in (
            (r"joint1 \(the base\) of arm '(\w+)'", self.bench.turn),
            (r"open and close Pika Sense '(\w+)_sense'", self.bench.squeeze),
            (r"move Pika Sense '(\w+)_sense'", self.bench.wave),
        ):
            found = re.search(pattern, message)
            if found:
                side = found.group(1)
                return lambda side=side, action=action: action(side)
        return None

    def notify(self, message: str) -> None:
        self.log.append(message)
        action = self.act(message)
        if action is not None:
            self.pending = action

    def progress(self, message: str) -> None:
        pass

    def finished(self) -> bool:
        if self.pending is not None:  # the person moves the device, then presses Enter
            self.pending()
            self.pending = None
            return False
        return True

    def confirm(self, message: str) -> bool:
        self.log.append(message)
        return self.answer

    def prompt(self, message: str) -> str:
        self.log.append(message)
        unplug = re.search(
            r"Unplug the USB cable of Pika Gripper '(\w+)_gripper'", message
        )
        if unplug:
            self.bench.unplugged.add(self.bench.gripper[unplug.group(1)])
        if "Plug it back" in message:
            self.bench.unplugged.clear()
        return self.answers.pop(0) if self.answers else ""


@pytest.fixture
def project(tmp_path):
    init_project("piper-pika", tmp_path / ".roboloom")
    return tmp_path / ".roboloom" / "piper-pika" / "config.yaml"


def node(project, name: str) -> dict:
    return yaml.safe_load((project.parent / "nodes" / f"{name}.yaml").read_text())


def test_setup_finds_every_device_by_its_change_and_writes_the_configuration(project):
    bench = Bench()
    person = Person(bench)
    report = Setup(project, person, bench.devices(), today="2026-11-17").run()
    assert node(project, "left")["can"] == {"serial": "0029002F5746570A20383839"}
    assert node(project, "right")["can"] == {"serial": "001D00285746571620383839"}
    assert node(project, "left_sense")["port"] == bench.sense["left"]
    assert node(project, "right_sense")["port"] == bench.sense["right"]
    assert node(project, "left_sense")["tracker"] == {
        "system": "lighthouse",
        "serial": "LHR-F7BA2042",
    }
    assert node(project, "right_sense")["tracker"]["serial"] == "LHR-CB8E8A3D"
    assert node(project, "left_gripper")["port"] == bench.gripper["left"]
    assert node(project, "right_gripper")["port"] == bench.gripper["right"]
    assert report.valid is True and len(report.written) == 8
    text = (project.parent / "nodes" / "left.yaml").read_text()
    assert "# roboloom setup 2026-11-17" in text and "# The left PiPER" in text
    assert any("below 0 (closed)" in n for n in report.notes)  # the gripper's zero
    assert any("no workspace" in n for n in report.notes)
    assert all(arm.closed for arm in bench.arms.values())
    # the second time, what is configured is kept with Enter
    again = Setup(project, Person(bench), bench.devices()).run(
        ["arms", "senses", "trackers", "grippers"]
    )
    assert again.written == []


def test_exactly_one_must_change_or_the_step_asks_again(project):
    bench = Bench()
    tries = {"n": 0}

    def act(message):
        found = re.search(r"of arm '(\w+)'", message)
        if not found:
            return None
        tries["n"] += 1
        if tries["n"] == 1:  # both arms bumped: ambiguous
            return lambda: (bench.turn("left"), bench.turn("right"))
        side = found.group(1)
        return lambda: bench.turn(side)

    person = Person(bench, act=act)
    Setup(project, person, bench.devices()).run(["arms"])
    assert any("2 changed (needs exactly one)" in line for line in person.log)
    assert node(project, "left")["can"] == {"serial": "0029002F5746570A20383839"}


def test_an_arm_with_motors_enabled_is_refused_and_never_disabled(project):
    bench = Bench()
    bench.arms["can0"].enabled = [True] * 6
    with pytest.raises(SetupError, match="motors enabled"):
        Setup(project, Person(bench), bench.devices()).run(["arms"])
    assert bench.arms["can0"].enabled == [True] * 6
    assert node(project, "left")["can"] == {"serial": "SET_LEFT_CAN_SERIAL"}


def test_down_can_interfaces_get_the_commands_to_run(project):
    bench = Bench()
    devices = bench.devices()
    devices.can_interfaces = lambda: [
        CanInterface("can0", False, None, "A", "1-5.1"),
        CanInterface("can1", True, 1_000_000, "B", "1-5.2"),
    ]
    person = Person(bench, answers=["q"])
    with pytest.raises(SetupError, match="not ready"):
        Setup(project, person, devices).run(["can"])
    assert any(
        "sudo ip link set can0 type can bitrate 1000000" in m for m in person.log
    )


def test_without_a_libsurvive_calibration_setup_offers_one_first(project):
    bench = Bench()
    devices = bench.devices()
    devices.survive_calibrated = lambda: False
    declined = Person(bench, confirm=False)
    with pytest.raises(SetupError, match="no libsurvive calibration"):
        Setup(project, declined, devices).run(["trackers"])
    assert bench.tracker_args == []
    Setup(project, Person(bench), devices).run(["trackers"])
    assert bench.tracker_args == [("--force-calibrate",)]  # one context only
    assert node(project, "left_sense")["tracker"]["serial"] == "LHR-F7BA2042"


def test_no_tracker_seen_explains_what_to_check(project):
    bench = Bench()
    bench.trackers.poses = {}
    with pytest.raises(SetupError, match="sees no tracker"):
        Setup(project, Person(bench), bench.devices()).run(["trackers"])


def test_the_template_runs_on_mock_devices(project):
    from roboloom.config import load_config

    cfg = load_config(project, mock=True)
    assert list(cfg.followers) == ["left", "right", "left_gripper", "right_gripper"]
    assert set(cfg.controllers) == {"left_ik", "right_ik"}


def test_values_are_written_without_touching_the_rest(tmp_path):
    path = tmp_path / "n.yaml"
    path.write_text("# head\ntype: x\nport: SET_PORT  # old\nother: 1\n")
    write_value(path, "port", '"/dev/serial/by-path/a:1.0"', "roboloom setup today")
    assert path.read_text() == (
        '# head\ntype: x\nport: "/dev/serial/by-path/a:1.0"  # roboloom setup today\n'
        "other: 1\n"
    )
