"""Several followers in one configuration: names, flow, recording, poses."""

import json
import shutil
import time
from pathlib import Path

import numpy as np
import pytest
import yaml
from conftest import dual_mock

from roboloom.config import load_config, parse_config, read_config
from roboloom.core.protocol import Envelope
from roboloom.core.source import Joined
from roboloom.errors import ConfigError
from roboloom.recording import EpisodeRecorder, features
from roboloom.recording.schema import joined_parts
from roboloom.runtime.flow import build_flow
from roboloom.setup import capture_pose

MS = 1_000_000


def test_two_followers_join_state_and_action_in_configuration_order(tmp_path):
    cfg = load_config(dual_mock(tmp_path))
    assert cfg.robot == "dual" and list(cfg.followers) == ["follower", "left"]
    f = features(cfg)
    names = f["action"]["names"]
    assert f["action"]["shape"] == (34,) and len(names) == 34
    assert names[0] == "follower.torso_yaw" and names[17] == "left.torso_yaw"
    assert f["observation.state"]["names"] == names
    for follower in ("follower", "left"):
        assert f[f"action.meta.{follower}.valid"]["shape"] == (1,)
        assert f"observation.meta.{follower}.valid" in f
    assert "action.seq" not in f and "action.sent_ns" not in f
    assert f["observation.leader"]["names"][0] == "torso_yaw"


def test_flow_wires_each_follower_to_its_own_controller_and_recorder_input(tmp_path):
    cfg = load_config(dual_mock(tmp_path))
    nodes = {n["id"]: n for n in build_flow(cfg)["nodes"]}
    left = nodes["left"]["inputs"]["command"]["source"]
    assert left == "left_controller/command_left"
    assert (
        nodes["follower"]["inputs"]["command"]["source"]
        == "controller/command_follower"
    )
    recorder = nodes["recorder"]["inputs"]
    assert recorder["action_left"]["source"] == "left/action"
    assert recorder["action_follower"]["source"] == "follower/action"
    assert nodes["left_controller"]["inputs"]["state_left"] == "left/state"
    assert nodes["left_controller"]["outputs"][0] == "command_left"
    # an input without a rate of its own runs at its follower's control rate
    assert nodes["left_leader"]["inputs"]["tick"].endswith(
        f"/{int(cfg.followers['left'].control_hz)}"
    )


@pytest.mark.parametrize("name", ["action_left", "left_status", "recorder", "tick"])
def test_node_names_that_collide_with_dataflow_ids_are_refused(tmp_path, name):
    tree = read_config(dual_mock(tmp_path))
    tree["followers"][name] = tree["followers"].pop("left")
    with pytest.raises(ValueError, match="invalid node name"):
        parse_config(tree)


def test_unknown_and_removed_top_level_keys_are_refused(tmp_path):
    path = dual_mock(tmp_path)
    text = path.read_text()
    path.write_text("robot_id: dual\n" + text)
    with pytest.raises(
        ConfigError, match="robot_id: the robot's name is its directory"
    ):
        read_config(path)
    path.write_text("colour: red\n" + text)
    with pytest.raises(ConfigError, match=r"unknown keys \['colour'\]"):
        read_config(path)
    path.write_text(text.replace("followers:", "robots:", 1))
    with pytest.raises(ConfigError, match="robots: renamed to followers"):
        read_config(path)


def test_controller_and_estimator_keys_name_followers(tmp_path):
    tree = read_config(dual_mock(tmp_path))
    controller = tree["controllers"]["left_controller"]
    controller["robot"] = controller.pop("followers")[0]
    with pytest.raises(ConfigError, match="use followers"):
        parse_config(tree)


def msg(kind, seq, t, payload, source):
    return Envelope(kind, source, "boot", seq, t, t, payload, t_receive_ns=t)


def test_a_silent_follower_fills_its_action_with_the_target_it_held(tmp_path):
    cfg = load_config(dual_mock(tmp_path))
    recorder = EpisodeRecorder(cfg)
    t = time.monotonic_ns()
    recorder.start("two arms", t, write=False)
    for name, value in (("follower", 2000), ("left", 1000)):
        recorder.ingest(
            name,
            msg(
                "follower_state",
                0,
                t - MS,
                {"positions": [value] * 17, "target": [value + 1] * 17},
                name,
            ),
        )
    sent = t + 20 * MS
    recorder.ingest(
        "action_follower",
        msg(
            "action",
            1,
            sent,
            {
                "valid": True,
                "clamped": True,
                "positions": [2050] * 17,
                "command_seq": 7,
                "t_sent_ns": sent,
            },
            "follower",
        ),
    )
    recorder.stop(t + 100 * MS)
    row = recorder.frames()[0]
    assert row["observation.state"][0] == 2000 and row["observation.state"][17] == 1000
    assert row["action"][0] == 2050 and row["action"][17] == 1001  # left held 1001
    assert row["action.valid"][0] == 0 and row["action.clamped"][0] == 1
    assert row["action.meta.follower.valid"][0] == 1
    assert row["action.meta.follower.seq"][0] == 7
    assert (
        row["action.meta.left.valid"][0] == 0 and row["action.meta.left.seq"][0] == -1
    )


def test_rows_wait_for_the_slowest_follower_then_for_grace(tmp_path):
    cfg = load_config(dual_mock(tmp_path))

    class Rows:
        def __init__(self):
            self.frames = []

        def add_frame(self, row):
            self.frames.append(row)

    dataset = Rows()
    recorder = EpisodeRecorder(cfg, dataset, grace_ms=500)
    t = time.monotonic_ns()
    recorder.start("two arms", t)
    late = t + 250 * MS  # the follower's stream has passed two rows (10 fps)
    recorder.ingest(
        "action_follower", msg("action", 1, late, {"valid": False}, "follower")
    )
    assert recorder.poll(late) == 0  # left has not passed row 0 yet
    recorder.ingest("action_left", msg("action", 1, late, {"valid": False}, "left"))
    assert recorder.poll(late) == 2
    assert (
        recorder.poll(t + 1000 * MS) > 0
    )  # silent streams: rows still come after grace


def test_parts_of_one_feature_must_share_their_unit():
    class Part:
        def __init__(self, unit):
            self.unit = unit

        def joined(self, fps):
            return {"observation.effort": Joined(("j",), unit=self.unit)}

    joined_parts({"a": Part("mA"), "b": Part("mA")}, 10)
    with pytest.raises(ValueError, match="cannot mix units"):
        joined_parts({"a": Part("mA"), "b": Part("N m")}, 10)


def test_capture_pose_needs_the_follower_when_there_are_several(tmp_path):
    path = dual_mock(tmp_path)
    with pytest.raises(ConfigError, match="name the follower"):
        capture_pose(path, "ready")
    saved = capture_pose(path, "ready", follower="left")
    assert saved == path.parent / "poses" / "left" / "ready.yaml"
    assert yaml.safe_load(saved.read_text())["follower"] == "left"
    with pytest.raises(ConfigError, match="no follower"):
        capture_pose(path, "ready", follower="right")


@pytest.mark.skipif(shutil.which("dora") is None, reason="needs dora")
def test_two_followers_record_one_episode_in_mock(tmp_path):
    from roboloom.runtime.session import Session

    path = dual_mock(tmp_path)
    with Session.launch(path, log_dir=tmp_path / "logs") as s:
        s.wait_ready(30)
        result = s.record("two arms", 1.0)
    assert result.saved and result.frames > 5, result
    assert set(result.metrics["action_missing_rate"]) == {"follower", "left"}
    info = json.loads((Path(path.parent) / "datasets/dual/meta/info.json").read_text())
    action = info["features"]["action"]
    assert action["shape"] == [34] and action["names"][17] == "left.torso_yaw"
    assert info["robot_type"] == "dual"
    assert np.isfinite(result.metrics["action_valid_rate"])


# -- one controller, several followers ------------------------------------------


def policy_tree(tmp_path: Path) -> dict:
    """The dual mock driven by one policy controller for both followers (no leaders)."""
    tree = read_config(dual_mock(tmp_path))
    tree["inputs"] = {}
    tree["controllers"] = {
        "policy": {
            "type": "policy",
            "followers": ["follower", "left"],
            "factory": "policies:creep",
            "observe": ["camera"],
            "rate_hz": 10,
            "action_horizon": 2,
            "max_speed": {"follower": 50, "left": 50},
            "command_deadline_ms": 300,
        }
    }
    for name in ("leader", "left_leader"):
        del tree["recorder"]["max_age_ms"][name]
    return tree


def follower_state(name: str, positions: list[float], mode: str = "HOLD") -> Envelope:
    t = time.monotonic_ns()
    payload = {"positions": positions, "target": positions, "mode": mode}
    return Envelope("follower_state", name, "boot", 0, t, t, payload)


def test_a_policy_splits_its_action_over_the_followers_in_order(tmp_path):
    from roboloom.controllers.policy import PolicyController

    cfg = parse_config(policy_tree(tmp_path))
    policy = cfg.controllers["policy"]
    assert isinstance(policy, PolicyController)
    policy.load("policies:creep", {"step": 1000.0, "horizon": 1})
    policy.observe("follower", follower_state("follower", [2000.0] * 17))
    policy.observe("left", follower_state("left", [1000.0] * 17))
    t = time.monotonic_ns()
    camera = cfg.sensors["camera"]
    policy.observe(
        "camera",
        Envelope(
            "image",
            "camera",
            "boot",
            0,
            t,
            t,
            camera.encode(camera.open(True, 10).read()),
        ),
    )
    policy.start("creep")
    commands = policy.tick()
    assert set(commands) == {"follower", "left"}
    first, left = commands["follower"].payload, commands["left"].payload
    assert first["follower"] == "follower" and left["follower"] == "left"
    # the first entry moved +1000; the speed limit (50/s at 10 Hz) keeps it to +5
    assert first["positions"][0] == pytest.approx(2005.0)
    assert left["positions"] == [1000.0] * 17  # left's part of the action: unchanged


def test_a_latched_follower_stops_the_whole_policy(tmp_path):
    cfg = parse_config(policy_tree(tmp_path))
    policy = cfg.controllers["policy"]
    policy.load("policies:creep", {})
    policy.observe("follower", follower_state("follower", [2000.0] * 17))
    policy.observe("left", follower_state("left", [1000.0] * 17, mode="FAULT"))
    policy.start("creep")
    assert policy.tick() == {}


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda t: t["controllers"]["policy"].update(followers=["left", "follower"]),
            "in configuration order",
        ),
        (
            lambda t: t["controllers"]["policy"].update(followers=["follower"]),
            "a policy drives every follower",
        ),
        (
            lambda t: t["controllers"]["policy"].update(followers=["follower", "x"]),
            "unknown: x",
        ),
    ],
)
def test_policy_followers_are_checked(tmp_path, change, message):
    tree = policy_tree(tmp_path)
    change(tree)
    with pytest.raises(ValueError, match=message):
        parse_config(tree)


def test_each_follower_has_exactly_one_controller_and_joint_controllers_one_follower(
    tmp_path,
):
    tree = read_config(dual_mock(tmp_path))
    tree["controllers"]["controller"]["followers"] = ["follower", "left"]
    with pytest.raises(ValueError, match="drives 1 follower"):
        parse_config(tree)
    tree = read_config(dual_mock(tmp_path / "b"))
    tree["controllers"]["left_controller"]["followers"] = ["follower"]
    with pytest.raises(ValueError, match="'follower' needs exactly one controller"):
        parse_config(tree)


class Recorder:
    """A two-follower controller that records what the node loop asks of it."""

    def __init__(self, controller):
        self.inner = controller
        self.updates = 0
        self.resets = 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def update(self, intent, views, now_ns=None):
        self.updates += 1
        return {
            name: self.inner.command(name, v.positions, time.monotonic_ns())
            for name, v in views.items()
        }

    def reset(self):
        self.resets += 1

    def status(self):
        return {"state": "following"}


def run_controller(monkeypatch, controller, events) -> list[str]:
    """Feed `events` (event id, message or None) to the controller node; the outputs sent."""
    from roboloom.runtime import node as runtime

    quit = Envelope("session", "session", "b", 0, 0, 0, {"command": "quit"})
    queue = iter([*events, ("session", quit)])

    def event(node):
        item = next(queue)
        return item() if callable(item) else item  # a callable: evaluated when due

    monkeypatch.setattr(runtime, "_event", event)
    sent: list[str] = []

    class Node:
        def send_output(self, output, value):
            sent.append(output)

    runtime._controller(Node(), controller)
    return [s for s in sent if s != "status"]


def test_one_latched_follower_stops_commands_to_the_whole_group(tmp_path, monkeypatch):
    cfg = parse_config(policy_tree(tmp_path))
    controller = Recorder(cfg.controllers["policy"])
    intent = Envelope("joint_intent", "leader", "b", 0, 0, 0, {})
    ok = follower_state("follower", [2000.0] * 17)
    sent = run_controller(
        monkeypatch,
        controller,
        [
            ("intent", intent),  # no follower state yet: nothing moves
            ("state_follower", ok),
            ("intent", intent),  # left has not reported: nothing moves
            ("state_left", follower_state("left", [1000.0] * 17, mode="FAULT")),
            ("intent", intent),
        ],
    )
    assert controller.resets == 1
    # update ran once both had reported; the controller (not the loop) then decides; a
    # real controller sends nothing after reset until it has re-aligned
    assert sent == ["command_follower", "command_left"] and controller.updates == 1


def test_a_silent_follower_resets_the_group(tmp_path, monkeypatch):
    cfg = parse_config(policy_tree(tmp_path))
    cfg.controllers["policy"].cfg["follower_timeout_ms"] = 1
    controller = Recorder(cfg.controllers["policy"])
    intent = Envelope("joint_intent", "leader", "b", 0, 0, 0, {})

    events = [
        ("state_follower", follower_state("follower", [1000.0] * 17)),
        ("state_left", follower_state("left", [1000.0] * 17)),
    ]
    from roboloom.runtime import node as runtime

    real = runtime.time.monotonic_ns
    offset = {"ns": 0}
    monkeypatch.setattr(runtime.time, "monotonic_ns", lambda: real() + offset["ns"])

    def later():
        offset["ns"] = 10_000_000  # 10 ms later: both states older than 1 ms
        return ("intent", intent)

    sent = run_controller(monkeypatch, controller, [*events, later])
    assert controller.resets == 1 and controller.updates == 0 and sent == []


@pytest.mark.skipif(shutil.which("dora") is None, reason="needs dora")
def test_one_policy_drives_two_followers_in_mock(tmp_path, monkeypatch):
    import os

    from roboloom.runtime.session import Session

    tests = str(Path(__file__).parent.resolve())
    monkeypatch.setenv(
        "PYTHONPATH", os.pathsep.join([tests, os.environ.get("PYTHONPATH", "")])
    )
    path = dual_mock(tmp_path)
    tree = policy_tree(tmp_path / "unused")
    (path.parent / "nodes" / "policy.yaml").write_text(
        yaml.safe_dump(tree["controllers"]["policy"])
    )
    recorder = yaml.safe_load((path.parent / "nodes" / "recorder.yaml").read_text())
    for name in ("leader", "left_leader"):
        del recorder["max_age_ms"][name]
    (path.parent / "nodes" / "recorder.yaml").write_text(yaml.safe_dump(recorder))
    config = yaml.safe_load(path.read_text())
    config["inputs"] = {}
    config["controllers"] = {"policy": "nodes/policy.yaml"}
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    with Session.launch(
        path, policy_kwargs={"step": 5.0}, log_dir=tmp_path / "logs"
    ) as s:
        s.wait_ready(30)
        result = s.record("creep", 1.5)
    assert result.saved, result
    assert result.metrics["action_valid_rate"] > 0.5, result.metrics
    assert max(result.metrics["action_missing_rate"].values()) < 0.5, result.metrics


# -- units ----------------------------------------------------------------------


def test_followers_and_inputs_declare_their_unit():
    from roboloom.inputs.base import JointInput
    from roboloom.robots.base import Follower
    from roboloom.robots.safety import FollowerSafety

    limits = [{"name": "a", "min": 0, "max": 1, "max_speed": 1, "max_jump": 1}]
    with pytest.raises(ValueError, match="declare the unit"):
        Follower("arm", {"limits": limits, "control_hz": 30}, ["a"])
    assert (
        Follower("arm", {"limits": limits, "control_hz": 30, "unit": "rad"}, ["a"]).unit
        == "rad"
    )
    with pytest.raises(ValueError, match="declare the unit"):
        JointInput("leader", {}, ["a"])
    with pytest.raises(ValueError, match="unit"):
        FollowerSafety({"name": "arm", "limits": limits}, None)


def test_count_specific_keys_were_renamed(tmp_path):
    tree = read_config(dual_mock(tmp_path))
    controller = tree["controllers"]["left_controller"]
    controller["max_speed_counts_per_s"] = controller.pop("max_speed")
    with pytest.raises(ConfigError, match="renamed: use max_speed"):
        parse_config(tree)
    tree = policy_tree(tmp_path / "p")
    tree["controllers"]["policy"]["max_speed"] = 50
    with pytest.raises(ValueError, match="one value per follower"):
        parse_config(tree)
