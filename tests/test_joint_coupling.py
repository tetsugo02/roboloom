"""Joint locking and measured-motion coupling without connecting to a robot."""

from __future__ import annotations

import time

import pytest
from conftest import rakuda2_tree

from roboloom.config import load_experiment, parse_experiment
from roboloom.control.device import JointDevice, build_laws, parse_groups
from roboloom.controllers.coupling import JointCouplings
from roboloom.controllers.joint import JointController
from roboloom.core.protocol import Envelope
from roboloom.drivers.mock import MockBus
from roboloom.inputs.base import ActuatedReader, JointInput
from roboloom.robots.safety import FollowerSafety

LINK = {"joint": "head_yaw", "source": "torso_yaw", "scale": -1.0, "reference": 2048}


def controller() -> JointController:
    base = load_experiment("examples/mock/experiment.yaml").controllers["controller"]
    assert isinstance(base, JointController) and base.source is not None
    return JointController(
        base.name,
        {**base.cfg, "couplings": [LINK]},
        base.source,
        base.robot,
        base.robot_id,
    )


def intent(seq: int, values: list[float], now: int, boot: str = "boot") -> Envelope:
    return Envelope(
        "joint_intent", "leader", boot, seq, now, now, {"positions": values}
    )


def test_compensation_uses_measured_motion_after_mapping() -> None:
    ctl = controller()
    # Sign and offset are applied to leader input before coupling.
    ctl.cfg["joints"][1].update(sign=-1, offset=4096)
    now = time.monotonic_ns() - 10_000_000_000
    initial = [2048.0] * 17
    assert ctl.update(intent(0, initial, now), initial, now) is not None
    actual, leader = initial.copy(), initial.copy()
    actual[0] += 100
    leader[0] += 400  # commanded torso is ahead of its measured pose
    leader[1] -= 20  # mapped head is 2068, including the operator's own head input
    cmd = ctl.update(
        intent(1, leader, now + 1_000_000_000), actual, now + 1_000_000_000
    )
    assert cmd is not None
    assert cmd.payload["positions"][:3] == [2448, 1968, 2048]
    assert actual[1] == 2048 and leader[1] == 2028  # input snapshots stay untouched


def test_coupling_keeps_speed_limit_and_follower_target_reference() -> None:
    ctl = controller()
    now = time.monotonic_ns() - 10_000_000_000
    hold = [2048.0] * 17
    assert ctl.update(intent(0, hold, now), hold, now, hold) is not None
    current = hold.copy()
    current[0] += 200
    for seq in range(1, 4):
        tick = now + seq * 10_000_000
        cmd = ctl.update(intent(seq, hold, tick), current, tick, hold)
        assert cmd is not None
        assert cmd.payload["positions"][1] == pytest.approx(2048 - 500 * 0.01)


def test_reference_is_configured_not_the_pose_at_alignment() -> None:
    ctl = controller()
    now = time.monotonic_ns() - 10_000_000_000
    # The leader torso is 100 counts from the follower's, within alignment tolerance.
    leader, actual = [2048.0] * 17, [2048.0] * 17
    actual[0], actual[1] = 2148, 1948  # follower camera heading already compensated
    cmd = ctl.update(intent(0, leader, now), actual, now)
    assert cmd is not None
    assert cmd.payload["positions"][:2] == pytest.approx([2148, 1948], abs=0.01)
    # Once the torso reaches the leader's pose, the head is the leader's head again;
    # a reference latched at alignment would leave it 100 counts off.
    actual[0] = 2048
    second = 1_000_000_000
    cmd = ctl.update(intent(1, leader, now + second), actual, now + second)
    assert cmd is not None and cmd.payload["positions"][:2] == [2048, 2048]
    # A leader restart realigns but keeps the same reference.
    actual[1] = 2048
    assert ctl.update(
        intent(0, leader, now + 2 * second, "restart"), actual, now + 2 * second
    )
    cmd = ctl.update(
        intent(1, leader, now + 3 * second, "restart"), actual, now + 3 * second
    )
    assert cmd is not None and cmd.payload["positions"][:2] == [2048, 2048]


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        ["head_yaw"],
        [{"joint": "head_yaw", "source": "torso_yaw", "scale": -1.0}],
        [{**LINK, "typo": 1}],
        [{**LINK, "joint": "missing"}],
        [{**LINK, "source": "missing"}],
        [{**LINK, "source": "head_yaw"}],
        [{**LINK, "scale": True}],
        [{**LINK, "scale": "-1"}],
        [{**LINK, "scale": float("nan")}],
        [{**LINK, "scale": float("inf")}],
        [{**LINK, "reference": None}],
        [{**LINK, "reference": True}],
        [{**LINK, "reference": float("nan")}],
        [LINK, LINK],
    ],
)
def test_invalid_couplings_fail_when_loading_yaml(raw: object) -> None:
    tree = rakuda2_tree()
    tree["controllers"]["controller"]["couplings"] = raw
    with pytest.raises(ValueError, match="couplings"):
        parse_experiment(tree)


def test_couplings_work_with_other_joint_names_and_snapshot_sources() -> None:
    links = JointCouplings(
        [
            {"joint": "tool", "source": "base", "scale": 0.5, "reference": 10},
            {"joint": "base", "source": "slider", "scale": -2, "reference": 30},
        ],
        ("base", "tool", "slider"),
        "test",
    )
    assert links.apply([100, 200, 300], [14, 20, 32]) == [96, 202, 300]
    overflow = JointCouplings(
        [{"joint": "tool", "source": "base", "scale": 1e308, "reference": 0}],
        ("base", "tool"),
        "test",
    )
    with pytest.raises(ValueError, match="finite"):
        overflow.apply([0, 0], [1e308, 0])


def test_position_locks_only_selected_leader_joints_and_seeds_before_torque() -> None:
    joints = ("base", "neck", "tilt")
    groups = parse_groups(
        [
            {"group": "free", "law": "free", "joints": ["base"]},
            {"group": "locked", "law": "position", "joints": ["neck", "tilt"]},
        ],
        joints,
        "leader",
    )

    class ObservedBus(MockBus):
        def __init__(self) -> None:
            super().__init__(dimension=3)
            self.events: list[tuple[str, list[int], list[float] | bool]] = []

        def write_goal_positions(self, indices: list[int], values: list[float]) -> None:
            self.events.append(("goal", indices.copy(), values.copy()))
            super().write_goal_positions(indices, values)

        def set_torque(self, indices: list[int], on: bool) -> None:
            self.events.append(("torque", indices.copy(), on))
            super().set_torque(indices, on)

    bus = ObservedBus()
    bus.values = [1000.0, 2000.0, 2500.0]
    reader = ActuatedReader(JointDevice(bus, joints, build_laws(groups, joints)))
    try:
        assert bus.events[:2] == [
            ("goal", [1, 2], [2000, 2500]),
            ("torque", [1, 2], True),
        ]
        assert bus.torque == [False, True, True] and not bus.eeprom_writes
        bus.values = [1200.0, 1990.0, 2490.0]
        reader.read()
        assert bus.values == [1200, 2000, 2500]
        reader.on_session("estop")
        assert not any(bus.torque)
    finally:
        reader.close()


def test_rakuda_leader_locking_uses_the_normal_yaml_control_groups() -> None:
    tree = rakuda2_tree()
    tree["experiment"]["mode"] = "mock"
    groups = tree["inputs"]["leader"]["control"]
    groups[0]["joints"] = ["torso_yaw"]
    groups.append(
        {"group": "fixed_head", "law": "position", "joints": ["head_yaw", "head_pitch"]}
    )
    cfg = parse_experiment(tree)
    leader = cfg.inputs["leader"]
    assert isinstance(leader, JointInput)
    reader = leader.open(True, cfg.dataset_fps)
    assert isinstance(reader, ActuatedReader)
    try:
        assert reader.device.bus.torque[:3] == [False, True, True]
        reader.read()
    finally:
        reader.close()


def test_compensated_commands_still_pass_through_robot_safety_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctl = controller()
    bus = MockBus(dimension=17)
    limits = [
        {"min": 0, "max": 4095, "max_speed": 3000, "max_jump": 400} for _ in range(17)
    ]
    limits[1]["min"] = 2000  # head has little travel left in this direction
    safety = FollowerSafety(
        {"robot_id": ctl.robot_id, "limits": limits, "control_hz": 30}, bus
    )
    safety.start()
    safety.arm()
    now = time.monotonic_ns() - 1_000_000_000
    tick = now
    monkeypatch.setattr("roboloom.core.protocol.time.monotonic_ns", lambda: tick)
    safety.tick(now)
    initial = bus.values.copy()
    assert ctl.update(intent(0, initial, now), initial, now) is not None
    actual, leader = initial.copy(), initial.copy()
    actual[0] += 300
    leader[0] += 300
    bus.values = actual
    tick = now + 500_000_000
    cmd = ctl.update(intent(1, leader, tick), actual, tick)
    assert cmd is not None and cmd.payload["positions"][1] == 1798
    safety.accept(cmd)
    _, action = safety.tick(tick)
    assert action.payload["valid"] and action.payload["clamped"]
    assert bus.values[1] == 2000  # compensation cannot bypass a head travel limit
    safety.stop()
    safety.release()
