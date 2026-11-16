"""A robot roboloom does not ship: its class is named by reference (`type:
module:Class`) and found by every node process, and its template makes a project."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from roboloom.config import load_config
from roboloom.core.registry import Registry, load_reference
from roboloom.errors import ConfigError
from roboloom.project import RECORD, init_project, update_project
from roboloom.recording import manifest
from roboloom.robots import FOLLOWERS
from roboloom.robots.base import Follower

EXAMPLE = str(Path(__file__).resolve().parents[1] / "examples" / "own_robot")


def _project(tmp_path: Path) -> Path:
    init_project("lab_arm", tmp_path / ".roboloom", template=EXAMPLE)
    return tmp_path / ".roboloom" / "lab_arm"


def test_a_class_next_to_the_configuration_is_found_by_reference(tmp_path):
    project = _project(tmp_path)
    cfg = load_config(project / "config.yaml", mock=True)
    arm = cfg.followers["arm"]
    assert type(arm).__name__ == "MyArm" and isinstance(arm, Follower)
    assert arm.joint_names == ("shoulder", "elbow") and arm.unit == "rad"
    assert arm.address == "mock://arm"  # the template's mock.yaml
    # the class says which keys it reads, so its YAML is checked like a built-in one
    node = project / "nodes" / "follower.yaml"
    node.write_text(node.read_text() + "adress: 10.0.0.2\n")
    with pytest.raises(
        ConfigError, match=r"unknown keys adress \(did you mean address"
    ):
        load_config(project / "config.yaml", mock=True)


@pytest.mark.parametrize(
    ("reference", "message"),
    [
        ("my_arm:JOINTS", "is not a Follower subclass"),
        ("my_arm:Missing", "has no attribute 'Missing'"),
        ("no_such_module:Arm", "No module named 'no_such_module'"),
        ("not_a_type", "unsupported follower type.*or module:Class"),
    ],
)
def test_a_reference_that_is_not_a_follower_class_is_refused(
    tmp_path, reference, message
):
    project = _project(tmp_path)
    node = project / "nodes" / "follower.yaml"
    node.write_text(node.read_text().replace("my_arm:MyArm", reference))
    with pytest.raises(ConfigError, match=message):
        load_config(project / "config.yaml", mock=True)


def test_a_reference_names_any_object_and_installed_modules_come_first(tmp_path):
    (tmp_path / "json.py").write_text("dumps = 'shadow'\n")  # must not win
    assert load_reference("json:dumps", [str(tmp_path)]) is json.dumps
    assert FOLLOWERS.get("roboloom.robots.base:Follower") is Follower
    plain: Registry = Registry("thing", {})
    assert plain.get("json:JSONDecoder") is json.JSONDecoder  # no base to check
    with pytest.raises(ConfigError, match="expected 'module:attribute'"):
        load_reference("json:")


@pytest.mark.e2e
@pytest.mark.skipif(shutil.which("dora") is None, reason="needs dora")
def test_every_node_process_finds_the_class(tmp_path):
    from roboloom.runtime.session import Session

    project = _project(tmp_path)
    with Session.launch(
        project / "config.yaml", mock=True, log_dir=tmp_path / "logs"
    ) as s:
        s.wait_ready(60)
        result = s.record("hold", 1.5)
        root = Path(s.cfg.output)
    assert result.saved and result.metrics["action_valid_rate"] > 0.5, result.metrics
    assert manifest.read(root)["units"]["action"] == ["rad", "rad"]


# -- templates roboloom does not ship ---------------------------------------------------


def test_a_project_is_made_from_a_directory_or_a_package_and_updated_from_it(tmp_path):
    root = tmp_path / ".roboloom"
    project = _project(tmp_path)
    assert (project / "my_arm.py").is_file()  # the class travels with the template
    record = json.loads((project / RECORD).read_text())
    assert record["template"] == EXAMPLE and "my_arm.py" in record["files"]
    assert "nothing to do" in update_project(
        "lab_arm", root
    )  # found again by the record

    # a package holding template/: here the shipped one, under another project name
    init_project("second", root, template="roboloom.robots.rakuda2")
    assert (root / "second" / "nodes" / "follower.yaml").is_file()
    (root / "second" / "nodes" / "policy.yaml").unlink()
    assert "added:\n  nodes/policy.yaml" in update_project("second", root)


@pytest.mark.parametrize(
    ("template", "message"),
    [
        ("no.such.package", "neither a directory nor an importable package"),
        ("json", "holds no template/config.yaml"),
        (None, "unknown robot 'lab_arm'.*--template"),
    ],
)
def test_a_template_that_cannot_be_found_is_refused(tmp_path, template, message):
    with pytest.raises(ConfigError, match=message):
        init_project("lab_arm", tmp_path / ".roboloom", template=template)
    assert not (tmp_path / ".roboloom" / "lab_arm").exists()


def test_the_example_has_no_key_its_class_does_not_read():
    # the example is documentation: it must load as it is (mock stand-ins aside)
    files = sorted(Path(EXAMPLE).rglob("*.yaml"))
    assert [f.name for f in files if f.parent.name == "nodes"] == [
        "follower.yaml",
        "policy.yaml",
        "recorder.yaml",
        "session.yaml",
    ]
    assert yaml.safe_load((Path(EXAMPLE) / "mock.yaml").read_text()) == {
        "SET_ARM_ADDRESS": "mock://arm"
    }
    assert load_config(Path(EXAMPLE) / "config.yaml", mock=True).robot == "own_robot"
