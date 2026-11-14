from copy import deepcopy

import pytest
from conftest import TEMPLATE, rakuda2_tree

from roboloom.config import parse_config, read_config
from roboloom.recording import features
from roboloom.runtime.flow import build_flow

PATH = "examples/mock/config.yaml"


def test_validate_rejects_duplicate_devices_and_bad_mapping():
    tree = read_config(PATH)
    duplicate = deepcopy(tree)
    duplicate["sensors"]["digit_right"]["serial"] = duplicate["sensors"]["digit_left"][
        "serial"
    ]
    with pytest.raises(ValueError, match="duplicate"):
        parse_config(duplicate)
    wrong = deepcopy(tree)
    wrong["controllers"]["controller"]["joints"][0]["leader"] = "head_yaw"
    with pytest.raises(ValueError, match="mapping"):
        parse_config(wrong)
    flow = build_flow(parse_config(tree))
    assert len(flow["nodes"]) == 9
    assert (
        next(x for x in flow["nodes"] if x["id"] == "follower")["restart_policy"]
        == "never"
    )


def test_unknown_types_and_dangling_references_fail_before_opening_devices():
    tree = read_config(PATH)
    unknown = deepcopy(tree)
    unknown["sensors"]["camera"]["type"] = "thermal"
    with pytest.raises(ValueError, match="unsupported sensor type"):
        parse_config(unknown)
    dangling = deepcopy(tree)
    dangling["controllers"]["controller"]["input"] = "spacemouse"
    with pytest.raises(ValueError, match="configured input"):
        parse_config(dangling)


def test_sensors_are_selected_by_name_and_type():
    tree = read_config(PATH)
    tree["sensors"]["wrist"] = {**tree["sensors"]["camera"], "serial": "mock-wrist"}
    tree["recorder"]["max_age_ms"]["wrist"] = 300
    cfg = parse_config(tree)
    assert "observation.images.wrist" in features(cfg)
    recorder = next(x for x in build_flow(cfg)["nodes"] if x["id"] == "recorder")
    assert recorder["inputs"]["wrist"]["source"] == "wrist/sample"
    assert recorder["inputs"]["wrist"]["queue_size"] == 5  # 10 fps x 0.5 s
    assert recorder["inputs"]["action_follower"]["queue_policy"] == "drop_oldest"


def filled_hardware_tree():
    return rakuda2_tree(["digit"])


def test_hardware_template_refuses_placeholders_then_parses():
    with pytest.raises(ValueError, match="followers.follower.port: SET_FOLLOWER_PORT"):
        parse_config(read_config(TEMPLATE / "config.yaml"))
    tree = rakuda2_tree()
    tree["followers"]["follower"]["limits"][0]["max"] = "SET_FROM_PROBE"
    with pytest.raises(ValueError, match=r"limits\[0\]\.max: SET_FROM_PROBE"):
        parse_config(tree)
    assert set(parse_config(rakuda2_tree()).sensors) == {"camera"}
    cfg = parse_config(filled_hardware_tree())
    assert not cfg.mock and set(cfg.sensors) == {"camera", "digit_left", "digit_right"}
    assert features(cfg)["observation.images.digit_left"]["shape"] == (320, 240, 3)
    assert "observation.effort" in features(cfg)


def test_register_expectations_are_required():
    tree = filled_hardware_tree()
    del tree["followers"]["follower"]["registers"]["operating_mode"]
    with pytest.raises(ValueError, match="operating_mode"):
        parse_config(tree)
    tree = filled_hardware_tree()
    tree["sensors"]["digit_left"]["height"] = 240
    with pytest.raises(ValueError, match="QVGA"):
        parse_config(tree)


def test_a_policy_is_imported_from_the_robot_directory(tmp_path, monkeypatch):
    import sys

    from roboloom.errors import ConfigError
    from roboloom.policy import load_policy

    (tmp_path / "local_policy_for_test.py").write_text(
        "from roboloom.policy import Hold\n\ndef make():\n    return Hold()\n"
    )
    monkeypatch.setattr(sys, "path", list(sys.path))
    with pytest.raises(ConfigError, match="local_policy_for_test"):
        load_policy("local_policy_for_test:make")
    policy = load_policy("local_policy_for_test:make", search=[str(tmp_path)])
    assert hasattr(policy, "infer")
    assert sys.path[-1] == str(tmp_path)  # after the installed packages


def test_the_node_knows_the_robot_directory():
    from roboloom.config import load_config

    cfg = load_config(".roboloom/piper-mock/config.yaml", options=["policy"])
    policy = cfg.controllers["policy"]
    assert policy.cfg["__robot_dir__"].endswith(".roboloom/piper-mock")
    assert set(cfg.followers) == {"left", "right", "left_gripper", "right_gripper"}


def test_a_leader_shaped_like_the_follower_needs_no_joint_table():
    from conftest import rakuda2_tree

    tree = rakuda2_tree()
    node = tree["controllers"]["controller"]
    assert "joints" not in node and "unit" not in node  # the shipped template
    controller = parse_config(tree).controllers["controller"]
    follower = controller.follower
    assert [j["leader"] for j in controller.mapping] == list(follower.joint_names)
    assert all(j["sign"] == 1 and j["offset"] == 0 for j in controller.mapping)
    pose = [2000.0 + i for i in range(len(follower.joint_names))]
    assert list(controller.leader_pose(pose).values()) == pose

    written = rakuda2_tree()
    written["controllers"]["controller"]["unit"] = "rad"
    with pytest.raises(ValueError, match="unit must match"):
        parse_config(written)
    explicit = rakuda2_tree()
    explicit["controllers"]["controller"]["unit"] = "dynamixel_count"
    explicit["controllers"]["controller"]["joints"] = [
        {"leader": j, "follower": j, "sign": -1 if j == "head_yaw" else 1, "offset": 0}
        for j in follower.joint_names
    ]
    mapped = parse_config(explicit).controllers["controller"].mapping
    assert [j["sign"] for j in mapped if j["leader"] == "head_yaw"] == [-1]


def test_an_input_without_the_followers_joints_needs_the_table():
    from roboloom.controllers.joint import JointController
    from roboloom.inputs.base import JointInput
    from roboloom.robots.base import Follower

    limits = [
        {"name": j, "min": -1, "max": 1, "max_speed": 1, "max_jump": 1}
        for j in ("a", "b")
    ]
    follower = Follower(
        "arm", {"joints": ["a", "b"], "unit": "rad", "control_hz": 50, "limits": limits}
    )

    class Knob(JointInput):
        safety_traits = Follower.safety_traits

    cfg = {
        "alignment_tolerance": 0.1,
        "max_speed": 1.0,
        "command_deadline_ms": 100,
        "input_timeout_ms": 150,
    }
    source = Knob("knob", {"joints": ["a", "wheel"], "unit": "rad"})
    with pytest.raises(ValueError, match=r"has no joints \['b'\]"):
        JointController("c", cfg, source, {"arm": follower})
    table = [
        {"leader": "a", "follower": "a", "sign": 1, "offset": 0},
        {"leader": "wheel", "follower": "b", "sign": 1, "offset": 0.5},
    ]
    controller = JointController(
        "c", {**cfg, "joints": table}, source, {"arm": follower}
    )
    assert controller.leader_pose([0.0, 0.75]) == {"a": 0.0, "wheel": 0.25}
