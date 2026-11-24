import math
import time

import numpy as np
import pytest

from roboloom.config import load_config
from roboloom.controllers.joint import JointController
from roboloom.core.protocol import Envelope, Publisher
from roboloom.drivers.base import Health
from roboloom.drivers.mock import MockBus
from roboloom.inputs.base import JointInput
from roboloom.robots.base import Follower
from roboloom.robots.safety import FollowerSafety

LIMIT = {"min": 0, "max": 4095, "max_speed": 3000, "max_jump": 400}


def command(seq, target, now, deadline=None):
    return Envelope(
        "command",
        "controller",
        "boot",
        seq,
        now,
        now,
        {
            "follower": "r",
            "unit": "dynamixel_count",
            "positions": target,
            "deadline_ns": deadline or now + 100_000_000,
        },
    )


def safety(**cfg):
    bus = MockBus(dimension=1)
    ctl = FollowerSafety(
        {
            "name": "r",
            "unit": "dynamixel_count",
            "limits": [LIMIT],
            "control_hz": 30,
            **cfg,
        },
        bus,
    )
    ctl.start()
    ctl.arm()
    return ctl, bus


def test_safety_rejects_stale_bad_and_out_of_range_commands():
    ctl, bus = safety()
    now = time.monotonic_ns()
    ctl.accept(command(0, [2070], now))
    _, action = ctl.tick(now)
    assert action.payload["valid"] and bus.values == [2070]
    ctl.accept(command(0, [2080], now))  # duplicate
    _, action = ctl.tick(now + 1)
    assert not action.payload["valid"]
    ctl.accept(command(1, [float("nan")], now))
    _, action = ctl.tick(now + 2)
    assert not action.payload["valid"] and ctl.mode == "HOLD"
    ctl.accept(command(2, [5000], now))
    _, action = ctl.tick(now + 3)
    assert not action.payload["valid"] and bus.values == [2070]


def test_soft_clamp_and_hard_jump():
    ctl, bus = safety()
    now = time.monotonic_ns() - 1_000_000_000  # tick times must not be in the future
    ctl.tick(now)
    ctl.accept(command(0, [2300], now))  # 252 > 3000 counts/s * 33 ms, < max_jump
    _, action = ctl.tick(now + 33_000_000)
    assert action.payload["valid"] and action.payload["clamped"]
    assert bus.values[0] == pytest.approx(2048 + 3000 * 0.033)
    ctl.accept(command(1, [2048 + 3000 * 0.033 + 401], now + 33_000_000))
    _, action = ctl.tick(now + 66_000_000)
    assert not action.payload["valid"] and ctl.mode == "HOLD"


def test_hold_target_is_latched_not_remeasured():
    ctl, bus = safety()
    now = time.monotonic_ns()
    ctl.accept(command(0, [2060], now))
    ctl.tick(now)
    bus.values = [2050.0]  # gravity sag measured by the bus
    ctl.tick(now + 1)
    assert ctl.mode == "HOLD" and bus.values == [2060]
    ctl.stop()
    bus.values = [2040.0]
    ctl.tick(now + 2)
    assert bus.values == [2060]


def test_stop_estop_and_release_latch():
    ctl, bus = safety()
    now = time.monotonic_ns()
    ctl.stop()
    ctl.accept(command(0, [2070], now))
    _, action = ctl.tick(now)
    assert not action.payload["valid"] and bus.values == [2048]
    ctl.arm()
    with pytest.raises(RuntimeError):
        ctl.release()  # armed
    ctl.accept(command(1, [2070], now))
    _, action = ctl.tick(now)
    assert action.payload["valid"]
    ctl.stop(estop=True)
    ctl.arm()
    ctl.accept(command(2, [2080], now))
    _, action = ctl.tick(now)
    assert ctl.mode == "ESTOP" and not action.payload["valid"]
    ctl.release()
    assert ctl.mode == "RELEASED" and not bus.enabled


def test_write_failure_and_health_latch_fault():
    ctl, bus = safety()
    now = time.monotonic_ns()

    def fail(values: list[float]) -> None:
        raise OSError("serial write failed")

    bus.write_positions = fail
    ctl.accept(command(0, [2070], now))
    _, action = ctl.tick(now)
    assert not action.payload["valid"] and ctl.mode == "FAULT"

    # one health register per health tick (watchdog, hardware error, temperature in turn)
    ctl, bus = safety(health={"every_ticks": 1, "max_temperature_c": 70})
    bus.health = Health([0], [75.0])
    modes = []
    for _ in range(3):
        state, _ = ctl.tick(now)
        modes.append(ctl.mode)
    assert modes == ["HOLD", "HOLD", "FAULT"]
    assert "temperature" in state.payload["reason"]
    ctl, bus = safety(health={"every_ticks": 1})
    bus.health = Health([1], [30.0])
    ctl.tick(now)
    ctl.tick(now)
    assert ctl.mode == "FAULT" and "hardware error" in ctl.reason
    ctl, bus = safety(health={"every_ticks": 1})
    bus.health = Health([0], [30.0], watchdog_fired=True)
    ctl.tick(now)
    assert ctl.mode == "FAULT"


def test_torque_false_records_state_only():
    ctl, bus = safety(torque=False)
    ctl.accept(command(0, [2070], time.monotonic_ns()))
    state, action = ctl.tick()
    assert not bus.enabled and ctl.mode == "RELEASED" and not action.payload["valid"]
    assert state.payload["positions"] == [2048]


def test_controller_alignment_and_input_age():
    ctl = load_config("examples/mock/config.yaml").controllers["controller"]
    assert isinstance(ctl, JointController)
    now = time.monotonic_ns()
    bad = Envelope(
        "joint_intent", "leader", "boot", 0, now, now, {"positions": [3000] * 17}
    )
    assert ctl.step(bad, [2048] * 17, now) is None
    aligned = Envelope(
        "joint_intent", "leader", "boot", 1, now, now, {"positions": [2048] * 17}
    )
    assert ctl.step(aligned, [2048] * 17, now) is not None
    assert ctl.step(aligned, [2048] * 17, now) is None
    old = Envelope(
        "joint_intent",
        "leader",
        "boot",
        2,
        now - 1_000_000_000,
        now - 1_000_000_000,
        {"positions": [2048] * 17},
    )
    assert ctl.step(old, [2048] * 17, now) is None


def test_envelope_binary_round_trip():
    image = np.arange(48 * 64 * 3, dtype=np.uint8).reshape(48, 64, 3)
    msg = Envelope(
        "image",
        "camera",
        "boot",
        3,
        1,
        2,
        {"image": image, "note": "x", "pcm": np.ones(4, np.int16)},
    )
    back = Envelope.decode(msg.encode())
    assert back.payload["note"] == "x" and back.seq == 3
    assert (
        np.array_equal(back.payload["image"], image)
        and back.payload["pcm"].dtype == np.int16
    )
    import pyarrow as pa

    arrow = Envelope.decode(pa.array(np.frombuffer(msg.encode(), np.uint8)))
    assert np.array_equal(arrow.payload["image"], image)


def test_out_of_range_is_clipped_and_rejects_say_why():
    ctl, bus = safety()
    now = time.monotonic_ns() - 1_000_000_000
    ctl.tick(now)
    bus.values = [4090.0]
    ctl.hold_target = ctl.last_sent = [4090.0]
    ctl.accept(command(0, [4200], now))  # beyond max=4095 but within max_jump
    _, action = ctl.tick(now + 33_000_000)
    assert (
        action.payload["valid"] and action.payload["clamped"] and bus.values == [4095]
    )
    ctl.accept(command(1, [3000], now + 33_000_000))
    state, action = ctl.tick(now + 66_000_000)
    assert not action.payload["valid"] and state.payload["rejected"]
    assert "jumps" in ctl.last_reject and "max_jump 400" in ctl.last_reject
    ctl.accept(command(2, [4095], now, deadline=now + 1))
    ctl.tick(now + 99_000_000)
    assert "stale" in ctl.last_reject


def test_controller_steps_from_the_follower_target_not_its_own_output():
    ctl = load_config("examples/mock/config.yaml").controllers["controller"]
    assert isinstance(ctl, JointController)
    now = (
        time.monotonic_ns() - 5_000_000_000
    )  # message times must not lie in the future
    hold = [2048.0] * 17
    intent = lambda seq, value, t: Envelope(
        "joint_intent", "leader", "boot", seq, t, t, {"positions": [value] * 17}
    )
    assert ctl.step(intent(0, 2048, now), hold, now, follower_target=hold) is not None
    # robot not armed yet: it keeps holding 2048 while the leader moves far away over 2 s
    cmd = None
    for k in range(1, 61):
        t = now + k * 33_000_000
        cmd = ctl.step(intent(k, 2048 + 20 * k, t), hold, t, follower_target=hold)
    assert cmd is not None
    step = 500 * 0.033  # max_speed of the mock controller (counts/s)
    assert max(abs(x - 2048) for x in cmd.payload["positions"]) <= step + 1e-6


def test_numpy_scalars_in_a_payload_encode_as_json_numbers():
    msg = Publisher("x").make(
        "status", {"fields": {"missing": {"leader": np.int64(3)}}}
    )
    assert Envelope.decode(msg.encode()).payload["fields"]["missing"]["leader"] == 3


def test_a_state_that_could_not_be_read_keeps_the_time_it_was_read():
    limits = [
        {"name": j, "min": 0, "max": 4095, "max_speed": 5000, "max_jump": 500}
        for j in ("a", "b")
    ]
    bus = MockBus(dimension=2)
    ctl = FollowerSafety(
        {"name": "arm", "limits": limits, "unit": "count", "control_hz": 100}, bus
    )
    ctl.start()
    t1 = time.monotonic_ns() - 100_000_000
    state, _ = ctl.tick(t1)
    assert state.t_capture_ns == t1 and state.payload["mode"] == "HOLD"
    bus.fail = True  # the cable came off
    t2 = t1 + 50_000_000
    state, action = ctl.tick(t2)
    assert state.payload["mode"] == "FAULT" and not action.payload["valid"]
    assert state.payload["positions"] == [2048.0, 2048.0]  # the last ones read ...
    assert state.t_capture_ns == t1  # ... and they say when: not now
    assert state.t_ready_ns >= t2


# -- a leader with another gear ratio or unit -----------------------------------------


def _arm(unit: str = "rad") -> Follower:
    limits = [
        {"name": j, "min": -4, "max": 4, "max_speed": 10, "max_jump": 4}
        for j in ("a", "b")
    ]
    return Follower(
        "arm", {"joints": ["a", "b"], "unit": unit, "control_hz": 50, "limits": limits}
    )


class Knob(JointInput):
    safety_traits = Follower.safety_traits


SCALED_CONTROLLER = {
    "alignment_tolerance": 0.1,
    "max_speed": 10.0,
    "command_deadline_ms": 100,
    "input_timeout_ms": 150,
}
PER_COUNT = 2 * math.pi / 4096


def _scaled(**change) -> JointController:
    # a leader in counts (0..4095, 2048 at the follower's zero) for an arm in rad
    table = [
        {
            "leader": "a",
            "follower": "a",
            "sign": 1,
            "offset": -math.pi,
            "scale": PER_COUNT,
        },
        {
            "leader": "b",
            "follower": "b",
            "sign": -1,
            "offset": math.pi,
            "scale": PER_COUNT,
        },
    ]
    cfg = {**SCALED_CONTROLLER, "joints": table, **change}
    leader = Knob("knob", {"joints": ["a", "b"], "unit": "dynamixel_count"})
    return JointController("c", cfg, leader, {"arm": _arm()})


def test_a_scale_maps_a_leader_of_another_unit_onto_the_follower():
    controller = _scaled()
    pose = controller.follower_pose([2048 + 1024, 2048 + 1024])
    assert pose == pytest.approx([math.pi / 2, -math.pi / 2])
    back = controller.leader_pose(pose)
    assert back == pytest.approx({"a": 3072.0, "b": 3072.0})
    # it follows: aligned at zero, then the leader turns 1/8 of a turn
    t0 = time.monotonic_ns() - 1_000_000_000
    first = Envelope(
        "joint_intent", "knob", "boot", 0, t0, t0, {"positions": [2048, 2048]}
    )
    controller.step(first, [0, 0], t0 + 1)
    second = Envelope(
        "joint_intent",
        "knob",
        "boot",
        1,
        t0 + 10_000_000,
        t0 + 10_000_000,
        {"positions": [2560, 2560]},
    )
    cmd = controller.step(
        second, [0.0, 0.0], t0 + 20_000_001, follower_target=[0.0, 0.0]
    )
    assert cmd is not None and controller.state == "following"
    # limited to max_speed * dt = 0.2 rad of the 0.785 rad asked, in each direction
    assert cmd.payload["positions"] == pytest.approx([0.2, -0.2])


def test_units_that_differ_need_a_scale_on_every_joint():
    leader = Knob("knob", {"joints": ["a", "b"], "unit": "dynamixel_count"})
    with pytest.raises(ValueError, match="or give every joint a scale"):
        JointController("c", dict(SCALED_CONTROLLER), leader, {"arm": _arm()})
    table = [
        {"leader": "a", "follower": "a", "sign": 1, "offset": 0, "scale": PER_COUNT},
        {"leader": "b", "follower": "b", "sign": 1, "offset": 0},  # no scale here
    ]
    with pytest.raises(ValueError, match="or give every joint a scale"):
        JointController(
            "c", {**SCALED_CONTROLLER, "joints": table}, leader, {"arm": _arm()}
        )
    # the same unit: a scale is a gear ratio, and no scale is 1
    same = Knob("knob", {"joints": ["a", "b"], "unit": "rad"})
    table[0]["scale"] = 2.0
    geared = JointController(
        "c", {**SCALED_CONTROLLER, "joints": table}, same, {"arm": _arm()}
    )
    assert geared.follower_pose([0.5, 0.5]) == pytest.approx([1.0, 0.5])


@pytest.mark.parametrize("scale", [0, -1.0, float("nan"), "2", True])
def test_a_scale_is_a_positive_number(scale):
    table = [
        {"leader": j, "follower": j, "sign": 1, "offset": 0, "scale": scale}
        for j in ("a", "b")
    ]
    same = Knob("knob", {"joints": ["a", "b"], "unit": "rad"})
    with pytest.raises(ValueError, match="scale must be a positive number"):
        JointController(
            "c", {**SCALED_CONTROLLER, "joints": table}, same, {"arm": _arm()}
        )


def test_force_feedback_is_refused_with_scaled_joints():
    with pytest.raises(ValueError, match="feedback: not with scaled joints"):
        _scaled(feedback={"estimator": "effort"})
