import time

from roboloom.config import load_experiment
from roboloom.control import FollowerSafety, JointController
from roboloom.devices import MockBus
from roboloom.protocol import Envelope


def command(seq, target, now, deadline=None):
    return Envelope("command", "controller", "boot", seq, now, now, {"robot_id": "r", "unit": "dynamixel_count", "positions": target, "deadline_ns": deadline or now + 100_000_000})


def safety():
    bus = MockBus(dimension=1)
    ctl = FollowerSafety({"robot_id": "r", "limits": [{"min": 0, "max": 4095, "max_step": 100}]}, bus)
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
    assert not action.payload["valid"] and ctl.mode == "FAULT"


def test_stop_and_estop_latch():
    ctl, bus = safety()
    now = time.monotonic_ns()
    ctl.stop()
    ctl.accept(command(0, [2070], now))
    _, action = ctl.tick(now)
    assert not action.payload["valid"] and bus.values == [2048]
    ctl.arm()
    ctl.accept(command(1, [2070], now))
    _, action = ctl.tick(now)
    assert action.payload["valid"]
    ctl.stop(estop=True)
    ctl.arm()
    ctl.accept(command(2, [2080], now))
    _, action = ctl.tick(now)
    assert ctl.mode == "ESTOP" and not action.payload["valid"]


def test_deadline_limit_and_write_failure():
    ctl, bus = safety()
    now = time.monotonic_ns()
    ctl.accept(command(0, [2070], now, now + 1))
    _, action = ctl.tick(now + 2)
    assert not action.payload["valid"] and ctl.mode == "HOLD"
    ctl.accept(command(1, [3000], now + 2))
    _, action = ctl.tick(now + 2)
    assert not action.payload["valid"] and ctl.mode == "HOLD"

    def fail(values: list[float]) -> None:
        raise OSError("serial write failed")

    bus.write_positions = fail
    ctl.accept(command(2, [2070], now + 2))
    _, action = ctl.tick(now + 2)
    assert not action.payload["valid"] and ctl.mode == "FAULT"


def test_controller_alignment_and_input_age():
    cfg = load_experiment("examples/mock/experiment.yaml")["nodes"]["controller"]
    cfg = {**cfg, "robot_id": "r"}
    ctl = JointController(cfg)
    now = time.monotonic_ns()
    bad = Envelope("leader", "leader", "boot", 0, now, now, {"positions": [3000] * 17})
    assert ctl.update(bad, [2048] * 17, now) is None
    aligned = Envelope("leader", "leader", "boot", 1, now, now, {"positions": [2048] * 17})
    assert ctl.update(aligned, [2048] * 17, now) is not None
    assert ctl.update(aligned, [2048] * 17, now) is None
    old = Envelope("leader", "leader", "boot", 2, now - 1_000_000_000, now - 1_000_000_000, {"positions": [2048] * 17})
    assert ctl.update(old, [2048] * 17, now) is None
