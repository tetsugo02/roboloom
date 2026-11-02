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
    assert nodes["left"]["inputs"]["command"]["source"] == "left_controller/command"
    assert nodes["follower"]["inputs"]["command"]["source"] == "controller/command"
    recorder = nodes["recorder"]["inputs"]
    assert recorder["action_left"]["source"] == "left/action"
    assert recorder["action_follower"]["source"] == "follower/action"
    assert nodes["left_controller"]["inputs"]["follower"] == "left/state"
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
