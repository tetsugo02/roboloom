"""PiPER bus and follower against a fake piper_sdk interface (no CAN, no SDK import)."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from roboloom.drivers.piper import FOC_ENABLED, PiperBus
from roboloom.robots.piper.follower import PiperFollower
from roboloom.robots.piper.spec import JOINTS, RANGE
from roboloom.robots.safety import FollowerSafety


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeSdk:
    """The parts of C_PiperInterface_V2 PiperBus uses; frames stamped by `clock`."""

    def __init__(self, clock: Clock, *, silent: bool = False, enable_after: int = 1):
        self.clock, self.silent, self.enable_after = clock, silent, enable_after
        self.sent: list[tuple] = []
        self.millideg = [0] * 6
        self.enabled = False
        self.enable_calls = 0
        self.foc = [0] * 6
        self.ctrl_mode, self.arm_status = 1, 0
        self.comm_error: set[int] = set()
        self.stamp_lag = 0.0  # how old every frame is
        self.stops_at: float | None = None  # frames stop arriving at this time

    def _stamp(self) -> float:
        if self.silent:
            return 0.0
        now = self.clock() - self.stamp_lag
        return now if self.stops_at is None else min(now, self.stops_at)

    def GetArmJointMsgs(self):
        joints = SimpleNamespace(
            **{f"joint_{i + 1}": v for i, v in enumerate(self.millideg)}
        )
        return SimpleNamespace(time_stamp=self._stamp(), joint_state=joints)

    def GetArmHighSpdInfoMsgs(self):
        motors = {
            f"motor_{i}": SimpleNamespace(motor_speed=500 * i, effort=-250 * i)
            for i in range(1, 7)
        }
        return SimpleNamespace(time_stamp=self._stamp(), **motors)

    def GetArmLowSpdInfoMsgs(self):
        motors = {
            f"motor_{i}": SimpleNamespace(
                foc_status_code=self.foc[i - 1] | (FOC_ENABLED if self.enabled else 0),
                motor_temp=30 + i,
                foc_temp=35,
            )
            for i in range(1, 7)
        }
        return SimpleNamespace(time_stamp=self._stamp(), **motors)

    def GetArmStatus(self):
        errors = SimpleNamespace(
            **{
                f"communication_status_joint_{i}": i in self.comm_error
                for i in range(1, 7)
            }
        )
        status = SimpleNamespace(
            ctrl_mode=self.ctrl_mode, arm_status=self.arm_status, err_status=errors
        )
        return SimpleNamespace(time_stamp=self._stamp(), arm_status=status)

    def SearchPiperFirmwareVersion(self):
        self.sent.append(("SearchPiperFirmwareVersion",))

    def GetPiperFirmwareVersion(self):
        return "S-V1.7-4"

    def MotionCtrl_2(self, *args):
        self.sent.append(("MotionCtrl_2", *args))

    def JointCtrl(self, *millideg):
        self.sent.append(("JointCtrl", *millideg))
        self.millideg = list(millideg)

    def EnableArm(self, motors):
        self.sent.append(("EnableArm", motors))
        self.enable_calls += 1
        self.enabled = self.enable_calls >= self.enable_after

    def DisableArm(self, motors):
        self.sent.append(("DisableArm", motors))
        self.enabled = False

    def DisconnectPort(self):
        self.sent.append(("DisconnectPort",))


def bus(sdk: FakeSdk | None = None, **kwargs) -> tuple[PiperBus, FakeSdk, Clock]:
    clock = sdk.clock if sdk else Clock()
    sdk = sdk or FakeSdk(clock)
    return (
        PiperBus("can_left", 30, sdk=sdk, clock=clock, sleep=clock.sleep, **kwargs),
        sdk,
        clock,
    )


def test_positions_are_rad_and_commands_millidegrees_after_motion_ctrl():
    piper, sdk, _ = bus()
    assert piper.firmware == "S-V1.7-4"
    sdk.millideg = [90_000, 45_000, -30_000, 0, 0, 0]
    assert piper.read_positions()[:3] == pytest.approx(
        [math.pi / 2, math.pi / 4, -math.pi / 6]
    )
    sdk.sent.clear()
    piper.write_positions([0.1, 0.2, -0.3, 0.0, 0.0, 0.0])
    assert sdk.sent[0] == ("MotionCtrl_2", 0x01, 0x01, 30, 0x00)  # CAN, MOVE J, speed
    assert sdk.sent[1] == ("JointCtrl", 5730, 11459, -17189, 0, 0, 0)
    state = piper.read_state()
    assert state.velocities == pytest.approx([0.5 * i for i in range(1, 7)])
    assert state.efforts_Nm == pytest.approx([-0.25 * i for i in range(1, 7)])
    with pytest.raises(ValueError, match="6 joint positions"):
        piper.write_positions([0.0])


def test_opening_waits_for_real_feedback_and_refuses_silence():
    clock = Clock()
    with pytest.raises(
        ConnectionError, match="no joint, motor, driver, status feedback"
    ):
        bus(FakeSdk(clock, silent=True))
    # frames from an earlier connection in this process do not count either
    sdk = FakeSdk(clock)
    sdk.stamp_lag = 5.0
    with pytest.raises(ConnectionError, match="ask an administrator"):
        bus(sdk)
    assert sdk.sent[-1] == ("DisconnectPort",)  # a failed open closes what it opened


def test_one_frame_after_opening_is_not_enough():
    # one stamp covers joints 1-2, 3-4 and 5-6: a stamp just after opening may come from
    # the first of those frames only, so feedback must keep arriving for a while
    clock = Clock()
    sdk = FakeSdk(clock)
    sdk.stops_at = clock.now + 0.01
    with pytest.raises(ConnectionError, match="no joint, motor, driver, status"):
        bus(sdk)


def test_stale_feedback_raises_so_the_follower_faults():
    piper, sdk, clock = bus()
    clock.now += 0.2  # nothing arrived for 200 ms (cable pulled)
    sdk.stamp_lag = 0.2
    with pytest.raises(ConnectionError, match="200 ms old"):
        piper.read_state()


def test_enable_repeats_until_every_joint_reports_enabled():
    piper, sdk, _ = bus(FakeSdk(Clock(), enable_after=3))
    piper.enable_torque()
    assert sdk.enable_calls == 3 and piper.enabled
    stuck, _, _ = bus(FakeSdk(Clock(), enable_after=10**9), enable_timeout_s=0.5)
    with pytest.raises(RuntimeError, match="did not enable"):
        stuck.enable_torque()


def test_health_puts_arm_and_driver_faults_into_words():
    piper, sdk, _ = bus()
    assert piper.read_health().faults == []
    sdk.ctrl_mode = 0x02  # teach button
    sdk.foc[2] = 1 << 2  # joint3 over-current
    sdk.comm_error = {5}
    health = piper.read_health()
    assert any("not CAN" in f for f in health.faults)
    assert "joint3: driver over-current" in health.faults
    assert "joint5: communication error" in health.faults
    assert health.hardware_error[2] == 1 << 2
    assert health.temperature_c[0] == 35.0
    sdk.ctrl_mode, sdk.foc[2], sdk.comm_error = 1, 0, set()
    piper.enable_torque()
    sdk.enabled = False  # a motor dropped out (collision protection, power)
    assert "joint1: motor disabled" in piper.read_health().faults


def test_disable_falls_and_close_keeps_the_motors():
    piper, sdk, _ = bus()
    piper.enable_torque()
    piper.close()
    assert sdk.sent[-1] == ("DisconnectPort",) and sdk.enabled  # not disabled
    piper.disable_torque()
    assert sdk.sent[-1] == ("DisableArm", 7)


def limits(**override) -> list[dict]:
    out = []
    for joint in JOINTS:
        low, high = RANGE[joint]
        out.append(
            {"name": joint, "min": low, "max": high, "max_speed": 1.0, "max_jump": 0.3}
        )
    for joint, (low, high) in override.items():
        next(x for x in out if x["name"] == joint).update(min=low, max=high)
    return out


def follower_cfg(**extra) -> dict:
    return {
        "type": "piper_follower",
        "can": "can_left",
        "control_hz": 100,
        "speed_percent": 30,
        "limits": limits(),
        "health": {"every_ticks": 10},
        **extra,
    }


def test_follower_checks_its_configuration():
    follower = PiperFollower("left", follower_cfg())
    assert follower.unit == "rad" and follower.device_ids() == ("can_left",)
    assert follower.traits().torque_off == "falls"
    assert follower.traits().unattended == "unknown"
    assert PiperFollower(
        "left", follower_cfg(unattended="holds")
    ).traits().unattended == ("holds")
    for bad, match in (
        ({"limits": limits(joint2=(-0.1, 1.0))}, "exceeds the PiPER range"),
        ({"speed_percent": 0}, "speed_percent"),
        ({"speed_percent": 50.0}, "speed_percent"),
        ({"can": "SET_CAN_LEFT"}, "explicit device identity"),
        ({"health": None}, "health: required"),
        ({"control": []}, "own position control"),
    ):
        with pytest.raises(ValueError, match=match):
            PiperFollower("left", {**follower_cfg(), **bad})


def test_health_faults_latch_the_follower():
    piper, sdk, _ = bus()
    follower = PiperFollower("left", follower_cfg())
    safety = FollowerSafety(follower.safety_config(), piper)
    safety.start()
    for _ in range(10):
        state, _ = safety.tick()
    assert safety.mode == "HOLD"
    assert state.payload["efforts_Nm"] == pytest.approx(
        [-0.25 * i for i in range(1, 7)]
    )
    sdk.arm_status = 0x07  # collision
    for _ in range(10):
        safety.tick()
    assert safety.mode == "FAULT" and "arm status" in safety.reason


def test_mock_follower_opens_at_rest():
    follower = PiperFollower("left", follower_cfg())
    mock = follower.open_device(mock=True)
    assert mock.read_positions() == [0.0] * 6


def piper_project(root) -> object:
    """Two mock PiPER followers and a camera, driven by one policy (no leaders yet)."""
    import shutil

    import yaml

    from roboloom.robots.piper.spec import RANGE

    target = root / "piper"
    (target / "nodes").mkdir(parents=True)
    shutil.copy("examples/mock/nodes/camera.yaml", target / "nodes" / "camera.yaml")
    shutil.copy("examples/mock/nodes/session.yaml", target / "nodes" / "session.yaml")
    arm = follower_cfg(record_effort=True)
    # the mock rests at 0 rad, the edge of joint2's range: creep moves joint1 only
    assert RANGE["joint1"][0] < 0 < RANGE["joint1"][1]
    for side in ("left", "right"):
        cfg = {**arm, "can": f"can_{side}"}
        (target / "nodes" / f"{side}.yaml").write_text(yaml.safe_dump(cfg))
    policy = {
        "type": "policy",
        "followers": ["left", "right"],
        "factory": "policies:creep",
        "observe": ["camera"],
        "rate_hz": 10,
        "action_horizon": 2,
        "max_speed": {"left": 0.5, "right": 0.5},
        "command_deadline_ms": 300,
    }
    (target / "nodes" / "policy.yaml").write_text(yaml.safe_dump(policy))
    recorder = {"max_age_ms": {"left": 300, "right": 300, "camera": 300}}
    (target / "nodes" / "recorder.yaml").write_text(yaml.safe_dump(recorder))
    config = {
        "repo_id": "local/piper-mock",
        "output": "datasets/piper",
        "mode": "mock",
        "dataset_fps": 10,
        "controllers": {"policy": "nodes/policy.yaml"},
        "followers": {"left": "nodes/left.yaml", "right": "nodes/right.yaml"},
        "sensors": {"camera": "nodes/camera.yaml"},
        "recorder": "nodes/recorder.yaml",
        "session": "nodes/session.yaml",
    }
    path = target / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    return path


def test_a_policy_drives_two_mock_pipers_and_records_rad(tmp_path, monkeypatch):
    import json
    import os
    from pathlib import Path

    from roboloom.runtime.session import Session

    tests = str(Path(__file__).parent.resolve())
    monkeypatch.setenv(
        "PYTHONPATH", os.pathsep.join([tests, os.environ.get("PYTHONPATH", "")])
    )
    path = piper_project(tmp_path)
    with Session.launch(
        path, policy_kwargs={"step": 0.01}, log_dir=tmp_path / "logs"
    ) as s:
        # nothing is known about the PiPER left alone: quit offers no "hold"
        assert s.held == [] and set(s.limp_at_end) == {"left", "right"}
        s.wait_ready(30)
        result = s.record("creep", 1.5)
        left = s.status()["left"]["fields"]
    assert left["unattended"] == "unknown" and left["torque_off"] == "falls"
    assert result.saved, result
    assert result.metrics["action_valid_rate"] > 0.5, result.metrics
    info = json.loads((path.parent / "datasets/piper/meta/info.json").read_text())
    action = info["features"]["action"]
    assert action["shape"] == [12] and action["names"][6] == "right.joint1"
    assert info["features"]["observation.effort"]["names"][0] == "left.joint1"
    assert info["robot_type"] == "piper"


# -- check-hold -----------------------------------------------------------------


class LeftAlone:
    """A 6-joint bus whose joint1 sags by `sag` per read once writes stopped (two reads in
    a row; sag 0: it holds), and whose motors may drop out then (`drops`)."""

    def __init__(self, sag: float = 0.0, drops: bool = False):
        from roboloom.drivers.mock import MockBus

        self.mock = MockBus(initial=0.0, dimension=6)
        self.mock.values[0] = 0.5
        self.sag, self.drops = sag, drops
        self.unwritten = 0  # reads since the last write
        self.closed = False

    def __getattr__(self, name):
        return getattr(self.mock, name)

    def write_positions(self, values):
        self.unwritten = 0
        self.mock.write_positions(values)

    def read_positions(self):
        self.unwritten += 1
        if self.unwritten > 1 and self.mock.enabled:
            self.mock.values[0] -= self.sag
        return self.mock.read_positions()

    def read_state(self):
        from roboloom.drivers.base import JointState

        return JointState(self.read_positions())

    def enable_status(self):
        return [self.mock.enabled and not (self.unwritten > 1 and self.drops)] * 6

    def close(self):
        self.closed = True  # the motors keep their torque, as PiPER's close does


def test_hold_trial_tells_holding_from_sagging():
    from roboloom.setup.hold import hold_trial

    follower = PiperFollower("left", follower_cfg())
    clock = Clock()
    for bus, holds in ((LeftAlone(), True), (LeftAlone(sag=0.01), False)):
        result = hold_trial(follower, bus, 2.0, 0.02, sleep=clock.sleep, clock=clock)
        assert result.holds is holds, result.lines()
        assert result.unattended == ("holds" if holds else "torque_off")
        assert bus.mock.enabled and not bus.closed  # left as it was: the caller decides
    result = hold_trial(
        follower, LeftAlone(drops=True), 1.0, 0.02, sleep=clock.sleep, clock=clock
    )
    assert not result.holds and "motors [1, 2, 3, 4, 5, 6] became disabled" in (
        "\n".join(result.lines())
    )


def test_check_hold_records_the_measurement_in_the_follower_yaml(tmp_path, monkeypatch):
    import yaml

    from roboloom.config import load_config
    from roboloom.errors import ConfigError
    from roboloom.operator import ScriptedOperator
    from roboloom.setup import check_hold

    path = piper_project(tmp_path)
    config = yaml.safe_load(path.read_text())
    config["mode"] = "hardware"
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    bus = LeftAlone()
    monkeypatch.setattr(PiperFollower, "open_device", lambda self, mock: bus)
    monkeypatch.setattr("roboloom.setup.hold.time.sleep", lambda s: None)
    operator = ScriptedOperator(prompts=["record", "release"])
    result = check_hold(path, "left", operator, tolerance=0.01, seconds=0.05)
    assert result.holds
    assert not bus.mock.enabled and bus.closed  # 'release' turned the torque off
    text = (path.parent / "nodes" / "left.yaml").read_text()
    assert "unattended: holds  # roboloom check-hold" in text
    cfg = load_config(path)
    assert cfg.followers["left"].traits().unattended == "holds"
    assert cfg.followers["right"].traits().unattended == "unknown"
    with pytest.raises(ConfigError, match="mock mode"):
        check_hold(load_config(path, mock=True), "right", operator, tolerance=0.01)


def test_check_hold_refuses_a_model_that_declares_it(tmp_path):
    from conftest import mock_project

    from roboloom.config import load_config
    from roboloom.errors import ConfigError
    from roboloom.operator import ScriptedOperator
    from roboloom.setup import check_hold

    project = mock_project(tmp_path / ".roboloom")
    cfg = load_config(project / "config.yaml", mock=False)
    with pytest.raises(ConfigError, match="declares unattended: holds"):
        check_hold(cfg, "follower", ScriptedOperator(), tolerance=10)


def test_probe_reads_a_network_interface_as_a_piper():
    from roboloom.probe import is_network_interface

    assert is_network_interface("lo")
    assert not is_network_interface("/dev/ttyUSB0")
    assert not is_network_interface("can_does_not_exist")
