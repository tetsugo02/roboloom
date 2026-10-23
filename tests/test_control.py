import time

import numpy as np
import pytest

from roboloom.config import load_experiment
from roboloom.core.protocol import Envelope
from roboloom.drivers.base import Health
from roboloom.drivers.mock import MockBus
from roboloom.robots.safety import FollowerSafety

LIMIT = {"min": 0, "max": 4095, "max_speed": 3000, "max_jump": 400}


def command(seq, target, now, deadline=None):
    return Envelope("command", "controller", "boot", seq, now, now, {"robot_id": "r", "unit": "dynamixel_count", "positions": target, "deadline_ns": deadline or now + 100_000_000})


def safety(**cfg):
    bus = MockBus(dimension=1)
    ctl = FollowerSafety({"robot_id": "r", "limits": [LIMIT], "control_hz": 30, **cfg}, bus)
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

    ctl, bus = safety(health={"every_ticks": 1, "max_temperature_c": 70})
    bus.health = Health([0], [75.0])
    state, _ = ctl.tick(now)
    assert ctl.mode == "FAULT" and "temperature" in state.payload["reason"]
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
    ctl = load_experiment("examples/mock/experiment.yaml").controllers["controller"]
    now = time.monotonic_ns()
    bad = Envelope("joint_intent", "leader", "boot", 0, now, now, {"positions": [3000] * 17})
    assert ctl.update(bad, [2048] * 17, now) is None
    aligned = Envelope("joint_intent", "leader", "boot", 1, now, now, {"positions": [2048] * 17})
    assert ctl.update(aligned, [2048] * 17, now) is not None
    assert ctl.update(aligned, [2048] * 17, now) is None
    old = Envelope("joint_intent", "leader", "boot", 2, now - 1_000_000_000, now - 1_000_000_000, {"positions": [2048] * 17})
    assert ctl.update(old, [2048] * 17, now) is None


def test_envelope_binary_round_trip():
    image = np.arange(48 * 64 * 3, dtype=np.uint8).reshape(48, 64, 3)
    msg = Envelope("image", "camera", "boot", 3, 1, 2, {"image": image, "note": "x", "pcm": np.ones(4, np.int16)})
    back = Envelope.decode(msg.encode())
    assert back.payload["note"] == "x" and back.seq == 3
    assert np.array_equal(back.payload["image"], image) and back.payload["pcm"].dtype == np.int16
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
    assert action.payload["valid"] and action.payload["clamped"] and bus.values == [4095]
    ctl.accept(command(1, [3000], now + 33_000_000))
    state, action = ctl.tick(now + 66_000_000)
    assert not action.payload["valid"] and state.payload["rejected"]
    assert "jumps" in ctl.last_reject and "max_jump 400" in ctl.last_reject
    ctl.accept(command(2, [4095], now, deadline=now + 1))
    ctl.tick(now + 99_000_000)
    assert "stale" in ctl.last_reject


def test_controller_steps_from_the_follower_target_not_its_own_output():
    ctl = load_experiment("examples/mock/experiment.yaml").controllers["controller"]
    now = time.monotonic_ns() - 5_000_000_000  # message times must not lie in the future
    hold = [2048.0] * 17
    intent = lambda seq, value, t: Envelope("joint_intent", "leader", "boot", seq, t, t, {"positions": [value] * 17})
    assert ctl.update(intent(0, 2048, now), hold, now, follower_target=hold) is not None
    # robot not armed yet: it keeps holding 2048 while the leader moves far away over 2 s
    for k in range(1, 61):
        t = now + k * 33_000_000
        cmd = ctl.update(intent(k, 2048 + 20 * k, t), hold, t, follower_target=hold)
    step = 500 * 0.033  # max_speed_counts_per_s in the mock controller
    assert max(abs(x - 2048) for x in cmd.payload["positions"]) <= step + 1e-6
