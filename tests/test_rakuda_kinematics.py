"""Kinematics in a follower's own joint unit: the unit map of `KinematicSpec`, and the
Rakuda2 arms (counts, CAD URDF with continuous joints)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from conftest import rakuda2_tree

from roboloom.config import parse_config
from roboloom.kinematics.spec import KinematicSpec

FILES = {
    "right_arm": "../calibration/follower_right.yaml",
    "left_arm": "../calibration/follower_left.yaml",
}


def _follower():
    tree = rakuda2_tree()
    tree["followers"]["follower"]["kinematics"] = dict(FILES)
    return parse_config(tree).followers["follower"]


def test_the_unit_map_goes_both_ways_and_flips_the_range():
    spec = KinematicSpec(
        Path("arm.urdf"),
        "base",
        "tip",
        ("a_dof", "b_dof"),
        follower_joints=("a", "b"),
        scale=(0.5, -2.0),
        offset=(10.0, 100.0),
    )
    assert spec.names == ("a", "b")
    assert spec.to_model([12.0, 101.0]) == [1.0, -2.0]
    assert spec.from_model([1.0, -2.0]) == [12.0, 101.0]
    low, high = spec.model_limits([10.0, 100.0], [14.0, 101.0])
    assert low == [0.0, -2.0] and high == [2.0, 0.0]  # the flipped joint swaps its ends
    plain = KinematicSpec(Path("arm.urdf"), "base", "tip", ("a", "b"))
    assert plain.names == ("a", "b") and plain.to_model([1, 2]) == [1.0, 2.0]
    assert plain.confirmed
    with pytest.raises(ValueError, match="one value per joint"):
        KinematicSpec(Path("arm.urdf"), "base", "tip", ("a", "b"), scale=(1.0,))
    with pytest.raises(ValueError, match="not zero"):
        KinematicSpec(Path("arm.urdf"), "base", "tip", ("a",), scale=(0.0,))


def test_a_rakuda_arm_is_a_chain_in_counts():
    follower = _follower()
    assert follower.kinematics() is None  # the whole follower is not one chain
    assert follower.part("body").kinematics() is None
    spec = follower.part("right_arm").kinematics()
    assert spec is not None
    assert spec.names == follower.parts()["right_arm"]
    assert spec.joints[0] == "shoulder_pitch_right_dof"
    assert not spec.confirmed  # the shipped joint map is a guess until checked
    # one turn is 4096 counts; the zero pose is where the calibration says
    assert spec.to_model([2048.0] * 6) == [0.0] * 6
    turn = spec.to_model([2048.0 + 4096] * 6)
    assert np.allclose(np.abs(turn), 2 * np.pi)
    assert {np.sign(x) for x in turn} == {1.0, -1.0}  # directions from the file

    tree = rakuda2_tree()
    del tree["followers"]["follower"]["kinematics"]  # the template names the files
    plain = parse_config(tree).followers["follower"]
    assert plain.part("right_arm").kinematics() is None  # not described


def test_rakuda_arm_poses_are_reached_again_by_the_ik():
    pytest.importorskip("pinocchio")
    from roboloom.kinematics.ik import ArmModel

    follower = _follower()
    for part in FILES:
        spec = follower.part(part).kinematics()
        model = ArmModel(spec)  # continuous joints, CAD link names
        wanted = [2048.0 + d for d in (200, -300, 250, 400, 100, -150)]
        seed = [2048.0 + d for d in (150, -250, 200, 350, 60, -100)]
        pose = model.fk(spec.to_model(wanted))
        low, high = spec.model_limits([1000.0] * 6, [3000.0] * 6)
        result = model.solve(pose, spec.to_model(seed), low, high)
        assert result.reached, (part, result)
        again = model.fk(result.q)
        assert np.allclose(again[:3, 3], pose[:3, 3], atol=2e-3)
        counts = spec.from_model(result.q)
        assert all(1000 <= c <= 3000 for c in counts)


def test_a_joint_map_with_gaps_is_refused(tmp_path):
    import yaml

    source = Path(
        "src/roboloom/robots/rakuda2/template/calibration/follower_right.yaml"
    )
    data = yaml.safe_load(source.read_text())
    data["urdf"] = "roboloom:robots/rakuda2/model/assembly_2.urdf"
    data["joints"] = [j for j in data["joints"] if j["name"] != "r_arm_wr_yaw"]
    (tmp_path / "short.yaml").write_text(yaml.safe_dump(data))
    tree = rakuda2_tree()
    tree["followers"]["follower"]["kinematics"] = {
        "right_arm": str(tmp_path / "short.yaml")
    }
    follower = parse_config(tree).followers["follower"]
    with pytest.raises(ValueError, match="lacks"):
        follower.part("right_arm").kinematics()
