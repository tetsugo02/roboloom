"""One process per serial bus, a lost packet that does not stop the robot, readings that
do not pass for fresh ones, a policy server whose answers cannot be mixed up, and a
leader with another gear ratio or unit."""

from __future__ import annotations

import math
import os
import threading
import time

import numpy as np
import pytest
from test_policy_remote import KEY, _free_address

from roboloom.controllers.joint import JointController
from roboloom.core.protocol import Publisher
from roboloom.drivers.base import claim_serial
from roboloom.drivers.mock import MockBus
from roboloom.inputs.base import JointInput
from roboloom.policy import remote as R
from roboloom.robots.base import Follower
from roboloom.robots.safety import FollowerSafety

# -- one process per bus --------------------------------------------------------------


def test_a_serial_port_is_taken_by_the_first_process_only():
    _, slave = os.openpty()
    name = os.ttyname(slave)
    first = os.open(name, os.O_RDWR | os.O_NOCTTY)
    try:
        claim_serial(first, name)
        # the second opener is stopped: at open (TIOCEXCL) or at its own claim (the lock)
        with pytest.raises(OSError):
            second = os.open(name, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            try:
                claim_serial(second, name)
            finally:
                os.close(second)
    finally:
        os.close(first)


def test_the_lock_names_the_port_and_what_may_hold_it(tmp_path):
    path = tmp_path / "ttyFAKE"  # a file takes the lock; it has no TIOCEXCL
    path.write_bytes(b"")
    first, second = os.open(path, os.O_RDWR), os.open(path, os.O_RDWR)
    try:
        claim_serial(first, str(path))
        with pytest.raises(ConnectionError, match="ttyFAKE is in use by another"):
            claim_serial(second, str(path))
    finally:
        os.close(first)
        os.close(second)
    third = os.open(path, os.O_RDWR)  # released when its holder closed it
    try:
        claim_serial(third, str(path))
    finally:
        os.close(third)


# -- a read that fails once -------------------------------------------------------------


class Replies:
    """A Dynamixel sync-read group answering with `results` in turn, then success."""

    def __init__(self, results: list, missing: list[int] | None = None):
        import dynamixel_sdk as dxl

        self.ok = dxl.COMM_SUCCESS
        self.results, self.missing, self.calls = list(results), missing or [], 0

    def txRxPacket(self):
        self.calls += 1
        return self.results.pop(0) if self.results else self.ok

    def isAvailable(self, motor, address, size):
        if self.missing and self.missing[0] == motor:
            self.missing.pop(0)  # missing from this reply only
            return False
        return True

    def getData(self, motor, address, size):
        return 2000 + motor


def _bus(group: Replies, retries: int = 1):
    import dynamixel_sdk as dxl

    from roboloom.drivers.dynamixel import DynamixelBus

    class Port:
        class ser:
            dropped = 0

            @classmethod
            def reset_input_buffer(cls):
                cls.dropped += 1

    bus = DynamixelBus.__new__(DynamixelBus)
    bus.ids, bus.fast_read, bus.port = [1, 2], False, Port()
    bus.read_retries, bus.retries = retries, 0
    bus._readers = {(132, 4): group}
    return bus, dxl.COMM_RX_TIMEOUT


def test_a_read_that_fails_once_is_repeated_and_counted():
    bus, timeout = _bus(Replies([]))
    assert bus._read(132, 4) == [[2001], [2002]] and bus.retries == 0
    group = Replies([timeout])
    bus, _ = _bus(group)
    assert bus._read(132, 4) == [[2001], [2002]]
    assert bus.retries == 1 and group.calls == 2
    assert bus.port.ser.dropped == 1  # the rest of the failed reply was dropped first
    bus, _ = _bus(Replies([], missing=[2]))  # a reply without motor 2, then a whole one
    assert bus._read(132, 4) == [[2001], [2002]] and bus.retries == 1


def test_a_read_that_keeps_failing_still_raises():
    _, timeout = _bus(Replies([]))
    group = Replies([timeout, timeout])
    bus, _ = _bus(group)
    with pytest.raises(ConnectionError, match="sync read failed"):
        bus._read(132, 4)
    assert group.calls == 2 and bus.retries == 1
    bus, _ = _bus(Replies([timeout]), retries=0)  # no retries configured
    with pytest.raises(ConnectionError):
        bus._read(132, 4)


# -- a state that could not be read ------------------------------------------------------


def test_a_state_that_could_not_be_read_keeps_the_time_it_was_read():
    limits = [
        {"name": j, "min": 0, "max": 4095, "max_speed": 5000, "max_jump": 500}
        for j in ("a", "b")
    ]
    bus = MockBus(dimension=2)
    safety = FollowerSafety(
        {"name": "arm", "limits": limits, "unit": "count", "control_hz": 100}, bus
    )
    safety.start()
    t1 = time.monotonic_ns() - 100_000_000
    state, _ = safety.tick(t1)
    assert state.t_capture_ns == t1 and state.payload["mode"] == "HOLD"
    bus.fail = True  # the cable came off
    t2 = t1 + 50_000_000
    state, action = safety.tick(t2)
    assert state.payload["mode"] == "FAULT" and not action.payload["valid"]
    assert state.payload["positions"] == [2048.0, 2048.0]  # the last ones read ...
    assert state.t_capture_ns == t1  # ... and they say when: not now
    assert state.t_ready_ns >= t2


# -- the policy server -------------------------------------------------------------------


class Slow:
    """Its n-th inference answers n; the first takes long."""

    def __init__(self) -> None:
        self.calls = 0

    def reset(self) -> None:
        pass

    def infer(self, observation: dict) -> np.ndarray:
        self.calls += 1
        number = self.calls
        if number == 1:
            time.sleep(1.0)
        return np.asarray([[float(number)]])


def _serve(monkeypatch, policy, clients: int) -> str:
    monkeypatch.setenv(R.AUTHKEY_ENV, KEY)
    address, up = _free_address(), threading.Event()
    threading.Thread(
        target=R.serve,
        args=(policy, address),
        kwargs={"authkey": KEY, "clients": clients, "ready": up.set},
        daemon=True,
    ).start()
    assert up.wait(5)
    return address


def test_an_answer_that_comes_after_its_call_timed_out_is_not_the_next_ones(
    monkeypatch,
):
    address = _serve(monkeypatch, Slow(), 1)
    client = R.RemotePolicy(address, timeout_s=0.3)
    try:
        with pytest.raises(TimeoutError, match="no answer to infer within 0.3 s"):
            client.infer({})
        client.timeout_s = 10.0
        # the late answer (1) is on the connection before this call's (2)
        assert client.infer({}).tolist() == [[2.0]]
        assert client.infer({}).tolist() == [[3.0]]
    finally:
        client.close()


def test_a_second_policy_node_is_told_the_server_is_busy(monkeypatch):
    address = _serve(monkeypatch, Slow(), 3)
    first = R.RemotePolicy(address, timeout_s=10)
    try:
        first.reset()
        second = R.RemotePolicy(address, timeout_s=5)  # it used to wait here for ever
        try:
            with pytest.raises(
                R.RemotePolicyError, match="serving another policy node"
            ):
                second.reset()
        finally:
            second.close()
        first.reset()  # the first one is still served
    finally:
        first.close()
    third = R.RemotePolicy(address, timeout_s=5)  # and once it left, the next one is
    try:
        third.reset()
    finally:
        third.close()


def test_a_client_from_before_calls_had_numbers_is_still_answered(monkeypatch):
    from multiprocessing.connection import Client

    address = _serve(monkeypatch, Slow(), 1)
    host, _, port = address.rpartition(":")
    with Client((host, int(port)), authkey=KEY.encode()) as connection:
        connection.send_bytes(R.encode(["reset"]))  # the old form: no number
        assert R.decode(connection.recv_bytes()) == ["ok", None]


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


CONTROLLER = {
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
    cfg = {**CONTROLLER, "joints": table, **change}
    leader = Knob("knob", {"joints": ["a", "b"], "unit": "dynamixel_count"})
    return JointController("c", cfg, leader, {"arm": _arm()})


def test_a_scale_maps_a_leader_of_another_unit_onto_the_follower():
    controller = _scaled()
    pose = controller.follower_pose([2048 + 1024, 2048 + 1024])
    assert pose == pytest.approx([math.pi / 2, -math.pi / 2])
    back = controller.leader_pose(pose)
    assert back == pytest.approx({"a": 3072.0, "b": 3072.0})
    # it follows: aligned at zero, then the leader turns 1/8 of a turn
    publisher = Publisher("knob")
    first = publisher.make("joint_intent", {"positions": [2048, 2048]})
    now = first.t_ready_ns + 1
    controller.step(first, [0, 0], now)
    second = publisher.make("joint_intent", {"positions": [2560, 2560]})
    time.sleep(0.03)  # a command is stamped with `now`, which must not lie ahead
    command = controller.step(
        second, [0.0, 0.0], now + 20_000_000, follower_target=[0.0, 0.0]
    )
    assert command is not None and controller.state == "following"
    # limited to max_speed * dt = 0.2 rad of the 0.785 rad asked, in each direction
    assert command.payload["positions"] == pytest.approx([0.2, -0.2])


def test_units_that_differ_need_a_scale_on_every_joint():
    leader = Knob("knob", {"joints": ["a", "b"], "unit": "dynamixel_count"})
    with pytest.raises(ValueError, match="or give every joint a scale"):
        JointController("c", dict(CONTROLLER), leader, {"arm": _arm()})
    table = [
        {"leader": "a", "follower": "a", "sign": 1, "offset": 0, "scale": PER_COUNT},
        {"leader": "b", "follower": "b", "sign": 1, "offset": 0},  # no scale here
    ]
    with pytest.raises(ValueError, match="or give every joint a scale"):
        JointController("c", {**CONTROLLER, "joints": table}, leader, {"arm": _arm()})
    # the same unit: a scale is a gear ratio, and no scale is 1
    same = Knob("knob", {"joints": ["a", "b"], "unit": "rad"})
    table[0]["scale"] = 2.0
    geared = JointController(
        "c", {**CONTROLLER, "joints": table}, same, {"arm": _arm()}
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
        JointController("c", {**CONTROLLER, "joints": table}, same, {"arm": _arm()})


def test_force_feedback_is_refused_with_scaled_joints():
    with pytest.raises(ValueError, match="feedback: not with scaled joints"):
        _scaled(feedback={"estimator": "effort"})
