"""Node files built on another (`extends:`): the base says what is shared, the file
that extends it only what differs."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from conftest import mock_project

from roboloom.config import load_config, overlay, read_node
from roboloom.errors import ConfigError
from roboloom.recording.manifest import snapshot


def _write(directory: Path, **files: str) -> None:
    for name, text in files.items():
        (directory / f"{name}.yaml").write_text(text)


BASE = """\
type: rakuda_mini
port: /dev/leader
registers:
  operating_mode: {default: 3, grip: 5}
  current_limit: {grip: 30}
control:
- group: body
  law: free
  joints: [torso, head]
- group: arm
  law: free
  joints: [a, b]
tags: [one, two]
"""


def test_a_file_says_only_what_differs_from_the_one_it_extends(tmp_path):
    _write(
        tmp_path,
        leader=BASE,
        gravity="""\
extends: leader.yaml
without: [registers.operating_mode]
registers:
  current_limit: {a: 150}
control:
- group: arm
  law: gravity_comp
  kd: 0.0
- group: wrist
  law: free
  joints: [c]
tags: [three]
bus_watchdog_ms: 500
""",
        locked="""\
extends: gravity.yaml
control:
- group: body
  law: position
""",
    )
    node = read_node(tmp_path / "gravity.yaml")
    assert node["port"] == "/dev/leader" and node["bus_watchdog_ms"] == 500
    assert node["registers"] == {"current_limit": {"grip": 30, "a": 150}}
    assert node["control"] == [
        {"group": "body", "law": "free", "joints": ["torso", "head"]},
        {"group": "arm", "law": "gravity_comp", "joints": ["a", "b"], "kd": 0.0},
        {"group": "wrist", "law": "free", "joints": ["c"]},  # new ones come last
    ]
    assert node["tags"] == ["three"]  # a plain list is replaced
    assert "extends" not in node and "without" not in node
    assert node["__extends__"] == [str(tmp_path / "leader.yaml")]
    # a chain: nearest base first
    locked = read_node(tmp_path / "locked.yaml")
    assert locked["control"][0]["law"] == "position"
    assert locked["control"][1]["law"] == "gravity_comp"
    assert [Path(p).name for p in locked["__extends__"]] == [
        "gravity.yaml",
        "leader.yaml",
    ]
    assert "__extends__" not in read_node(tmp_path / "leader.yaml")


def test_overlay_merges_named_lists_and_replaces_the_rest():
    limits = [{"name": "j1", "min": 0, "max": 10}, {"name": "j2", "min": 0, "max": 5}]
    merged = overlay({"limits": limits, "n": 1}, {"limits": [{"name": "j2", "max": 7}]})
    assert merged == {
        "limits": [limits[0], {"name": "j2", "min": 0, "max": 7}],
        "n": 1,
    }
    # entries without a common name, or with a repeated one: replaced as a whole
    assert overlay([{"a": 1}], [{"b": 2}]) == [{"b": 2}]
    twice = [{"name": "x"}, {"name": "x"}]
    assert overlay([{"name": "x", "v": 1}], twice) == twice
    assert overlay({"a": {"b": 1}}, {"a": None}) == {"a": None}


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("extends: ../leader.yaml\n", "names a node file in the same directory"),
        ("extends: none.yaml\n", "names none.yaml, which is not there"),
        ("extends: other.yaml\n", "goes in a circle"),
        ("without: [port]\n", "`without` needs `extends`"),
        ("extends: leader.yaml\nwithout: [registers.kp]\n", "'registers.kp', which is"),
        ("extends: leader.yaml\nwithout: port\n", "`without` is a list of keys"),
    ],
)
def test_a_bad_extends_is_named(tmp_path, text, problem):
    _write(tmp_path, leader=BASE, other="extends: bad.yaml\n", bad=text)
    with pytest.raises(ConfigError, match=problem):
        read_node(tmp_path / "bad.yaml")


def test_the_template_variants_extend_their_base_and_load(tmp_path):
    project = mock_project(tmp_path / ".roboloom")
    nodes = project / "nodes"
    for name, base in (("leader_gravity", "leader"), ("policy_teleop", "policy")):
        assert yaml.safe_load((nodes / f"{name}.yaml").read_text())["extends"] == (
            f"{base}.yaml"
        )
    cfg = load_config(project / "config.yaml", options=["policy_teleop"])
    assert cfg.controllers["policy"].teleop  # policy.yaml's settings plus teleop
    assert cfg.controllers["policy"].rate_hz == 15
    # the dataset manifest records which base files an extending node was built on
    saved = snapshot(cfg)
    assert saved is not None
    policy = saved["controllers"]["policy"]
    assert policy["file"] == "nodes/policy_teleop.yaml"
    assert policy["extends"] == ["nodes/policy.yaml"]
    assert policy["rate_hz"] == 15  # the values it ran with, bases included
    # extending a leader file merges a single control group override into the base groups
    (nodes / "leader_fixed_camera.yaml").write_text(
        "extends: leader.yaml\ncontrol:\n- group: body\n  law: position\n"
    )
    config = yaml.safe_load((project / "config.yaml").read_text())
    config["options"]["policy_teleop"]["set"]["inputs.leader"] = (
        "nodes/leader_fixed_camera.yaml"
    )
    (project / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    locked_cfg = load_config(project / "config.yaml", options=["policy_teleop"])
    by_group = {g.name: g.law for g in locked_cfg.inputs["leader"].control}
    assert by_group["body"] == "position"
    # a misspelled key of the extending file is still refused by the node's class
    teleop = nodes / "policy_teleop.yaml"
    teleop.write_text(teleop.read_text() + "rate_hx: 5\n")
    with pytest.raises(ConfigError, match="rate_hx"):
        load_config(project / "config.yaml", options=["policy_teleop"])
