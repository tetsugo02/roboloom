import time
from copy import deepcopy

import numpy as np
import pytest
from conftest import rakuda2_tree

from roboloom.config import parse_experiment
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
    return rakuda2_tree()


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


def test_undriven_joint_may_fall_fast_but_not_leave_its_range():
    dev, bus = device(
        [
            {**GRAVITY, "gravity_gain": [0.5, 0.0]},
            {"group": "c", "law": "free", "joints": ["c"]},
        ],
        [0, 0, 3],
        FlatGravity(),
    )
    dev.read_state()
    dev.enable_torque()
    bus.velocities = [0.0, -5000.0, 0.0]  # b is not driven: a limp fall, not a runaway
    dev.read_state()
    dev.command(None)
    bus.velocities = [-5000.0, 0.0, 0.0]  # a is driven
    dev.read_state()
    with pytest.raises(RunawayError, match="a:"):
        dev.command(None)


def test_release_trial_reports_drift_and_leaves_torque_off():
    from roboloom import tools

    dev, bus = device(
        [GRAVITY, {"group": "c", "law": "free", "joints": ["c"]}],
        [0, 0, 3],
        FlatGravity(),
    )
    law = dev.laws[0]
    ticks = []

    def sleep(_):
        ticks.append(1)
        if len(ticks) > 5:
            bus.values[0] -= 10  # the arm sinks after the release

    result = tools.release_trial(
        dev, law, [1.0, 1.0], 0.1, 0.1, 0.02, sleep, lambda: None
    )
    assert law.gain == [1.0, 1.0]
    q0, model, sent, drift, _ = result["a"]
    assert (
        q0 == 2048 and model == 100 and sent > 0 and drift < 0 and result["b"][3] == 0
    )
    assert not any(bus.torque)


def test_breakaway_hold_resists_up_to_hold_mA_then_slides():
    dev, bus = device(
        [
            {
                **GRAVITY,
                "gravity_gain": 0.0,
                "hold_mA": [20, 0],
                "hold_kp": 1.0,
                "ramp_s": 0.01,
            },
            {"group": "c", "law": "free", "joints": ["c"]},
        ],
        [0, 0, 3],
        FlatGravity(),
    )
    dev.read_state()
    dev.enable_torque()
    t = time.monotonic_ns()
    steps = iter(range(1, 100))

    def at(q):
        bus.values[0] = q
        dev.read_state()
        dev.command(None, t + next(steps) * int(0.02e9))
        return bus.goal_current[0]

    assert at(2048) == 0
    assert at(2038) == 10  # pushed 10 counts: pulls back with 10 mA
    assert at(2000) == 20  # pushed harder: capped at hold_mA, the anchor slides
    assert at(2000) == 20
    assert at(2010) == 10  # let go of the push: the anchor stayed at 2020
    assert bus.goal_current[1] == 0  # no hold on b


def test_tuning_session_changes_values_live_and_saves_them(tmp_path):
    import yaml

    from roboloom.control.tuning import TuningSession

    path = tmp_path / "tuning.yaml"
    path.write_text(
        "# header kept\nhold_kp: 1.0\njoints:\n"
        "  a: {gain: 1.0, hold_mA: 0, hint: 'arm out'}\n  b: {gain: 0.0, hold_mA: 0}\n"
    )
    dev, bus = device(
        [
            {**GRAVITY, "gravity_gain": [1.0, 0.0], "ramp_s": 0.01},
            {"group": "c", "law": "free", "joints": ["c"]},
        ],
        [0, 0, 3],
        FlatGravity(),
    )
    session = TuningSession(dev, dev.laws[0], path, {"a": 1, "b": 2})
    session.start()
    t = time.monotonic_ns()
    session.step(t + int(0.1e9))
    assert bus.goal_current[0] == 80  # 100 mA clipped
    assert "gain 1.1" in session.key("]")
    session.key("=")
    assert session.key("0").endswith("OFF (compare)")
    session.step(t + int(0.2e9))
    assert bus.goal_current[0] == 0  # gravity term off, hold anchored at the pose
    session.key("0")
    session.key("j")
    assert session.rows()[1].joint == "b" and session.selected == 1
    session.key("s")
    saved = yaml.safe_load(path.read_text())
    assert path.read_text().startswith("# header kept")
    assert saved["joints"]["a"] == {"gain": 1.1, "hold_mA": 5.0, "hint": "arm out"}
    assert not session.dirty
    bus.values[0] = 9000  # far outside the range: runaway, the device goes limp
    session.step(t + int(0.3e9))
    assert session.stopped and not any(bus.torque)
    bus.values[0] = 2048
    assert "re-enabled" in session.key("r") and bus.torque[0]
