"""Kinematic descriptions and rigid transforms in numpy (no pinocchio needed).

A `Pose` is a 4x4 homogeneous transform; positions are in m, quaternions are xyzw.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..dynamics.kinematics import rpy_matrix

Pose = np.ndarray  # (4, 4)


@dataclass(frozen=True)
class KinematicSpec:
    """A follower's arm as a URDF chain: its joints (in the follower's order, named as in
    the URDF) from `base` to `tip` (the flange; tools are added by the controller)."""

    urdf: Path
    base: str
    tip: str
    joints: tuple[str, ...]


def quaternion_matrix(q: Sequence[float]) -> np.ndarray:
    """Rotation of a unit quaternion given as x, y, z, w."""
    x, y, z, w = (float(v) for v in q)
    n = np.sqrt(x * x + y * y + z * z + w * w)
    if not np.isfinite(n) or n < 1e-9:
        raise ValueError(f"not a rotation quaternion: {list(q)}")
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def matrix_quaternion(r: np.ndarray) -> list[float]:
    """x, y, z, w of a rotation matrix (w >= 0)."""
    m = np.asarray(r, dtype=float)
    trace = m[0, 0] + m[1, 1] + m[2, 2]
    if trace > 0:
        s = 2 * np.sqrt(trace + 1)
        q = [(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s]
        q.append(s / 4)
    else:
        i = int(np.argmax([m[0, 0], m[1, 1], m[2, 2]]))
        j, k = (i + 1) % 3, (i + 2) % 3
        s = 2 * np.sqrt(1 + m[i, i] - m[j, j] - m[k, k])
        v = [0.0, 0.0, 0.0]
        v[i] = s / 4
        v[j] = (m[j, i] + m[i, j]) / s
        v[k] = (m[k, i] + m[i, k]) / s
        q = [*v, (m[k, j] - m[j, k]) / s]
    if q[3] < 0:
        q = [-c for c in q]
    return [float(c) for c in q]


def pose_from(position: Sequence[float], quaternion: Sequence[float]) -> Pose:
    out = np.eye(4)
    out[:3, :3] = quaternion_matrix(quaternion)
    out[:3, 3] = np.asarray(position, dtype=float)
    return out


def pose_to(pose: Pose) -> tuple[list[float], list[float]]:
    """(position, quaternion xyzw) of a pose."""
    return [float(v) for v in pose[:3, 3]], matrix_quaternion(pose[:3, :3])


def pose_xyz_rpy(xyz: Sequence[float], rpy: Sequence[float]) -> Pose:
    """A pose from a translation (m) and roll, pitch, yaw (rad), as URDF origins."""
    out = np.eye(4)
    out[:3, :3] = rpy_matrix(*(float(a) for a in rpy))
    out[:3, 3] = np.asarray(xyz, dtype=float)
    return out


def invert(pose: Pose) -> Pose:
    out = np.eye(4)
    rotation = pose[:3, :3].T
    out[:3, :3] = rotation
    out[:3, 3] = -rotation @ pose[:3, 3]
    return out


def rotation_angle(r: np.ndarray) -> float:
    """The angle (rad) of a rotation matrix."""
    c = (float(np.trace(r)) - 1) / 2
    return float(np.arccos(min(1.0, max(-1.0, c))))
