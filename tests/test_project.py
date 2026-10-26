import pytest
import yaml

from roboloom.config import placeholders, resolve_experiment
from roboloom.control.device import build_laws, parse_groups
from roboloom.control.laws import GravityComp
from roboloom.core.resources import resolve
from roboloom.errors import ConfigError
from roboloom.project import init_project


def test_init_copies_the_template_once_and_ignores_raw_data(tmp_path):
    root = tmp_path / ".roboloom"
    assert "created" in init_project("rakuda2", root)
    project = root / "rakuda2"
    assert (project / "experiment_gravity.yaml").is_file()
    assert (project / "calibration" / "gravity_tuning_right.yaml").is_file()
    assert "*.npz" in (root / ".gitignore").read_text()
    with pytest.raises(ConfigError, match="already exists"):
        init_project("rakuda2", root)
    with pytest.raises(ConfigError, match="unknown robot"):
        init_project("nope", root)


def test_experiments_resolve_by_name_under_the_project_root(tmp_path):
    root = tmp_path / ".roboloom"
    init_project("rakuda2", root)
    assert resolve_experiment("rakuda2", root) == root / "rakuda2" / "experiment.yaml"
    assert resolve_experiment("rakuda2/experiment_gravity", root).name == (
        "experiment_gravity.yaml"
    )
    with pytest.raises(ConfigError, match="roboloom init"):
        resolve_experiment("missing", root)


def test_placeholders_are_listed_with_their_location():
    tree = {
        "robots": {"robot": {"port": "SET_PORT", "__dir__": "SET_x"}},
        "a": [1, "SET_B"],
    }
    assert placeholders(tree) == ["robots.robot.port: SET_PORT", "a[1]: SET_B"]


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
