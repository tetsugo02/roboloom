"""PiPER kinematics (vendored URDF) and the damped-least-squares IK (pinocchio)."""

from __future__ import annotations

import math

import numpy as np
import pytest

pytest.importorskip("pinocchio")

from roboloom.kinematics.ik import ArmModel
from roboloom.kinematics.spec import (
    invert,
    matrix_quaternion,
    pose_from,
    pose_to,
    pose_xyz_rpy,
    quaternion_matrix,
    rotation_angle,
)
from roboloom.robots.piper.spec import MODEL, RANGE

LOW = [RANGE[j][0] for j in MODEL.joints]
HIGH = [RANGE[j][1] for j in MODEL.joints]
POSES = (
    [0.0] * 6,
    [0.3, 1.0, -1.2, 0.4, -0.5, 0.7],
    [-0.8, 0.5, -0.4, -1.0, 0.9, -1.5],
)


def sdk_dh(q):
    """piper_sdk 0.6.2 `C_PiperForwardKinematics(dh_is_offset=1)`: modified DH, mm."""
    a = [0, 0, 285.03, -21.98, 0, 0]
    alpha = [0, -math.pi / 2, 0, math.pi / 2, -math.pi / 2, math.pi / 2]
    d = [123, 0, 0, 250.75, 0, 91]
    offset = [0, math.radians(-172.22), math.radians(-102.78), 0, 0, 0]
    out = np.eye(4)
    for i in range(6):
        ca, sa = math.cos(alpha[i]), math.sin(alpha[i])
        ct, st = math.cos(q[i] + offset[i]), math.sin(q[i] + offset[i])
        out = out @ np.array(
            [
                [ct, -st, 0, a[i]],
                [st * ca, ct * ca, -sa, -sa * d[i]],
                [st * sa, ct * sa, ca, ca * d[i]],
                [0, 0, 0, 1],
            ]
        )
    return out


def test_quaternions_round_trip_in_xyzw():
    q = [0.1, -0.2, 0.3, 0.9]
    r = quaternion_matrix(q)
    back = matrix_quaternion(r)
    assert np.allclose(back, np.asarray(q) / np.linalg.norm(q))
    assert np.allclose(quaternion_matrix([0, 0, 0, 1]), np.eye(3))
    pose = pose_xyz_rpy([0.1, 0.2, 0.3], [0.4, -0.5, 0.6])
    position, quaternion = pose_to(pose)
    assert np.allclose(pose_from(position, quaternion), pose)
    assert np.allclose(invert(pose) @ pose, np.eye(4))
    assert rotation_angle(
        pose_xyz_rpy([0, 0, 0], [0, 0, 0.7])[:3, :3]
    ) == pytest.approx(0.7)
    with pytest.raises(ValueError):
        quaternion_matrix([0, 0, 0, 0])


def test_the_urdf_matches_the_sdk_dh_parameters():
    arm = ArmModel(MODEL)
    for q in POSES:
        urdf, dh = arm.fk(q), sdk_dh(q)
        assert np.allclose(urdf[:3, 3] * 1000, dh[:3, 3], atol=0.2)  # mm
        assert rotation_angle(urdf[:3, :3].T @ dh[:3, :3]) < math.radians(0.01)


def test_ik_reaches_poses_it_can_and_says_when_it_cannot():
    tool = pose_xyz_rpy([0, 0, 0.19], [0, -math.pi / 2, 0])
    arm = ArmModel(MODEL, tool)
    for q in POSES[1:]:
        result = arm.solve(
            arm.fk(q), [0.0, 0.5, -0.5, 0, 0, 0], LOW, HIGH, iterations=100
        )
        assert result.reached, result
        assert np.allclose(arm.fk(result.q)[:3, 3], arm.fk(q)[:3, 3], atol=1e-3)
    far = pose_xyz_rpy([2.0, 0, 0.3], [0, 0, 0])  # 2 m away: out of reach
    result = arm.solve(far, POSES[1], LOW, HIGH)
    assert not result.reached and result.position_error_m > 1.0
    assert all(lo <= v <= hi for v, lo, hi in zip(result.q, LOW, HIGH, strict=True))


def test_ik_is_deterministic_and_stays_near_its_seed():
    arm = ArmModel(MODEL)
    seed = [0.0, 1.2, -0.9, 0.0, 0.3, 0.0]
    target = arm.fk(seed) @ pose_xyz_rpy([0.0, 0.01, 0.0], [0.02, 0, 0])
    a = arm.solve(target, seed, LOW, HIGH)
    b = arm.solve(target, seed, LOW, HIGH)
    assert a == b and a.reached
    # a 1 cm, 0.02 rad step stays on the branch of the seed (no flip of the wrist)
    assert max(abs(x - s) for x, s in zip(a.q, seed, strict=True)) < 0.3
    assert a.iterations < 10


def test_a_follower_without_kinematics_says_so():
    from test_pika import follower_cfg

    from roboloom.robots.pika.follower import PikaGripperFollower

    assert PikaGripperFollower("g", follower_cfg()).kinematics() is None
