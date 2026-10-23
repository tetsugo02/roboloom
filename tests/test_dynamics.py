import numpy as np
import pytest

from roboloom.dynamics.identify import holdout_mask, search_directions
from roboloom.dynamics.kinematics import UrdfTree
from roboloom.dynamics.regressor import (
    COUNTS_PER_RAD,
    JointMap,
    Regressor,
    RegressorGravityModel,
)

# base -(yaw about z)-> l0 -(pitch about y, 0.1 up)-> l1 -(pitch about y, 0.3 along x)-> l2 -fixed-> tip
URDF = """<robot name="toy">
  <link name="base"/><link name="l0"/><link name="l1"/><link name="l2"/><link name="tip"/>
  <joint name="yaw" type="continuous"><parent link="base"/><child link="l0"/><axis xyz="0 0 1"/></joint>
  <joint name="j1" type="revolute"><parent link="l0"/><child link="l1"/><origin xyz="0 0 0.1"/><axis xyz="0 1 0"/></joint>
  <joint name="j2" type="revolute"><parent link="l1"/><child link="l2"/><origin xyz="0.3 0 0" rpy="0 0 0"/><axis xyz="0 1 0"/></joint>
  <joint name="t" type="fixed"><parent link="l2"/><child link="tip"/><origin xyz="0.2 0 0"/></joint>
</robot>"""

INPUTS = [
    JointMap("yaw", "yaw", 2048, 1),
    JointMap("a", "j1", 2048, 1),
    JointMap("b", "j2", 2048, -1),
]
OUTPUTS = ["a", "b"]


def physics(counts):
    """True holding torque (scaled to mA): mass 1.0 at (0.15, 0, 0.05) in l1, 0.5 at (0.2, 0, 0.03) in l2, 3 mA offset on b.

    Masses off the link axis make the joint directions identifiable (see the symmetric case below).
    """
    q1, q2 = INPUTS[1].angle(counts[1]), INPUTS[2].angle(counts[2])
    # rotation about +y: x' = x cos q + z sin q
    x1 = 0.15 * np.cos(q1) + 0.05 * np.sin(q1)
    x2 = 0.3 * np.cos(q1) + 0.2 * np.cos(q1 + q2) + 0.03 * np.sin(q1 + q2)
    tau1 = 9.81 * (1.0 * x1 + 0.5 * x2)
    tau2 = 9.81 * 0.5 * (0.2 * np.cos(q1 + q2) + 0.03 * np.sin(q1 + q2))
    return np.array(
        [100 * tau1, 100 * -tau2 + 3.0]
    )  # joint b's motor counts the other way


def poses(n, seed=0):
    rng = np.random.default_rng(seed)
    out = np.column_stack(
        [
            2048 + rng.uniform(-1500, 1500, n),
            2048 + rng.uniform(-900, 900, n),
            2048 + rng.uniform(-900, 900, n),
        ]
    )
    return out


def test_forward_kinematics_matches_planar_solution():
    tree = UrdfTree.parse(URDF)
    links, _ = tree.frames({"j1": 0.4, "j2": -0.3})
    tip = links["tip"].origin
    expected = np.array(
        [
            0.3 * np.cos(0.4) + 0.2 * np.cos(0.1),
            0,
            0.1 - 0.3 * np.sin(0.4) - 0.2 * np.sin(0.1),
        ]
    )
    assert np.allclose(tip, expected)
    assert tree.movable() == ["yaw", "j1", "j2"]
    assert tree.subtree_joints("j1") == ["j1", "j2"]


def test_identified_model_predicts_unseen_poses_and_reports_rank(tmp_path):
    train, test = poses(40), poses(20, seed=1)
    currents = np.array([physics(q) for q in train])
    reg = Regressor(URDF, INPUTS, OUTPUTS)
    fit = reg.fit(train, currents, holdout_mask(len(train)))
    assert max(fit.holdout_rms_mA) < 1e-6
    assert fit.rank[0] < 4 * 2 + 1  # some first-moment directions are not identifiable
    model = RegressorGravityModel(URDF, INPUTS, OUTPUTS, fit.theta)
    for q in test:
        assert np.allclose(model.effort_mA(q), physics(q), atol=1e-6)
    urdf = tmp_path / "toy.urdf"
    urdf.write_text(URDF)
    model.save(tmp_path / "gravity.yaml", urdf, fit)
    loaded = RegressorGravityModel.load(tmp_path / "gravity.yaml")
    assert np.allclose(loaded.effort_mA(test[0]), physics(test[0]))
    urdf.write_text(URDF + " ")
    with pytest.raises(ValueError, match="changed"):
        RegressorGravityModel.load(tmp_path / "gravity.yaml")


def test_direction_search_and_zero_refinement_recover_calibration():
    samples = poses(40)
    currents = np.array([physics(q) for q in samples])
    wrong = [JointMap(m.name, m.urdf, m.zero, 1) for m in INPUTS]
    ranked = search_directions(
        URDF, wrong, OUTPUTS, samples, currents, holdout_mask(40), fixed={"yaw"}
    )
    # A planar chain cannot tell all angles flipped from mirrored mass: two exact fits tie,
    # so directions must come from calibration and the search only checks them.
    ties = [[m.direction for m in trial] for score, trial, _ in ranked if score < 1e-6]
    assert sorted(ties) == [[1, -1, 1], [1, 1, -1]]
    assert ranked[2][0] > 1.0
    best = INPUTS
    # A zero offset on j1 rotates everything below a planar joint: absorbed, predictions stay exact.
    shifted = [best[0], JointMap("a", "j1", 2048 + 46, 1), best[2]]
    fit = Regressor(URDF, shifted, OUTPUTS).fit(samples, currents, holdout_mask(40))
    assert max(fit.holdout_rms_mA) < 1e-6
    assert COUNTS_PER_RAD == pytest.approx(651.9, abs=0.1)


def test_shared_parameters_fit_with_few_poses():
    # same motor on both joints: one set of body moments; b's motor counts (and current) are reversed
    train, test = poses(6), poses(20, seed=3)
    currents = np.array([physics(q) for q in train])
    shared = Regressor(URDF, INPUTS, OUTPUTS).fit(train, currents, shared=True)
    model = RegressorGravityModel(URDF, INPUTS, OUTPUTS, shared.theta)
    for q in test:
        assert np.allclose(model.effort_mA(q), physics(q), atol=1e-6)
    ranked = search_directions(
        URDF,
        INPUTS,
        OUTPUTS,
        np.vstack([train, test]),
        np.array([physics(q) for q in np.vstack([train, test])]),
        holdout_mask(26),
        fixed={"yaw"},
        shared=True,
    )
    ties = sorted([m.direction for m in trial] for score, trial, _ in ranked if score < 1e-6)
    assert ties == [[1, -1, 1], [1, 1, -1]]  # the planar mirror ambiguity remains with shared parameters
