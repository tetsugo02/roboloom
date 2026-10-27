"""Moving the leader and follower to a saved pose (`home`) before an episode."""

from __future__ import annotations

import shutil
import time
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
import yaml
from conftest import mock_project, rakuda2_tree
from test_control_laws import GRAVITY, FlatGravity

from roboloom.config import parse_experiment
from roboloom.control.device import JointDevice, build_laws, parse_groups
from roboloom.control.homing import Trajectory, load_pose
from roboloom.drivers.mock import MockBus
from roboloom.errors import ConfigError, SetupError
from roboloom.robots.safety import FollowerSafety
from roboloom.runtime.node import home_warning, start_warning
from roboloom.setup import capture_pose

SECOND = 1_000_000_000


def test_trajectory_moves_every_joint_together_within_the_speed() -> None:
    path = Trajectory([0, 100, 50], [400, 100, -50], max_speed=200)
    assert path.duration_s == pytest.approx(np.pi / 2 * 400 / 200)
    times = np.linspace(0, path.duration_s, 2001)
    points = np.array([path.at(t) for t in times])
    speed = np.abs(np.diff(points, axis=0)) / np.diff(times)[:, None]
    assert speed.max() <= 200 * 1.001
    assert path.at(path.duration_s) == [400, 100, -50]
    assert path.at(path.duration_s / 2) == pytest.approx([200, 100, 0])
    assert Trajectory([1, 2], [1, 2], 10).at(0) == [1, 2]  # already there


def write_pose(path: Path, values: dict, **extra) -> Path:
    body = {"robot_type": "rakuda2", "unit": "dynamixel_count", "pose": values, **extra}
    path.write_text(yaml.safe_dump(body))
    return path


JOINTS = ("a", "b")
LIMITS = [{"min": 0, "max": 4095}] * 2


@pytest.mark.parametrize(
    ("values", "extra", "match"),
    [
        ({"a": 1}, {}, "joints differ"),
        ({"a": 1, "b": 2, "c": 3}, {}, "joints differ"),
        ({"a": 1, "b": 5000}, {}, "outside"),
        ({"a": 1, "b": float("nan")}, {}, "outside"),
        ({"a": 1, "b": 2}, {"robot_type": "other"}, "saved for other"),
    ],
)
def test_pose_files_are_checked_against_the_robot(tmp_path, values, extra, match):
    path = write_pose(tmp_path / "p.yaml", values, **extra)
    with pytest.raises(ConfigError, match=match):
        load_pose(path, "rakuda2", "dynamixel_count", JOINTS, LIMITS)
    with pytest.raises(ConfigError, match="capture-pose"):
        load_pose(
            tmp_path / "missing.yaml", "rakuda2", "dynamixel_count", JOINTS, LIMITS
        )


def test_capture_pose_saves_the_follower_pose_by_name(tmp_path):
    project = mock_project(tmp_path / ".roboloom")
    path = capture_pose(project / "experiment.yaml", "ready")
    assert path == project / "poses" / "ready.yaml"
    saved = yaml.safe_load(path.read_text())
    assert saved["robot_type"] == "rakuda2" and saved["pose"]["torso_yaw"] == 2048
    assert len(saved["pose"]) == 17
    with pytest.raises(SetupError, match="exists"):
        capture_pose(project / "experiment.yaml", "ready")
    capture_pose(project / "experiment.yaml", "ready", force=True)
    with pytest.raises(ConfigError, match="pose name"):
        capture_pose(project / "experiment.yaml", "../escape")


def home_tree(tmp_path: Path, **home) -> dict:
    tree = rakuda2_tree()
    pose = {j: 2048 for j in tree["robots"]["robot"]["limits"][0:0] or []}
    names = [limit["name"] for limit in tree["robots"]["robot"]["limits"]]
    pose = {j: 2048 for j in names}
    pose["torso_yaw"], pose["head_yaw"] = 2148, 2000
    path = write_pose(tmp_path / "ready.yaml", pose)
    controller = tree["controllers"]["controller"]
    controller["home"] = {"pose": str(path), "max_speed": 200, **home}
    controller["couplings"] = [
        {"joint": "head_yaw", "source": "torso_yaw", "scale": -1.0, "reference": 2048}
    ]
    return tree


def test_leader_pose_maps_back_through_signs_offsets_and_couplings(tmp_path):
    cfg = parse_experiment(home_tree(tmp_path))
    controller = cfg.controllers["controller"]
    assert controller.home is not None and controller.home.pose.name == "ready"
    follower = controller.home.target(cfg.robot.joint_names)
    leader = controller.leader_pose(follower)
    # the head target gets -(torso - reference) = -100 added: the leader neck sits 100 higher
    assert leader["head_yaw"] == 2100 and leader["torso_yaw"] == 2148
    from roboloom.core.protocol import Envelope

    now = time.monotonic_ns()
    intent = Envelope(
        "joint_intent",
        "leader",
        "boot",
        0,
        now,
        now,
        {"positions": [leader[j] for j in cfg.inputs["leader"].joint_names]},
    )
    controller.update(intent, follower, now)
    assert controller.status()["worst_diff"] == pytest.approx(0, abs=1e-6)
    assert controller.status()["home"] == "ready"


def test_home_settings_are_checked(tmp_path):
    with pytest.raises(ConfigError, match="max_speed_counts_per_s"):
        parse_experiment(home_tree(tmp_path, max_speed=10_000))
    tree = home_tree(tmp_path)
    tree["controllers"]["controller"]["home"].pop("max_speed")
    with pytest.raises(ConfigError, match="needs pose and max_speed"):
        parse_experiment(tree)


def test_gravity_leader_groups_need_a_homing_spring(tmp_path):
    from test_tools import gravity_tree

    tree = gravity_tree(tmp_path)
    tree["controllers"]["controller"]["home"] = home_tree(tmp_path)["controllers"][
        "controller"
    ]["home"]
    tree["experiment"]["mode"] = "mock"
    for group in tree["inputs"]["leader"]["control"]:
        group.pop("homing", None)  # the template ships one; take it away
    with pytest.raises(ConfigError, match="need homing"):
        parse_experiment(deepcopy(tree))
    for group in tree["inputs"]["leader"]["control"]:
        if group["law"] == "gravity_comp":
            group["homing"] = {"kp_mA_per_count": 0.5, "max_mA": 40}
    assert parse_experiment(tree).controllers["controller"].home is not None


def safety() -> tuple[FollowerSafety, MockBus]:
    bus = MockBus(dimension=2)
    limit = {"min": 0, "max": 4095, "max_speed": 3000, "max_jump": 400}
    ctl = FollowerSafety(
        {"robot_id": "r", "limits": [limit, limit], "control_hz": 100}, bus
    )
    ctl.start()
    return ctl, bus


def test_follower_moves_home_slowly_then_holds_there():
    ctl, bus = safety()
    t0 = time.monotonic_ns() - 30 * SECOND  # ticks must not be in the future
    ctl.home([2448, 1848], max_speed=200, name="ready", now_ns=t0)
    assert ctl.mode == "HOMING"
    previous, fastest = list(bus.values), 0.0
    t = t0
    while ctl.mode == "HOMING" and t < t0 + 10 * SECOND:
        t += SECOND // 100
        ctl.tick(t)
        fastest = max(
            fastest, *(abs(a - b) * 100 for a, b in zip(bus.values, previous))
        )
        previous = list(bus.values)
    assert ctl.mode == "HOLD" and ctl.home_reached and bus.values == [2448, 1848]
    assert fastest <= 200 * 1.01  # slow by design
    ctl.tick(t + SECOND)  # holds the pose, does not creep
    assert bus.values == [2448, 1848] and ctl.hold_target == [2448, 1848]


def test_home_is_interrupted_by_stop_and_refused_while_following():
    ctl, bus = safety()
    t0 = time.monotonic_ns() - 30 * SECOND  # ticks must not be in the future
    ctl.home([2448, 2048], 200, "ready", t0)
    ctl.tick(t0 + SECOND // 2)
    reached = list(bus.values)
    ctl.stop()
    ctl.tick(t0 + SECOND)
    assert ctl.mode == "HOLD" and bus.values == reached and 2048 < reached[0] < 2448
    ctl.arm()
    with pytest.raises(RuntimeError, match="stopped in HOLD"):
        ctl.home([2048, 2048], 200, "ready")
    ctl.stop(estop=True)
    with pytest.raises(RuntimeError, match="ESTOP"):
        ctl.home([2048, 2048], 200, "ready")


def leader_device() -> tuple[JointDevice, MockBus]:
    """a, b gravity-compensated (current), c locked (position), d free in position mode."""
    groups = [
        {**GRAVITY, "homing": {"kp_mA_per_count": 1.0, "max_mA": 20}},
        {"group": "c", "law": "position", "joints": ["c"]},
        {"group": "d", "law": "free", "joints": ["d"]},
    ]
    joints = ("a", "b", "c", "d")
    specs = parse_groups(groups, joints, "dev")
    laws = build_laws(specs, joints, models={"arm": FlatGravity()})
    bus = MockBus(dimension=4, modes=[0, 0, 3, 3])
    device = JointDevice(bus, joints, laws, "leader")
    device.read_state()
    device.enable_torque()
    return device, bus


def test_leader_moves_home_by_capped_springs_then_gravity_comp_resumes():
    device, bus = leader_device()
    assert bus.torque == [True, True, True, False]  # d is free
    t0 = time.monotonic_ns()
    goal = {"a": 2048 + 1000, "b": 2048 - 1000, "c": 2248, "d": 1848}
    device.begin_home(goal, max_speed=200, tolerance=5, name="ready", now_ns=t0)
    assert bus.torque[3]  # the free joint is driven during the move
    duration = device.home.trajectory.duration_s
    device.read_state()
    device.command(None, t0 + int(duration * SECOND))  # at the end of the move
    # FlatGravity gives a 100 and b -50 mA; each spring adds at most 20 mA
    assert bus.goal_current[1] == pytest.approx(-50 - 20)
    assert bus.goal_current[0] == pytest.approx(GRAVITY["max_current_mA"])  # total cap
    assert bus.values[2:] == [2248, 1848]  # position goals reached the pose
    assert device.home_status(t0)["home_state"] == "moving"  # settling
    settled = t0 + int((duration + 1.5) * SECOND)
    device.read_state()
    device.command(None, settled)  # settling over: back to the normal laws
    result = device.home_status(settled)
    # springs left a and b short (the mock does not move current joints)
    assert result["home_state"] == "short"
    assert result["home_far"] == {"a": -1000, "b": 1000}
    assert not bus.torque[3]  # the free joint is limp again
    device.read_state()
    device.command(None, settled + SECOND)
    assert bus.values[2] == 2248  # the lock keeps the home pose
    assert bus.goal_current[1] == pytest.approx(-50)  # gravity only, no spring
    device.end_home()  # start clears the result
    assert device.home_status() == {}


def test_estop_during_home_leaves_the_leader_limp():
    device, bus = leader_device()
    device.begin_home({"a": 2100, "b": 2048, "c": 2048, "d": 2048}, 200, 5, "ready")
    device.disable_torque()
    assert not any(bus.torque) and device.home is None


def status(t_ns: int, **fields) -> dict:
    return {"t_ns": t_ns, "fields": fields}


def test_session_refuses_home_while_recording_and_start_while_moving(tmp_path):
    cfg = parse_experiment(home_tree(tmp_path))
    now = time.monotonic_ns()
    latest = {"recorder": status(now, state="recording")}
    assert "stop the episode" in home_warning(cfg, latest, now)
    latest = {"recorder": status(now, state="idle"), "robot": status(now, armed=True)}
    assert "following" in home_warning(cfg, latest, now)
    latest = {"robot": status(now, armed=False)}
    assert home_warning(cfg, latest, now) is None
    ready = status(now, state="following", worst_diff=0, tolerance=300)
    moving = {
        "controller": ready,
        "robot": status(now, home="ready", home_state="moving"),
    }
    assert "moving home" in start_warning(cfg, moving, now)
    moving["robot"] = status(now, home="ready", home_state="reached")
    assert start_warning(cfg, moving, now) is None


@pytest.mark.skipif(shutil.which("dora") is None, reason="needs dora")
def test_session_moves_home_then_records_from_there(tmp_path):
    from roboloom.runtime.session import Session

    project = mock_project(tmp_path / ".roboloom")
    capture_pose(project / "experiment.yaml", "ready")
    pose = project / "poses" / "ready.yaml"
    saved = yaml.safe_load(pose.read_text())
    saved["pose"]["torso_yaw"], saved["pose"]["r_arm_sh_pitch1"] = 2100, 2000
    pose.write_text(yaml.safe_dump(saved))
    controller = project / "nodes" / "controller.yaml"
    controller.write_text(
        controller.read_text()
        + "home:\n  pose: ../poses/ready.yaml\n  max_speed: 400\n  timeout_s: 20\n"
    )
    with Session.launch(project / "experiment.yaml") as s:
        s.wait_ready(30)
        s.home()
        robot = s.status()["robot"]["fields"]
        assert robot["home"] == "ready" and robot["home_state"] == "reached"
        result = s.record("from home", 1.0, home=True)
    assert result.saved and result.frames > 5
