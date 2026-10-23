import time
from copy import deepcopy

import numpy as np
import pytest

from roboloom.config import parse_experiment, read_experiment
from roboloom.control.device import JointDevice, build_laws, parse_groups
from roboloom.control.laws import RunawayError
from roboloom.drivers.mock import MockBus
from roboloom.robots.safety import FollowerSafety

JOINTS = ("a", "b", "c")


class FlatGravity:
    """g(q) = 100 mA on a and -50 mA on b, independent of q."""

    joint_names = ("a", "b")
    output_joints = ("a", "b")

    def effort_mA(self, positions):
        return [100.0, -50.0]


def device(groups, modes, gravity=None):
    specs = parse_groups(groups, JOINTS, "dev")
    laws = build_laws(specs, JOINTS, models={"arm": gravity} if gravity else None)
    bus = MockBus(dimension=3, modes=modes)
    return JointDevice(bus, JOINTS, laws, "dev"), bus


GRAVITY = {
    "group": "arm",
    "law": "gravity_comp",
    "joints": ["a", "b"],
    "max_current_mA": 80,
    "kd": 0.0,
    "ramp_s": 1.0,
    "max_velocity": 2000,
    "range": [[1000, 3000], [1000, 3000]],
    "range_margin": 100,
}


def test_groups_must_cover_every_joint_once():
    with pytest.raises(ValueError, match="exactly once"):
        parse_groups(
            [{"group": "x", "law": "position", "joints": ["a", "b"]}], JOINTS, "dev"
        )
    with pytest.raises(ValueError, match="law"):
        parse_groups(
            [{"group": "x", "law": "teleport", "joints": list(JOINTS)}], JOINTS, "dev"
        )


def test_modes_are_checked_never_written_on_enable():
    dev, bus = device(
        [{"group": "all", "law": "position", "joints": list(JOINTS)}], [3, 3, 0]
    )
    dev.read_state()
    with pytest.raises(RuntimeError, match="commission"):
        dev.enable_torque()
    assert not bus.eeprom_writes and not any(bus.torque)


def test_gravity_comp_ramps_clips_and_zeroes_current_before_torque():
    groups = [
        GRAVITY,
        {
            "group": "grip",
            "law": "current_position",
            "joints": ["c"],
            "goal_current_mA": 30,
            "target": 2400,
        },
    ]
    dev, bus = device(groups, [0, 0, 5], FlatGravity())
    bus.goal_current = [910.0, 910.0, 910.0]  # power-on value equals Current Limit
    dev.read_state()
    dev.enable_torque()
    assert bus.torque == [True, True, True]
    assert bus.goal_current[:2] == [0.0, 0.0]  # zero at torque-on (ramp starts at 0)
    assert bus.values[2] == 2400 and bus.goal_current[2] == 30  # trigger spring
    t = time.monotonic_ns()
    for k in range(1, 4):
        dev.read_state()
        dev.command(None, t + int(k * 0.5e9))
    assert bus.goal_current[0] == 80  # 100 mA clipped to max_current_mA after the ramp
    assert bus.goal_current[1] == -50


def test_runaway_and_bus_failure_leave_device_limp():
    dev, bus = device(
        [GRAVITY, {"group": "c", "law": "free", "joints": ["c"]}],
        [0, 0, 3],
        FlatGravity(),
    )
    dev.read_state()
    dev.enable_torque()
    bus.values[0] = 3200  # beyond range + margin
    dev.read_state()
    with pytest.raises(RunawayError):
        dev.command(None)
    assert not any(bus.torque) and bus.goal_current[:2] == [0.0, 0.0]
    bus.values[0] = 2000
    dev.enable_torque()
    bus.fail = True
    with pytest.raises(ConnectionError):
        dev.read_state()


def test_follower_safety_drives_a_device_like_a_bus():
    groups = [
        {"group": "arm", "law": "position", "joints": ["a", "b"]},
        {
            "group": "grip",
            "law": "current_position",
            "joints": ["c"],
            "goal_current_mA": 300,
        },
    ]
    dev, bus = device(groups, [3, 3, 5])
    limit = {"min": 0, "max": 4095, "max_speed": 3000, "max_jump": 400}
    safety = FollowerSafety(
        {"robot_id": "r", "limits": [limit] * 3, "control_hz": 30}, dev
    )
    safety.start()
    assert bus.torque == [True, True, True] and bus.goal_current[2] == 300
    safety.stop()
    safety.release()
    assert not any(bus.torque) and safety.mode == "RELEASED"


def test_runtime_switch_changes_one_group_with_torque_off():
    groups = [
        {"group": "arm", "law": "free", "joints": ["a", "b"]},
        {"group": "c", "law": "position", "joints": ["c"]},
    ]
    dev, bus = device(groups, [3, 3, 3])
    dev.read_state()
    dev.enable_torque()
    new = build_laws(
        parse_groups(
            [GRAVITY, {"group": "c", "law": "position", "joints": ["c"]}], JOINTS, "dev"
        ),
        JOINTS,
        models={"arm": FlatGravity()},
    )[0]
    dev.switch("arm", new)
    assert bus.modes[:2] == [0, 0] and bus.torque[:2] == [True, True]
    assert ("operating_mode", [0, 1], [0, 0]) in bus.eeprom_writes


def hardware_tree():
    tree = read_experiment("examples/rakuda2/experiment.yaml")
    tree["inputs"]["leader"]["port"] = "/dev/serial/by-id/leader"
    tree["robots"]["robot"]["port"] = "/dev/serial/by-id/follower"
    for limit in tree["robots"]["robot"]["limits"]:
        limit["min"], limit["max"] = 1000, 3000
    return tree


def test_hardware_refuses_unvalidated_and_unprotected_current_laws():
    tree = hardware_tree()
    joints = [x["name"] for x in tree["robots"]["robot"]["limits"]]
    impedance = {
        "group": "all",
        "law": "impedance",
        "joints": joints,
        "kp": 1.0,
        "max_current_mA": 500,
        "max_velocity": 2000,
        "range": [[1000, 3000]] * 17,
    }
    tree["robots"]["robot"]["control"] = [impedance]
    del tree["robots"]["robot"]["registers"]["operating_mode"]
    with pytest.raises(ValueError, match="not validated"):
        parse_experiment(deepcopy(tree))
    impedance["allow_unvalidated"] = True
    with pytest.raises(ValueError, match="bus_watchdog_ms"):
        parse_experiment(deepcopy(tree))
    tree["robots"]["robot"]["bus_watchdog_ms"] = 200
    with pytest.raises(ValueError, match="current_limit"):
        parse_experiment(deepcopy(tree))
    tree["mode"] = "mock"
    tree["experiment"]["mode"] = "mock"
    assert parse_experiment(tree).robot.control is not None


def test_mock_leader_with_trigger_spring_runs_as_actuated_input():
    tree = hardware_tree()
    tree["experiment"]["mode"] = "mock"
    joints = [x["name"] for x in tree["robots"]["robot"]["limits"]]
    arms = [j for j in joints if not j.endswith("grip")]
    tree["inputs"]["leader"]["control"] = [
        {"group": "hand", "law": "free", "joints": arms},
        {
            "group": "trigger",
            "law": "current_position",
            "joints": ["r_arm_grip", "l_arm_grip"],
            "goal_current_mA": 30,
            "target": 2400,
        },
    ]
    cfg = parse_experiment(tree)
    leader = cfg.inputs["leader"]
    assert leader.actuated
    reader = leader.open(True, cfg.dataset_fps)
    sample = reader.read()
    assert np.asarray(sample.value).shape == (17,)
    bus = reader.device.bus
    assert bus.values[joints.index("r_arm_grip")] == 2400
    reader.on_session("estop")
    assert not any(bus.torque)
    reader.close()


def test_position_joints_keep_torque_when_a_write_fails():
    dev, bus = device(
        [{"group": "all", "law": "position", "joints": list(JOINTS)}], [3, 3, 3]
    )
    dev.read_state()
    dev.enable_torque()

    def fail(indices, values):
        raise ConnectionError("write failed")

    bus.write_goal_positions = fail
    dev.read_state()
    with pytest.raises(ConnectionError):
        dev.command([2050.0] * 3)
    assert bus.torque == [True, True, True]  # a follower must not drop on a bus error
    dev.disable_torque()
    assert not any(bus.torque)


def test_spring_holds_rest_with_capped_current_and_needs_a_capable_bus():
    dev, bus = device(
        [
            {"group": "arm", "law": "free", "joints": ["a", "b"]},
            {
                "group": "trigger",
                "law": "spring",
                "joints": ["c"],
                "rest": 2600,
                "goal_current_mA": 20,
            },
        ],
        [3, 3, 5],
    )
    dev.read_state()
    dev.enable_torque()
    assert (
        bus.values[2] == 2600
        and bus.goal_current[2] == 20
        and bus.torque == [False, False, True]
    )
    with pytest.raises(ValueError, match="rest"):
        parse_and_build(
            [
                {
                    "group": "all",
                    "law": "spring",
                    "joints": list(JOINTS),
                    "goal_current_mA": 20,
                }
            ]
        )

    class PositionOnlyBus:
        def read_positions(self):
            return [0.0] * 3

        def write_goal_positions(self, indices, values):
            pass

        def set_torque(self, indices, on):
            pass

        def read_register(self, name):
            return [5] * 3

        def close(self):
            pass

    laws = parse_and_build(
        [
            {
                "group": "all",
                "law": "spring",
                "joints": list(JOINTS),
                "rest": 2600,
                "goal_current_mA": 20,
            }
        ]
    )
    with pytest.raises(TypeError, match="write_goal_currents"):
        JointDevice(PositionOnlyBus(), JOINTS, laws)


def parse_and_build(groups):
    return build_laws(parse_groups(groups, JOINTS, "dev"), JOINTS)


def test_range_can_name_a_measured_travel_file(tmp_path):
    (tmp_path / "travel.yaml").write_text(
        "travel:\n  a: [1000, 3000]\n  b: [1500, 2500]\n"
    )
    spec = {**GRAVITY, "range": "travel.yaml"}
    laws = build_laws(
        parse_groups(
            [spec, {"group": "rest", "law": "free", "joints": ["c"]}], JOINTS, "dev"
        ),
        JOINTS,
        str(tmp_path),
        models={"arm": FlatGravity()},
    )
    assert laws[0].range == [(1000.0, 3000.0), (1500.0, 2500.0)]
    (tmp_path / "travel.yaml").write_text("travel:\n  a: [1000, 3000]\n")
    with pytest.raises(ValueError, match="no measured travel"):
        build_laws(
            parse_groups(
                [spec, {"group": "rest", "law": "free", "joints": ["c"]}], JOINTS, "dev"
            ),
            JOINTS,
            str(tmp_path),
            models={"arm": FlatGravity()},
        )


def test_fired_bus_watchdog_releases_current_joints():
    from roboloom.control.device import WatchdogFired

    groups = [GRAVITY, {"group": "c", "law": "position", "joints": ["c"]}]
    dev, bus = device(groups, [0, 0, 3], FlatGravity())
    dev.read_state()
    dev.enable_torque()
    bus.watchdog[1] = -1  # the loop stalled: the motor froze its goal current
    with pytest.raises(WatchdogFired, match="b"):
        dev.command(None)
    assert bus.torque == [False, False, True]  # current joints released, position kept


def test_gravity_gain_can_differ_per_joint():
    dev, bus = device(
        [
            {**GRAVITY, "gravity_gain": [0.5, 0.0], "ramp_s": 0.1},
            {"group": "c", "law": "free", "joints": ["c"]},
        ],
        [0, 0, 3],
        FlatGravity(),
    )
    dev.read_state()
    dev.enable_torque()
    t = time.monotonic_ns()
    for k in range(1, 3):
        dev.read_state()
        dev.command(None, t + int(k * 0.2e9))
    assert bus.goal_current[:2] == [50.0, 0.0]
