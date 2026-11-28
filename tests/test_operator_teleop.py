"""Operator teleop outside an episode and its interaction with recording."""

from __future__ import annotations

import time
from collections.abc import Mapping

import pytest
from conftest import make_fake_session, mock_project
from test_operator_backends import FakeSession, Notices
from test_parts import _arms
from test_pose_ik import CONFIG as POSE_IK_CONFIG

from roboloom.config import load_config
from roboloom.controllers.base import Controller, FollowerView
from roboloom.controllers.teleop import TeleopMode, teleop_mode
from roboloom.core.protocol import Envelope
from roboloom.recording.schema import records_intervention
from roboloom.runtime.node import home_warning, teleop_warning
from roboloom.runtime.session import Session, SessionError
from roboloom.ui.backend import RecordingPlan, SessionBackend
from roboloom.ui.models import Capabilities, Snapshot


class OperatorController(Controller):
    def update(
        self,
        intent: Envelope,
        views: Mapping[str, FollowerView],
        now_ns: int | None = None,
    ) -> dict[str, Envelope]:
        return {}

    def reset(self) -> None:
        pass


class EpisodeOnlyController(OperatorController):
    def follows_operator(self) -> bool:
        return False


def _config(tmp_path, options=None):
    path = mock_project(tmp_path / ".roboloom") / "config.yaml"
    return load_config(path) if options is None else load_config(path, options=options)


def _status(t, **fields):
    return {"t_ns": t, "fields": fields}


def _latest(now, *, recorder="idle", armed=False, **controller):
    fields = {"state": "following", "worst_joint": "r_arm_el_yaw", "worst_diff": 3}
    fields.update(tolerance=300, **controller)
    return {
        "recorder": _status(now, state=recorder),
        "controller": _status(now, **fields),
        "follower": _status(now, mode="ACTIVE" if armed else "HOLD", armed=armed),
    }


def test_joint_and_parts_controllers_support_operator_teleop(tmp_path):
    for cfg in (_config(tmp_path / "joint"), load_config(_arms(tmp_path / "parts"))):
        assert teleop_mode(cfg.controllers) == TeleopMode(policy=None)
        assert not records_intervention(cfg)


def test_pose_ik_controllers_support_operator_teleop():
    cfg = load_config(POSE_IK_CONFIG)
    assert teleop_mode(cfg.controllers) == TeleopMode(policy=None)


@pytest.mark.parametrize(
    ("options", "mode"),
    [
        (["policy"], None),
        (["policy", "policy_teleop"], TeleopMode(policy="policy")),
    ],
)
def test_policy_teleop_selects_handback_and_records_interventions(
    tmp_path, options, mode
):
    cfg = _config(tmp_path, options)
    assert teleop_mode(cfg.controllers) == mode
    assert records_intervention(cfg) == (mode is not None)


def test_custom_controller_can_follow_operator_or_opt_out(tmp_path):
    cfg = _config(tmp_path)
    operator = OperatorController(
        "operator", {"command_deadline_ms": 100}, cfg.inputs["leader"], cfg.followers
    )
    episode_only = EpisodeOnlyController(
        "episode_only", operator.cfg, operator.source, operator.followers
    )
    assert teleop_mode({"operator": operator}) == TeleopMode(policy=None)
    assert teleop_mode({"operator": operator, "episode_only": episode_only}) is None
    assert teleop_mode({}) is None


def test_operator_teleop_needs_readiness_and_no_active_episode(tmp_path):
    cfg = _config(tmp_path)
    now = time.monotonic_ns()
    assert teleop_warning(cfg, "teleop", _latest(now), now) is None
    assert "already teleoperating" in teleop_warning(
        cfg, "teleop", _latest(now, armed=True), now
    )
    assert "already drives" in teleop_warning(
        cfg, "teleop", _latest(now, recorder="recording", armed=True), now
    )
    aligning = _latest(now, state="aligning", worst_diff=900)
    warning = teleop_warning(cfg, "teleop", aligning, now)
    assert "move the leader" in warning and warning.endswith("retry teleop")
    behind = _latest(now, worst_diff=301)
    assert "not at the leader" in teleop_warning(cfg, "teleop", behind, now)
    latched = _latest(now)
    latched["follower"] = _status(now, mode="ESTOP")
    assert "ESTOP" in teleop_warning(cfg, "teleop", latched, now)
    homing = _latest(now)
    homing["follower"] = _status(now, mode="HOMING", home_state="moving")
    assert "moving home" in teleop_warning(cfg, "teleop", homing, now)
    stale = _latest(now - 2_000_000_000)
    assert "no recent controller status" in teleop_warning(cfg, "teleop", stale, now)


def test_stop_teleop_and_policy_in_operator_mode(tmp_path):
    cfg = _config(tmp_path)
    now = time.monotonic_ns()
    assert teleop_warning(cfg, "stop_teleop", _latest(now, armed=True), now) is None
    assert teleop_warning(cfg, "stop_teleop", _latest(now), now) is None
    recording = _latest(now, recorder="recording", armed=True)
    assert (
        teleop_warning(cfg, "stop_teleop", recording, now)
        == "during an episode use stop"
    )
    assert "no policy" in teleop_warning(cfg, "policy", _latest(now), now)


def test_stop_teleop_waits_for_fresh_disarmed_status(tmp_path):
    session = make_fake_session(tmp_path)
    session.client.new_reports.return_value = [{"id": 1, "command": "stop_teleop"}]
    stale = time.monotonic_ns()

    def statuses():
        yield {"nodes": {"follower": _status(stale, armed=True)}}
        yield {"nodes": {"follower": _status(stale, armed=False)}}
        yield {"nodes": {"follower": _status(time.monotonic_ns(), armed=True)}}
        yield {"nodes": {"follower": _status(time.monotonic_ns(), armed=False)}}

    session.client.status.side_effect = statuses()
    session.stop_teleop()
    assert session.client.status.call_count == 4


def test_stop_teleop_times_out_if_follower_stays_armed(tmp_path):
    session = make_fake_session(tmp_path)
    session.client.new_reports.return_value = [{"id": 1, "command": "stop_teleop"}]
    session.client.status.side_effect = lambda: {
        "nodes": {"follower": _status(time.monotonic_ns(), armed=True)}
    }
    with pytest.raises(
        SessionError, match=r"stop_teleop: follower still following after 0\.01 s"
    ):
        session.stop_teleop(timeout=0.01)


def test_home_says_how_to_end_teleoperation(tmp_path):
    cfg = _config(tmp_path)
    for controller in cfg.controllers.values():
        controller.homes = {"follower": object()}  # type: ignore[attr-defined]
    now = time.monotonic_ns()
    assert "stop_teleop" in home_warning(cfg, _latest(now, armed=True), now)


def test_operations_in_operator_mode(tmp_path):
    cfg = _config(tmp_path)
    now = time.monotonic_ns()
    status = _latest(now)
    backend = SessionBackend(lambda: None)  # type: ignore[arg-type,return-value]
    caps = Capabilities(teleop=True)
    ops = {
        o.command: o
        for o in backend._teleop_operations(cfg, caps, None, "", status, now)
    }
    assert list(ops) == ["teleop"]  # single toggle; no Policy without a policy
    assert ops["teleop"].enabled and ops["teleop"].label == "TELEOP: OFF"
    ops = {
        o.command: o
        for o in backend._teleop_operations(cfg, caps, "teleop", "", status, now)
    }
    assert list(ops) == ["stop_teleop"]
    assert ops["stop_teleop"].enabled and ops["stop_teleop"].label == "TELEOP: ON"
    backend._episode = backend._recording = True
    ops = {
        o.command: o
        for o in backend._teleop_operations(cfg, caps, None, "busy", status, now)
    }
    assert "already drives" in ops["teleop"].reason


def test_operator_teleop_waits_for_save_or_discard(tmp_path):
    session = FakeSession(tmp_path)
    plan = RecordingPlan("task", 30, confirm=True)
    backend = SessionBackend(lambda: session, mode="record", recording=plan)
    notices = Notices()
    backend.start(notices)
    try:
        ready = notices.wait_phase("ready: episode 1/1", "start", "teleop")
        assert ready.capabilities.teleop and not ready.capabilities.handback
        backend.submit("start")
        notices.wait(
            lambda n: isinstance(n, Snapshot) and n.phase.startswith("episode 1/1  [")
        )
        backend.submit("stop")
        stopped = notices.wait_phase(
            "stopped: save or discard (episode 1/1)", "save", "discard"
        )
        ops = {o.command: o for o in stopped.operations}
        assert not ops["teleop"].enabled
        assert ops["teleop"].reason == "stopped episode: save or discard first"
        since = len(notices.items)
        backend.submit("discard")
        notices.wait_phase("ready: episode 1/1", "start", "teleop", since=since)
    finally:
        backend.shutdown()


@pytest.mark.e2e
def test_operator_teleop_then_an_episode_in_the_mock_dataflow(tmp_path):
    path = mock_project(tmp_path / ".roboloom") / "config.yaml"
    with Session.launch(path, log_dir=tmp_path / "logs", screen=False) as s:
        s.wait_ready(30)
        s.teleop()  # the follower follows the leader; nothing is recorded
        time.sleep(0.5)
        status = s.status()
        assert status["follower"]["fields"]["armed"]
        assert status["recorder"]["fields"]["state"] == "idle"
        with pytest.raises(SessionError, match="already teleoperating"):
            s.teleop()
        s.stop_teleop()
        assert not s.status()["follower"]["fields"]["armed"]
        s.teleop()
        s.stop_teleop()
        assert not s.status()["follower"]["fields"]["armed"]
        s.teleop()
        time.sleep(0.5)
        s.start("handover")  # recording starts from where teleoperation left it
        time.sleep(1.0)
        s.stop()
        result = s.save(wait=True)
        time.sleep(0.5)
        assert not s.status()["follower"]["fields"]["armed"]
    assert s.process.poll() is not None
    assert result.saved
