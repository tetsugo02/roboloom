"""Pika Gripper serial link, bus and follower against fakes (no serial port, no device)."""

from __future__ import annotations

import struct
import threading
import time

import pytest

from roboloom.drivers.pika_gripper import (
    CURRENT_LIMIT,
    DISABLE,
    ENABLE,
    ENABLED,
    POSITION,
    PikaGripperBus,
)
from roboloom.drivers.pika_serial import JsonStream, PikaSerial, encode
from roboloom.robots.pika.follower import PikaGripperFollower
from roboloom.robots.pika.spec import RANGE
from roboloom.robots.safety import FollowerSafety


class Clock:
    def __init__(self) -> None:
        self.now = 50.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


# -- the serial link ------------------------------------------------------------------


def test_commands_are_a_byte_a_float_and_crlf():
    frame = encode(POSITION, 0.5)
    assert frame[0] == 22 and frame[-2:] == b"\r\n" and len(frame) == 7
    assert struct.unpack("<f", frame[1:5])[0] == pytest.approx(0.5)
    with pytest.raises(ValueError):
        encode(256)


def test_json_objects_are_cut_out_of_a_noisy_split_stream():
    stream = JsonStream()
    assert (
        stream.feed(b'tail"}\r\n{"motor": {"Position": 0.1') == []
    )  # mid-object start
    got = stream.feed(b', "Speed": 0.0,},}\r\n{"motorstatus": {"Status": "0x40"}}')
    assert got == [
        {"motor": {"Position": 0.1, "Speed": 0.0}},
        {"motorstatus": {"Status": "0x40"}},
    ]
    assert stream.feed(b'{"bad": [1, 2}\r\n{"Version": "1.2"}') == [{"Version": "1.2"}]
    assert stream.dropped == 1
    assert stream.feed(b"{" + b"x" * 5000) == [] and stream.buffer == ""


class FakeSerial:
    """pyserial's read/in_waiting/write/close over a byte queue the test fills."""

    def __init__(self) -> None:
        self.incoming = bytearray()
        self.written: list[bytes] = []
        self.lock = threading.Lock()
        self.closed = False
        self.unplugged = False

    @property
    def in_waiting(self) -> int:
        return len(self.incoming)

    def read(self, size: int) -> bytes:
        if self.unplugged:
            raise OSError("device disconnected")
        with self.lock:
            data = bytes(self.incoming[:size])
            del self.incoming[:size]
        if not data:
            time.sleep(0.001)
        return data

    def push(self, data: bytes) -> None:
        with self.lock:
            self.incoming += data

    def write(self, data: bytes) -> None:
        self.written.append(data)

    def close(self) -> None:
        self.closed = True


def wait_for(condition, timeout: float = 2.0) -> None:
    end = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.005)


def test_the_receive_thread_keeps_the_latest_value_of_each_key_with_its_time():
    port = FakeSerial()
    link = PikaSerial("/dev/fake", serial=port)
    try:
        port.push(b'{"motor": {"Position": 0.2}, "motorstatus": {"Status": "0x00"}}')
        port.push(b'{"motor": {"Position": 0.3}}')
        wait_for(lambda: link.count("motor") == 2)
        value, stamp = link.latest("motor")
        assert value == {"Position": 0.3} and stamp <= time.monotonic()
        assert link.latest("motorstatus")[0] == {"Status": "0x00"}
        assert link.latest("Version") is None
        link.send(ENABLE)
        link.send_line("GET_INFO")
        assert port.written == [encode(ENABLE), b"GET_INFO\r\n"]
        port.unplugged = True  # the thread stops; the values just go stale
        wait_for(lambda: link.error is not None)
    finally:
        link.close()
    assert port.closed


def test_a_port_that_does_not_open_says_how_to_name_it(monkeypatch):
    def refuse(port):
        raise OSError("No such file or directory")

    monkeypatch.setattr("roboloom.drivers.pika_serial.open_serial", refuse)
    with pytest.raises(ConnectionError, match="/dev/serial/by-path"):
        PikaSerial("/dev/ttyUSB9")


# -- the bus --------------------------------------------------------------------------


class FakeGripper:
    """The parts of PikaSerial the bus uses, acting as a gripper; values stamped `now`."""

    def __init__(self, clock: Clock, *, silent: bool = False, enable_after: int = 1):
        self.clock, self.silent, self.enable_after = clock, silent, enable_after
        self.position, self.current, self.status = 0.4, -120.0, 0x80
        self.temperatures = (35.0, 41.0)
        self.sent: list[tuple[int, float]] = []
        self.lines: list[str] = []
        self.closed = False

    def latest(self, key):
        if self.silent:
            return None
        if key == "motor":
            value = {"Position": self.position, "Speed": 0.1, "Current": self.current}
        elif key == "motorstatus":
            motor, driver = self.temperatures
            value = {
                "Voltage": 24.1,
                "MotorTemp": motor,
                "DriverTemp": driver,
                "Status": f"0x{self.status:02X}",
                "BusCurrent": 30,
            }
        else:
            return None
        return value, self.clock.now

    def count(self, key):
        return 0

    def send(self, cmd, value=0.0):
        self.sent.append((cmd, value))
        if cmd == ENABLE:
            self.enable_after -= 1
            if self.enable_after <= 0:
                self.status |= ENABLED
        elif cmd == DISABLE:
            self.status &= ~ENABLED
        elif cmd == POSITION:
            self.position = value

    def send_line(self, text):
        self.lines.append(text)

    def close(self):
        self.closed = True


def bus(**kwargs):
    clock = Clock()
    device = FakeGripper(clock, **kwargs)
    return (
        PikaGripperBus(
            "/dev/fake", 1.0, transport=device, clock=clock, sleep=clock.sleep
        ),
        device,
        clock,
    )


def test_bus_reads_the_angle_speed_and_current():
    gripper, _, _ = bus()
    assert gripper.read_positions() == [0.4]
    state = gripper.read_state()
    assert state.velocities == [0.1] and state.currents_mA == [-120.0]
    assert gripper.enable_status() == [False]
    health = gripper.read_health()
    assert health.faults == [] and health.temperature_c == [41.0]
    assert health.hardware_error == [0]  # "homed" is not an error


def test_bus_refuses_a_silent_or_stale_gripper():
    with pytest.raises(ConnectionError, match="no motor, motorstatus feedback"):
        bus(silent=True)
    gripper, device, clock = bus()
    device.latest = lambda key, old=device.latest: (old(key)[0], clock.now - 0.5)
    with pytest.raises(ConnectionError, match="500 ms old"):
        gripper.read_positions()


def test_enabling_sets_the_current_limit_first_and_retries():
    gripper, device, _ = bus(enable_after=3)
    gripper.enable_torque()
    assert device.sent[0] == (CURRENT_LIMIT, 1.0)
    assert [c for c, _ in device.sent[1:]] == [ENABLE] * 3
    assert gripper.enable_status() == [True]
    gripper.write_positions([0.7])
    assert device.sent[-1] == (POSITION, 0.7) and device.position == 0.7
    with pytest.raises(ValueError):
        gripper.write_positions([0.1, 0.2])
    gripper.close()  # closing leaves the motor enabled
    assert device.closed and device.status & ENABLED
    stuck, _, _ = bus(enable_after=10**6)
    with pytest.raises(RuntimeError, match="did not enable"):
        stuck.enable_torque()


def test_status_faults_latch_the_follower():
    gripper, device, _ = bus()
    follower = PikaGripperFollower("left_gripper", follower_cfg())
    safety = FollowerSafety(follower.safety_config(), gripper)
    safety.start()
    for _ in range(10):
        state, _ = safety.tick()
    assert safety.mode == "HOLD" and state.payload["currents_mA"] == [-120.0]
    device.status |= 0x04  # over-current
    for _ in range(10):
        safety.tick()
    assert safety.mode == "FAULT" and "over-current" in safety.reason


def test_a_motor_that_drops_out_after_enabling_is_a_fault():
    gripper, device, _ = bus()
    gripper.enable_torque()
    device.status &= ~ENABLED
    assert "gripper: motor disabled" in gripper.read_health().faults
    gripper.disable_torque()
    assert gripper.read_health().faults == []


# -- the follower ---------------------------------------------------------------------


def follower_cfg(**extra) -> dict:
    low, high = RANGE["gripper"]
    return {
        "type": "pika_gripper_follower",
        "port": "/dev/serial/by-path/pci-0000:00:14.0-usb-0:2:1.0-port0",
        "control_hz": 100,
        "current_limit_A": 1.0,
        "limits": [
            {
                "name": "gripper",
                "min": low,
                "max": high,
                "max_speed": 3.0,
                "max_jump": 0.5,
            }
        ],
        "health": {"every_ticks": 10},
        **extra,
    }


def test_follower_checks_its_configuration():
    follower = PikaGripperFollower("left_gripper", follower_cfg())
    assert follower.unit == "rad" and follower.joint_names == ("gripper",)
    assert follower.traits().torque_off == "lets_go"
    assert follower.traits().unattended == "unknown"
    assert follower.device_ids() == (follower_cfg()["port"],)
    over = [{**follower_cfg()["limits"][0], "max": 2.0}]
    for bad, match in (
        ({"limits": over}, "exceeds the Pika Gripper range"),
        ({"current_limit_A": 0}, "current_limit_A"),
        ({"current_limit_A": 3.0}, "current_limit_A"),
        ({"current_limit_A": True}, "current_limit_A"),
        ({"port": "SET_PORT"}, "explicit device identity"),
        ({"health": None}, "health: required"),
        ({"control": []}, "own position control"),
    ):
        with pytest.raises(ValueError, match=match):
            PikaGripperFollower("left_gripper", {**follower_cfg(), **bad})


def test_mock_follower_opens_closed():
    follower = PikaGripperFollower("left_gripper", follower_cfg())
    assert follower.open_device(mock=True).read_positions() == [0.0]


def test_probe_reads_a_pika_gripper_without_enabling_it(monkeypatch):
    from roboloom.drivers import pika_gripper
    from roboloom.probe import probe

    clock = Clock()
    device = FakeGripper(clock)
    real = PikaGripperBus

    def fake_bus(port, current_limit_A, **kwargs):
        return real(
            port, current_limit_A, transport=device, clock=clock, sleep=clock.sleep
        )

    monkeypatch.setattr(pika_gripper, "PikaGripperBus", fake_bus)
    monkeypatch.setattr(pika_gripper.time, "sleep", lambda s: None)
    text = probe("/dev/fake", device="pika")
    assert "angle +0.4000 rad" in text and "homed True" in text
    assert "faults: none" in text
    assert device.lines == ["GET_INFO"] and device.sent == [] and device.closed
    with pytest.raises(ValueError, match="unknown device"):
        probe("/dev/fake", device="gello")


def test_a_policy_drives_two_pipers_and_two_grippers(tmp_path, monkeypatch):
    """The Pika Grippers are followers of their own beside the PiPER arms."""
    import json
    import os
    from pathlib import Path

    import yaml
    from test_piper import piper_project

    from roboloom.runtime.session import Session

    tests = str(Path(__file__).parent.resolve())
    monkeypatch.setenv(
        "PYTHONPATH", os.pathsep.join([tests, os.environ.get("PYTHONPATH", "")])
    )
    path = piper_project(tmp_path)
    nodes = path.parent / "nodes"
    config = yaml.safe_load(path.read_text())
    policy = yaml.safe_load((nodes / "policy.yaml").read_text())
    recorder = yaml.safe_load((nodes / "recorder.yaml").read_text())
    for side in ("left", "right"):
        name = f"{side}_gripper"
        cfg = follower_cfg(port=f"/dev/serial/by-path/mock-{side}")
        (nodes / f"{name}.yaml").write_text(yaml.safe_dump(cfg))
        config["followers"][name] = f"nodes/{name}.yaml"
        policy["followers"].append(name)
        policy["max_speed"][name] = 1.0
        recorder["max_age_ms"][name] = 300
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    (nodes / "policy.yaml").write_text(yaml.safe_dump(policy))
    (nodes / "recorder.yaml").write_text(yaml.safe_dump(recorder))
    with Session.launch(
        path, policy_kwargs={"step": 0.01}, log_dir=tmp_path / "logs"
    ) as s:
        assert s.held == []
        assert set(s.limp_at_end) == {"left", "right", "left_gripper", "right_gripper"}
        s.wait_ready(30)
        result = s.record("creep", 1.5)
        gripper = s.status()["left_gripper"]["fields"]
    assert gripper["torque_off"] == "lets_go" and gripper["unattended"] == "unknown"
    assert result.saved, result
    info = json.loads((path.parent / "datasets/piper/meta/info.json").read_text())
    action = info["features"]["action"]
    assert action["shape"] == [14]
    assert action["names"][12:] == ["left_gripper.gripper", "right_gripper.gripper"]


def test_check_hold_measures_a_gripper():
    from roboloom.setup.hold import hold_trial

    gripper, device, clock = bus()
    follower = PikaGripperFollower("left_gripper", follower_cfg())
    result = hold_trial(follower, gripper, 1.0, 0.01, sleep=clock.sleep, clock=clock)
    assert result.holds and result.enabled == [True]
    assert result.unattended == "holds" and not device.closed
