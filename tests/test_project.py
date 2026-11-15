import hashlib
import json
import shutil
import time

import pytest
import yaml

from roboloom.config import load_config, placeholders, resolve_config
from roboloom.control.device import build_laws, parse_groups
from roboloom.control.laws import GravityComp
from roboloom.core.resources import resolve
from roboloom.errors import ConfigError
from roboloom.project import RECORD, init_project, update_project
from roboloom.runtime.flow import timer


def test_init_copies_the_template_once_and_ignores_raw_data(tmp_path):
    root = tmp_path / ".roboloom"
    assert "created" in init_project("rakuda2", root)
    project = root / "rakuda2"
    assert (project / "config.yaml").is_file()
    assert not list(project.glob("experiment*.yaml"))
    assert (project / "calibration" / "gravity_tuning_right.yaml").is_file()
    assert "*.npz" in (root / ".gitignore").read_text()
    with pytest.raises(ConfigError, match="already exists"):
        init_project("rakuda2", root)
    with pytest.raises(ConfigError, match="unknown robot"):
        init_project("nope", root)


def test_configs_resolve_by_name_under_the_project_root(tmp_path):
    root = tmp_path / ".roboloom"
    init_project("rakuda2", root)
    assert resolve_config("rakuda2", root) == root / "rakuda2" / "config.yaml"
    # the only robot under the root needs no name
    assert resolve_config(None, root) == root / "rakuda2" / "config.yaml"
    (root / "two").mkdir()
    (root / "two" / "config.yaml").write_text("{}")
    with pytest.raises(ConfigError, match="several robots"):
        resolve_config(None, root)
    with pytest.raises(ConfigError, match="roboloom init"):
        resolve_config("missing", root)


def test_placeholders_are_listed_with_their_location():
    tree = {
        "followers": {"follower": {"port": "SET_PORT", "__dir__": "SET_x"}},
        "a": [1, "SET_B"],
    }
    assert placeholders(tree) == ["followers.follower.port: SET_PORT", "a[1]: SET_B"]


def test_package_references_resolve_to_shipped_files(tmp_path):
    assert resolve("roboloom:robots/rakuda2/model/assembly_2.urdf").is_file()
    with pytest.raises(FileNotFoundError):
        resolve("roboloom:robots/none.urdf")
    assert resolve("x.yaml", tmp_path) == (tmp_path / "x.yaml").resolve()


class Flat:
    joint_names = output_joints = ("a", "b")

    def effort_mA(self, positions):
        return [10.0, 10.0]


def test_tuning_file_sets_gain_and_hold_per_joint(tmp_path):
    (tmp_path / "t.yaml").write_text(
        yaml.safe_dump(
            {
                "hold_kp": 2.0,
                "joints": {"a": {"gain": 1.5, "hold_mA": 20}, "b": {"gain": 0}},
            }
        )
    )
    group = {
        "group": "arm",
        "law": "gravity_comp",
        "joints": ["a", "b"],
        "tuning": "t.yaml",
        "max_current_mA": 100,
        "max_velocity": 3000,
        "range": [[0, 4095], [0, 4095]],
    }
    groups = parse_groups([group], ("a", "b"), "dev")
    (law,) = build_laws(groups, ("a", "b"), str(tmp_path), {"arm": Flat()})
    assert isinstance(law, GravityComp)
    assert law.gain == [1.5, 0.0] and law.hold == [20.0, 0.0] and law.hold_kp == 2.0
    groups = parse_groups([{**group, "gravity_gain": 1.0}], ("a", "b"), "dev")
    with pytest.raises(ValueError, match="both inline and in tuning"):
        build_laws(groups, ("a", "b"), str(tmp_path), {"arm": Flat()})


# -- a project runs in mock before anything was measured ------------------------------


def test_a_fresh_project_loads_with_mock_devices_and_not_with_the_hardware(tmp_path):
    root = tmp_path / ".roboloom"
    init_project("rakuda2", root)
    path = root / "rakuda2" / "config.yaml"
    for options in (None, ["digit"], ["policy"], ["pika"], ["policy", "policy_teleop"]):
        cfg = load_config(path, options=options, mock=True)
        assert cfg.mock
    assert cfg.followers["follower"].port == "mock://follower"  # from mock.yaml
    # the files still hold the SET_ values, and the hardware refuses them as ever
    assert "SET_FOLLOWER_PORT" in (path.parent / "nodes" / "follower.yaml").read_text()
    with pytest.raises(ConfigError, match="template values still to fill"):
        load_config(path)
    (path.parent / "mock.yaml").write_text("port: /dev/ttyUSB0\n")
    with pytest.raises(ConfigError, match="its keys are SET_ names"):
        load_config(path, mock=True)


@pytest.mark.skipif(shutil.which("dora") is None, reason="needs dora")
def test_a_fresh_project_records_an_episode_in_mock(tmp_path):
    from roboloom.runtime.session import Session

    root = tmp_path / ".roboloom"
    init_project("rakuda2", root)  # not a file is edited
    with Session.launch(
        root / "rakuda2" / "config.yaml", mock=True, log_dir=tmp_path / "logs"
    ) as s:
        # the mock follower starts where the mock leader's trigger spring rests
        s.wait_ready(60)
        result = s.record("try it", 1.5)
    assert result.saved and result.metrics["action_valid_rate"] > 0.5, result.metrics


# -- updating a project to a newer template ---------------------------------------------


def test_update_adds_and_replaces_without_touching_what_was_edited(tmp_path):
    root = tmp_path / ".roboloom"
    init_project("rakuda2", root)
    project = root / "rakuda2"
    assert "nothing to do" in update_project("rakuda2", root)

    # as an older template left it: a file missing, one unchanged copy that the
    # template has changed since, and two files the user edited
    (project / "nodes" / "policy.yaml").unlink()
    record = json.loads((project / RECORD).read_text())
    stale = project / "nodes" / "camera.yaml"
    stale.write_text("type: realsense_rgb  # an older template\n")
    record["files"]["nodes/camera.yaml"] = hashlib.sha256(
        stale.read_bytes()
    ).hexdigest()
    (project / RECORD).write_text(json.dumps(record))
    follower = project / "nodes" / "follower.yaml"
    measured = follower.read_text().replace("SET_FOLLOWER_PORT", "/dev/measured")
    follower.write_text(measured)
    config = yaml.safe_load((project / "config.yaml").read_text())
    del config["options"]["policy_teleop"], config["options"]["policy"]
    (project / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))

    report = update_project("rakuda2", root)
    assert "added:\n  nodes/policy.yaml" in report
    assert "replaced (unchanged copies):\n  nodes/camera.yaml" in report
    assert "config.yaml: options.policy, options.policy_teleop" in report
    assert "nodes/follower.yaml: other values or text" in report
    assert (project / "nodes" / "policy.yaml").is_file()
    assert "SET_REALSENSE_SERIAL" in stale.read_text()  # the template's again
    assert follower.read_text() == measured  # the measured value is still there
    assert (
        "policy" not in yaml.safe_load((project / "config.yaml").read_text())["options"]
    )
    # a second run has nothing to add or replace, and still leaves the edited files
    again = update_project("rakuda2", root)
    assert "added" not in again and "replaced" not in again
    assert "nodes/follower.yaml" in again and follower.read_text() == measured


def test_update_needs_a_project_and_treats_an_old_one_as_edited(tmp_path):
    root = tmp_path / ".roboloom"
    with pytest.raises(ConfigError, match="roboloom init rakuda2"):
        update_project("rakuda2", root)
    init_project("rakuda2", root)
    project = root / "rakuda2"
    (project / RECORD).unlink()  # made before the record existed
    readme = project / "README.md"
    readme.write_text("my notes\n")
    report = update_project("rakuda2", root)
    assert "README.md" in report and readme.read_text() == "my notes\n"
    assert (project / RECORD).is_file()


# -- node rates -----------------------------------------------------------------------


def test_a_node_ticks_at_whole_hz_or_whole_milliseconds_only():
    assert timer(120, "follower") == "dora/timer/hz/120"
    assert timer(12.5, "camera") == "dora/timer/millis/80"
    assert timer(0.5, "slow") == "dora/timer/millis/2000"
    with pytest.raises(ConfigError, match="camera: 29.97 Hz is neither"):
        timer(29.97, "camera")  # it used to run at 29 Hz without a word


@pytest.mark.skipif(shutil.which("dora") is None, reason="needs dora")
def test_a_rate_in_whole_milliseconds_runs_at_that_rate(tmp_path):
    from conftest import mock_project

    from roboloom.runtime.session import Session

    project = mock_project(tmp_path / ".roboloom")
    camera = project / "nodes" / "camera.yaml"
    assert "fps: 30" in camera.read_text()
    camera.write_text(camera.read_text().replace("fps: 30", "fps: 12.5"))
    with Session.launch(project / "config.yaml", log_dir=tmp_path / "logs") as s:
        time.sleep(4.0)
        rate = s.status()["camera"]["fields"]["rate_hz"]
    assert 11.5 < rate < 13.5, rate  # 80 ms ticks; it used to be cut to 12 Hz
