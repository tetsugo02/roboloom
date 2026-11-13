"""Teleoperation of a policy (`teleop:`): before an episode, interventions during one,
taking the joints over one by one (`JointPickup`), and `action.intervention`."""

from __future__ import annotations

import shutil
import time

import numpy as np
import pytest
import yaml
from conftest import mock_project

from roboloom.config import load_config
from roboloom.control.takeover import JointPickup
from roboloom.controllers.base import FollowerView
from roboloom.core.protocol import Envelope
from roboloom.errors import ConfigError
from roboloom.runtime.node import teleop_warning

OPTIONS = ["policy", "policy_teleop"]

# -- JointPickup -------------------------------------------------------------------


def test_joints_are_caught_within_tolerance_or_by_crossing():
    pickup = JointPickup([100.0, 200.0, 300.0], tolerance=10)
    out = pickup.apply([105.0, 150.0, 400.0])  # only joint 0 is close enough
    assert out == [105.0, 200.0, 300.0]
    assert pickup.caught == [True, False, False]
    assert pickup.remaining == [0.0, -50.0, 100.0]
    out = pickup.apply([110.0, 260.0, 380.0])  # joint 1 crossed its held value
    assert out == [110.0, 260.0, 300.0] and pickup.caught == [True, True, False]
    assert not pickup.done
    pickup.apply([110.0, 260.0, 305.0])
    assert pickup.done


def test_a_closed_gripper_holds_until_the_trigger_reaches_it():
    pickup = JointPickup([1500.0], tolerance=30)  # gripper closed on an object
    for trigger in (2048.0, 1900.0, 1700.0):  # trigger released: open
        assert pickup.apply([trigger]) == [1500.0]  # stays closed
    assert pickup.apply([1520.0]) == [1520.0]  # squeezed to it: follows


# -- configuration -----------------------------------------------------------------


def _project(tmp_path, **policy):
    project = mock_project(tmp_path / ".roboloom")
    path = project / "nodes" / "policy_teleop.yaml"
    node = yaml.safe_load(path.read_text())
    node.update(policy, observe=[])
    path.write_text(yaml.safe_dump(node))
    return project / "config.yaml"


def test_the_rakuda2_option_adds_the_leader_and_its_controller(tmp_path):
    cfg = load_config(_project(tmp_path), options=OPTIONS)
    policy = cfg.controllers["policy"]
    assert list(cfg.controllers) == ["policy"]  # one controller per follower
    assert list(policy.teleop) == ["controller"]
    assert policy.teleop_inputs() == ["leader"] and policy.observes() == []
    assert cfg.repo_id.endswith("-eval-teleop")
    from roboloom.recording.schema import features

    assert "action.intervention" in features(cfg)
    assert "action.intervention" not in features(
        load_config(_project(tmp_path / "plain"), options=["policy"])
    )


def test_teleop_needs_its_input(tmp_path):
    path = _project(tmp_path)
    config = path.parent / "config.yaml"
    tree = yaml.safe_load(config.read_text())
    del tree["options"]["policy_teleop"]["set"]["inputs.leader"]
    config.write_text(yaml.safe_dump(tree))
    with pytest.raises(ConfigError, match="must follow a configured input"):
        load_config(path, options=OPTIONS)


def test_teleop_controllers_must_take_over_and_cover_every_follower(tmp_path):
    from roboloom.controllers.joint import JointController

    cfg = load_config(_project(tmp_path), options=OPTIONS)
    policy, inner = cfg.controllers["policy"], cfg.controllers["policy"].teleop

    class NoTakeover(JointController):
        begin_takeover = None  # type: ignore[assignment]

    no_takeover = object.__new__(NoTakeover)
    no_takeover.__dict__.update(inner["controller"].__dict__)
    with pytest.raises(ConfigError, match="cannot take over"):
        policy.bind_teleop({"other": no_takeover})
    with pytest.raises(ConfigError, match="no teleop controller drives follower"):
        policy.bind_teleop({})
    with pytest.raises(ConfigError, match="driven by both"):
        policy.bind_teleop({"a": inner["controller"], "b": inner["controller"]})


# -- arbitration -------------------------------------------------------------------


class Plus:
    """Each infer moves every joint 4 counts from the state."""

    def __init__(self):
        self.resets = 0

    def reset(self):
        self.resets += 1

    def infer(self, observation):
        return np.asarray(observation["observation.state"], dtype=float) + 4


def _state(t, positions, target=None, mode="ACTIVE"):
    payload = {"positions": positions, "target": target or positions, "mode": mode}
    return Envelope("follower_state", "follower", "boot", 0, t, t, payload)


def _intent(seq, t, positions):
    """A leader sample; `t` None: fresh (stamped now)."""
    t = time.monotonic_ns() if t is None else t
    return Envelope(
        "joint_intent", "leader", "lead", seq, t, t, {"positions": positions}
    )


def test_teleop_then_policy_then_an_intervention_and_back(tmp_path):
    cfg = load_config(_project(tmp_path), options=OPTIONS)
    policy = cfg.controllers["policy"]
    plus = Plus()
    policy.policy, policy.state = plus, "ready"
    joints = cfg.followers["follower"].joint_names
    leader_joints = cfg.inputs["leader"].joint_names
    held = [2048.0] * len(joints)
    held[joints.index("r_arm_grip")] = 1500.0  # the gripper holds an object
    now = time.monotonic_ns() - 10**9  # commands must not be stamped in the future
    policy.observe("follower", _state(now, held))

    policy.begin_teleop()  # before the episode
    assert policy.control == "teleop" and policy.tick(now) == {}
    lead = [2048.0] * len(leader_joints)  # the trigger is released (open)
    sent = policy.teleop_update("leader", _intent(1, None, lead))["follower"]
    target = sent.payload["positions"]
    assert target[joints.index("r_arm_grip")] == 1500.0  # stays closed
    assert sent.payload["intervention"] is True
    assert policy.status()["pickup"] == {"r_arm_grip": 548.0}

    policy.start("task")  # the policy takes over from the held targets
    assert policy.control == "policy" and plus.resets == 1
    assert policy.teleop_update("leader", _intent(2, None, lead)) == {}
    command = policy.tick(now)["follower"]
    assert command.payload["intervention"] is False

    policy.begin_teleop()  # an intervention during the episode
    assert policy.tick(now) == {} and policy.control == "teleop"
    policy.resume_policy()
    assert plus.resets == 2 and policy.control == "policy"
    assert policy.tick(now + 10_000_000)["follower"].payload["intervention"] is False
    policy.stop()
    with pytest.raises(RuntimeError, match="no episode running"):
        policy.resume_policy()


def test_a_latched_follower_ends_teleop(tmp_path):
    cfg = load_config(_project(tmp_path), options=OPTIONS)
    policy = cfg.controllers["policy"]
    now = time.monotonic_ns()
    n = len(cfg.followers["follower"].joint_names)
    policy.observe("follower", _state(now, [2048.0] * n))
    policy.begin_teleop()
    policy.reset()
    assert policy.control == "" and policy.teleop["controller"].pickup is None


def test_joint_controller_takeover_survives_a_stale_input(tmp_path):
    cfg = load_config(_project(tmp_path), options=OPTIONS)
    inner = cfg.controllers["policy"].teleop["controller"]
    n = len(cfg.followers["follower"].joint_names)
    now = time.monotonic_ns()
    view = FollowerView([2048.0] * n, [2048.0] * n, None, "ACTIVE", now)
    inner.begin_takeover({"follower": view})
    stale = _intent(1, now - 10**9, [2048.0] * len(cfg.inputs["leader"].joint_names))
    assert inner.update(stale, {"follower": view}, now) == {}
    assert inner.aligned and inner.pickup is not None  # still taking over


# -- session checks ----------------------------------------------------------------


def _status(t, **fields):
    return {"t_ns": t, "fields": fields}


def test_session_checks_teleop_policy_and_stop_teleop(tmp_path):
    cfg = load_config(_project(tmp_path), options=OPTIONS)
    now = time.monotonic_ns()
    idle = {
        "recorder": _status(now, state="idle"),
        "policy": _status(now, control="hold"),
    }
    assert teleop_warning(cfg, "teleop", idle, now) is None
    assert "no episode running" in teleop_warning(cfg, "policy", idle, now)
    assert teleop_warning(cfg, "stop_teleop", idle, now) is None
    recording = {
        "recorder": _status(now, state="recording"),
        "policy": _status(now, control="policy"),
    }
    assert "already driving" in teleop_warning(cfg, "policy", recording, now)
    assert "use stop" in teleop_warning(cfg, "stop_teleop", recording, now)
    recording["policy"] = _status(now, control="teleop")
    assert teleop_warning(cfg, "policy", recording, now) is None
    latched = {**idle, "follower": _status(now, mode="ESTOP")}
    assert "ESTOP" in teleop_warning(cfg, "teleop", latched, now)
    homing = {**idle, "follower": _status(now, home_state="moving")}
    assert "moving home" in teleop_warning(cfg, "teleop", homing, now)
    plain = load_config(_project(tmp_path / "plain"), options=["policy"])
    assert "no teleoperation" in teleop_warning(plain, "teleop", idle, now)


def test_operations_say_when_they_can_be_used():
    from roboloom.ui.backend import SessionBackend
    from roboloom.ui.models import Capabilities

    backend = SessionBackend(lambda: None)  # type: ignore[arg-type,return-value]
    caps = Capabilities(teleop=True)
    assert backend._teleop_operations(Capabilities(), None, "") == ()
    ops = {o.command: o for o in backend._teleop_operations(caps, "hold", "")}
    assert ops["teleop"].enabled and not ops["policy"].enabled
    assert "only during an episode" in ops["policy"].reason
    assert "not teleoperating" in ops["stop_teleop"].reason
    backend._episode = backend._recording = True
    ops = {o.command: o for o in backend._teleop_operations(caps, "teleop", "busy")}
    assert ops["policy"].enabled and not ops["teleop"].enabled
    assert not ops["stop_teleop"].enabled


# -- the dataflow ------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("dora") is None, reason="needs dora")
def test_teleop_before_and_during_an_episode_is_recorded(tmp_path):
    import pandas as pd

    from roboloom.runtime.session import Session

    path = _project(tmp_path)
    with Session.launch(
        path, options=OPTIONS, log_dir=tmp_path / "logs", screen=False
    ) as s:
        s.wait_ready(30)
        s.teleop()  # before the episode: the follower follows, nothing is recorded
        time.sleep(0.5)
        fields = s.status()
        assert fields["follower"]["fields"]["armed"]
        assert fields["policy"]["fields"]["control"] == "teleop"
        s.start("handover")  # the policy takes over
        time.sleep(1.0)
        s.teleop()  # an intervention
        time.sleep(1.0)
        s.policy()  # and back
        time.sleep(1.0)
        s.stop()
        result = s.save()
        output = s.cfg.output
    assert result.saved
    frames = pd.concat(
        pd.read_parquet(p)
        for p in sorted((tmp_path / output).rglob("*.parquet"))
        if "data" in p.parts
    )
    flags = np.asarray(frames["action.intervention"].tolist()).reshape(-1).astype(int)
    # policy, then a person, then the policy again
    # (the first row or two may still carry the teleop command the follower was
    # executing when start arrived: a person drove it)
    lead = int(np.argmin(flags)) if flags[0] else 0
    assert lead <= 2, flags
    rest = flags[lead:]
    changes = [int(v) for k, v in enumerate(rest) if k == 0 or v != rest[k - 1]]
    assert changes == [0, 1, 0], flags
