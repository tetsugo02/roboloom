"""`home:` of a policy controller, and the measured arrival check of every home move."""

from __future__ import annotations

import shutil
import time

import pytest
import yaml
from conftest import mock_project
from test_homing import SECOND, status

from roboloom.config import load_config
from roboloom.drivers.mock import MockBus
from roboloom.errors import ConfigError
from roboloom.robots.safety import HOME_SETTLE_S, FollowerSafety
from roboloom.runtime.node import start_warning
from roboloom.setup import capture_pose

HOME = {"pose": "../poses/follower/ready.yaml", "max_speed": 400, "tolerance": 30}


def _project(tmp_path, home=None, **policy):
    project = mock_project(tmp_path / ".roboloom")
    capture_pose(project / "config.yaml", "ready")
    pose = project / "poses" / "follower" / "ready.yaml"
    saved = yaml.safe_load(pose.read_text())
    saved["pose"]["torso_yaw"], saved["pose"]["r_arm_sh_pitch1"] = 2100, 2000
    pose.write_text(yaml.safe_dump(saved))
    path = project / "nodes" / "policy.yaml"
    node = yaml.safe_load(path.read_text())
    node.update(policy, observe=[])
    if home is not None:
        node["home"] = home
    path.write_text(yaml.safe_dump(node))
    return project / "config.yaml"


# -- configuration -----------------------------------------------------------------


@pytest.mark.parametrize("home", [HOME, {"follower": HOME}])
def test_a_policy_reads_its_home_pose(tmp_path, home):
    cfg = load_config(_project(tmp_path, home), options=["policy"])
    spec = cfg.controllers["policy"].homes["follower"]
    assert spec.pose.name == "ready" and spec.tolerance == 30
    target = spec.target(cfg.followers["follower"].joint_names)
    assert target[0] == 2100  # torso_yaw


@pytest.mark.parametrize(
    ("home", "match"),
    [
        ({**HOME, "max_speed": 5000}, "exceeds the controller's max_speed"),
        ({**HOME, "pose": "../poses/follower/none.yaml"}, "no such pose"),
        ({"other": HOME}, "pose, max_speed, tolerance"),
        ({"pose": HOME["pose"]}, "needs pose, max_speed and tolerance"),
    ],
)
def test_bad_policy_homes_are_refused(tmp_path, home, match):
    with pytest.raises(ConfigError, match=match):
        load_config(_project(tmp_path, home), options=["policy"])


def test_a_policy_without_home_has_none(tmp_path):
    cfg = load_config(_project(tmp_path), options=["policy"])
    assert cfg.controllers["policy"].homes == {}


# -- the measured arrival ----------------------------------------------------------


class Sagging(MockBus):
    """Joint 0 stays `sag` below every goal (gravity the position loop cannot beat)."""

    def __init__(self, sag: float):
        super().__init__(dimension=2)
        self.sag = sag

    def write_goal_positions(self, indices, values):
        super().write_goal_positions(indices, values)
        self.values[0] -= self.sag


def _safety(sag: float) -> FollowerSafety:
    limit = {"min": 0, "max": 4095, "max_speed": 3000, "max_jump": 400}
    ctl = FollowerSafety(
        {"name": "r", "unit": "dynamixel_count", "limits": [limit, limit]},
        Sagging(sag),
    )
    ctl.start()
    return ctl


def _move(ctl: FollowerSafety, tolerance: float | None):
    """Start the move (about 0.8 s); yields after each 10 ms tick, with the elapsed s."""
    t0 = time.monotonic_ns() - 60 * SECOND  # ticks must not be in the future
    ctl.home([2248, 1948], max_speed=400, name="ready", now_ns=t0, tolerance=tolerance)
    t = t0
    while True:
        t += SECOND // 100
        ctl.tick(t)
        yield (t - t0) / SECOND


def _run(ctl: FollowerSafety, seconds: float, tolerance: float | None) -> None:
    for elapsed in _move(ctl, tolerance):
        if elapsed >= seconds:
            return


def test_home_is_reached_once_the_measured_joints_are_within_tolerance():
    ctl = _safety(sag=10)
    _run(ctl, 3, tolerance=30)
    assert ctl.home_reached and not ctl.home_short
    assert ctl.home_diff == ("0", pytest.approx(10))


def test_home_is_short_when_a_joint_stays_out_of_tolerance():
    ctl = _safety(sag=50)
    for elapsed in _move(ctl, tolerance=30):
        if 1.5 <= elapsed < 2.5:  # the move ended at 0.8 s; still 50 out
            assert ctl.mode == "HOLD" and ctl.home_settling_ns is not None
            assert not ctl.home_reached and not ctl.home_short
        if elapsed >= 1 + HOME_SETTLE_S + 0.5:
            break
    assert ctl.home_short and not ctl.home_reached
    assert ctl.home_diff == ("0", pytest.approx(50))
    ctl.arm()  # the next episode forgets it
    assert not ctl.home_short and ctl.home_diff is None


def test_without_a_tolerance_the_end_of_the_move_counts():
    ctl = _safety(sag=50)
    _run(ctl, 3, tolerance=None)
    assert ctl.home_reached


def test_start_is_refused_while_settling_or_short(tmp_path):
    cfg = load_config(_project(tmp_path, HOME), options=["policy"])
    now = time.monotonic_ns()
    ready = status(now, state="ready")
    latest = {
        "policy": ready,
        "follower": status(now, home="ready", home_state="settling"),
    }
    assert "still moving home" in start_warning(cfg, latest, now)
    latest["follower"] = status(
        now,
        home="ready",
        home_state="short",
        home_joint="r_arm_sh_pitch1",
        home_diff=80,
        home_tolerance=30,
    )
    warning = start_warning(cfg, latest, now)
    assert "r_arm_sh_pitch1 is 80 from the pose (tolerance 30)" in warning
    latest["follower"] = status(now, home="ready", home_state="reached")
    assert start_warning(cfg, latest, now) is None


# -- CLI and the dataflow ----------------------------------------------------------


def test_infer_takes_home(tmp_path, monkeypatch):
    from roboloom import cli

    _project(tmp_path, HOME)
    monkeypatch.chdir(tmp_path)
    plans = []
    monkeypatch.setattr(cli, "_start", lambda args, cfg, plan, **kw: plans.append(plan))
    cli.main(["infer", "--plain", "--seconds", "1", "--home"])
    cli.main(["infer", "--plain", "--seconds", "1"])
    assert [p.home for p in plans] == [True, False]


@pytest.mark.skipif(shutil.which("dora") is None, reason="needs dora")
def test_the_policy_moves_home_then_infers_from_there(tmp_path):
    from roboloom.runtime.session import Session

    path = _project(tmp_path, HOME)
    with Session.launch(
        path, options=["policy"], log_dir=tmp_path / "logs", screen=False
    ) as s:
        s.wait_ready(30)
        s.home()
        robot = s.status()["follower"]["fields"]
        assert robot["home"] == "ready" and robot["home_state"] == "reached"
        assert robot["home_diff"] <= 30
        result = s.record("from home", 1.0, home=True)
    assert result.saved and result.frames > 5
