"""Parts of a follower, and several inputs driving one follower (`type: parts`)."""

from __future__ import annotations

import pytest
import yaml
from conftest import mock_project

from roboloom.config import load_config
from roboloom.controllers.base import FollowerView
from roboloom.core.protocol import Envelope
from roboloom.runtime.flow import build_flow

JOINT = {
    "type": "joint",
    "input": "leader",
    "alignment_tolerance": 300,
    "max_speed": 2048,
    "command_deadline_ms": 100,
    "input_timeout_ms": 150,
}


def _project(tmp_path, parts: dict[str, dict], **extra):
    """The Rakuda2 mock with its controller replaced by a parts controller."""
    project = mock_project(tmp_path / ".roboloom")
    nodes = project / "nodes"
    for name, node in parts.items():
        (nodes / f"{name}.yaml").write_text(yaml.safe_dump(node))
    (nodes / "controller.yaml").write_text(
        yaml.safe_dump(
            {
                "type": "parts",
                "followers": ["follower"],
                "command_deadline_ms": 100,
                "parts": [f"{name}.yaml" for name in parts],
                **extra,
            }
        )
    )
    return project / "config.yaml"


def _arms(tmp_path):
    return _project(
        tmp_path,
        {
            "right": {**JOINT, "followers": ["follower.right_arm"]},
            "right_grip": {**JOINT, "followers": ["follower.right_gripper"]},
            "left": {**JOINT, "followers": ["follower.left_arm"]},
        },
    )


def test_a_follower_names_its_parts():
    from conftest import rakuda2_tree

    from roboloom.config import parse_config

    tree = rakuda2_tree()
    tree["followers"]["follower"]["parts"] = {"neck": ["head_yaw", "head_pitch"]}
    follower = parse_config(tree).followers["follower"]
    parts = follower.parts()
    assert list(parts) == [
        "body",
        "right_arm",
        "right_gripper",
        "left_arm",
        "left_gripper",
        "neck",
    ]
    assert sum(len(parts[p]) for p in list(parts)[:5]) == 17
    arm = follower.part("right_arm")
    assert arm.name == "follower.right_arm" and arm.unit == follower.unit
    assert arm.joint_names == parts["right_arm"] and len(arm.limits) == 6
    assert [limit["name"] for limit in arm.limits] == list(arm.joint_names)
    with pytest.raises(ValueError, match="no part 'tail'"):
        follower.part("tail")
    tree["followers"]["follower"]["parts"] = {"bad": ["elbow"]}
    with pytest.raises(ValueError, match="unknown joints"):
        parse_config(tree)


def _leader(t_ns: int, positions: list[float], seq: int) -> Envelope:
    payload = {"positions": positions, "unit": "dynamixel_count"}
    return Envelope("joint_intent", "leader", "boot", seq, t_ns, t_ns, payload)


def test_each_part_follows_its_input_and_the_rest_holds(tmp_path):
    cfg = load_config(_arms(tmp_path))
    controller = cfg.controllers["controller"]
    follower = cfg.followers["follower"]
    names = list(follower.joint_names)
    held = [2048.0] * 17
    view = FollowerView(held, held, None, "ACTIVE", 0)
    leader = [2100.0] * 17
    t = 1_000_000_000
    out = controller.update_from("leader", _leader(t, leader, 1), {"follower": view}, t)
    sent = out["follower"].payload["positions"]
    assert out["follower"].payload["follower"] == "follower" and len(sent) == 17
    moved = {n for n, x in zip(names, sent, strict=True) if x != 2048.0}
    driven = {
        *follower.parts()["right_arm"],
        "r_arm_grip",
        *follower.parts()["left_arm"],
    }
    assert moved == driven  # torso, head and the left gripper stay where they are held
    assert controller.status()["state"] == "following"
    assert set(controller.status()["parts"]) == {"right", "right_grip", "left"}
    assert controller.intent_inputs() == ["leader"]

    controller.reset()  # a latched follower: every part re-aligns
    far = FollowerView([1000.0] * 17, [1000.0] * 17, None, "ACTIVE", 0)
    t += 10_000_000
    assert (
        controller.update_from("leader", _leader(t, leader, 2), {"follower": far}, t)
        == {}
    )
    assert "aligning" in controller.status()["state"]


def test_parts_are_checked_at_load(tmp_path):
    with pytest.raises(ValueError, match="driven by both"):
        load_config(
            _project(
                tmp_path / "a",
                {
                    "one": {**JOINT, "followers": ["follower.right_arm"]},
                    "two": {**JOINT, "followers": ["follower.right_arm"]},
                },
            )
        )
    with pytest.raises(Exception, match="parts of follower"):
        load_config(
            _project(tmp_path / "b", {"one": {**JOINT, "followers": ["follower"]}})
        )
    with pytest.raises(ValueError, match="no part 'tail'"):
        load_config(
            _project(tmp_path / "c", {"one": {**JOINT, "followers": ["follower.tail"]}})
        )
    with pytest.raises(Exception, match="configured input"):
        load_config(
            _project(
                tmp_path / "d",
                {"one": {**JOINT, "input": "nobody", "followers": ["follower.body"]}},
            )
        )
    with pytest.raises(Exception, match="list of controller YAML paths"):
        load_config(_project(tmp_path / "e", {}))


def test_the_flow_gives_the_follower_one_command_source(tmp_path):
    cfg = load_config(_arms(tmp_path))
    flow = build_flow(cfg)
    nodes = {n["id"]: n for n in flow["nodes"]}
    assert nodes["controller"]["inputs"]["intent_leader"] == "leader/sample"
    assert "intent" not in nodes["controller"]["inputs"]
    command = nodes["follower"]["inputs"]["command"]
    source = command["source"] if isinstance(command, dict) else command
    assert source.startswith("controller/")


def test_a_parts_controller_teleoperates_in_the_dataflow(tmp_path):
    from roboloom.runtime.session import Session

    with Session.launch(_arms(tmp_path), log_dir=tmp_path / "logs") as s:
        s.wait_ready(60)
        result = s.record("pick", 2.0)
        fields = s.status()["controller"]["fields"]
    assert result.saved and result.metrics["action_valid_rate"] > 0.5, result.metrics
    assert fields["state"] == "following" and fields["command_hz"] > 50, fields


def test_a_part_whose_input_stopped_is_not_commanded_again(tmp_path):
    """Another input's updates must not renew a part's old target: the follower may
    have been short of it (speed-limited), and would keep moving without an input."""
    path = _project(
        tmp_path,
        {
            "right": {**JOINT, "followers": ["follower.right_arm"]},
            "left": {**JOINT, "input": "other", "followers": ["follower.left_arm"]},
        },
    )
    node = yaml.safe_load((path.parent / "nodes" / "leader.yaml").read_text())
    node["port"] = str(node["port"]) + "-other"
    (path.parent / "nodes" / "other.yaml").write_text(yaml.safe_dump(node))
    config = yaml.safe_load(path.read_text())
    config["inputs"]["other"] = "nodes/other.yaml"
    path.write_text(yaml.safe_dump(config))
    recorder = path.parent / "nodes" / "recorder.yaml"
    settings = yaml.safe_load(recorder.read_text())
    settings["max_age_ms"]["other"] = settings["max_age_ms"]["leader"]
    recorder.write_text(yaml.safe_dump(settings))
    cfg = load_config(path)
    controller = cfg.controllers["controller"]
    follower = cfg.followers["follower"]
    right = [follower.joint_names.index(j) for j in follower.parts()["right_arm"]]
    left = [follower.joint_names.index(j) for j in follower.parts()["left_arm"]]
    held = [2048.0] * 17
    view = {"follower": FollowerView(held, held, None, "ACTIVE", 0)}
    t = 1_000_000_000

    def intent(source: str, seq: int, at: int) -> Envelope:
        payload = {"positions": [2100.0] * 17, "unit": "dynamixel_count"}
        return Envelope("joint_intent", source, "boot", seq, at, at, payload)

    out = controller.update_from("leader", intent("leader", 1, t), view, t)
    assert all(out["follower"].payload["positions"][i] != 2048.0 for i in right)
    # 50 ms later the other input moves the left arm: the right target is still valid
    t += 50_000_000
    sent = controller.update_from("other", intent("other", 1, t), view, t)[
        "follower"
    ].payload["positions"]
    assert all(sent[i] != 2048.0 for i in right + left)
    # the right input is silent past its deadline: the right arm gets what is held
    t += 100_000_000
    sent = controller.update_from("other", intent("other", 2, t), view, t)[
        "follower"
    ].payload["positions"]
    assert [sent[i] for i in right] == [2048.0] * len(right)
    assert all(sent[i] != 2048.0 for i in left)
