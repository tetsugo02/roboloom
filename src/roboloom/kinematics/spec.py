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
    # The follower's own names of these joints, in the same order (None: as `joints`).
    follower_joints: tuple[str, ...] | None = None
    # The follower's joint unit -> rad of the URDF joint: rad = scale * (q - offset),
    # per joint (None: the follower already speaks rad with the URDF's zero and sign).
    # A negative scale is a joint that turns the other way.
    scale: tuple[float, ...] | None = None
    offset: tuple[float, ...] | None = None
    # False while the map above is a guess not yet checked on the robot: controllers
    # refuse to move hardware with it.
    confirmed: bool = True

    def __post_init__(self) -> None:
        n = len(self.joints)
        for name, values in (
            ("follower_joints", self.follower_joints),
            ("scale", self.scale),
            ("offset", self.offset),
        ):
            if values is not None and len(values) != n:
                raise ValueError(f"{name}: one value per joint ({n})")
        if self.scale is not None and not all(
            np.isfinite(s) and s != 0 for s in self.scale
        ):
            raise ValueError("scale: finite and not zero")

    @property
    def names(self) -> tuple[str, ...]:
        """The joints as the follower names them."""
        return self.follower_joints or self.joints

    def to_model(self, q: Sequence[float]) -> list[float]:
        """Follower joint values -> URDF joint angles (rad)."""
        scale = self.scale or (1.0,) * len(self.joints)
        offset = self.offset or (0.0,) * len(self.joints)
        return [s * (float(x) - o) for x, s, o in zip(q, scale, offset, strict=True)]

    def from_model(self, rad: Sequence[float]) -> list[float]:
        """URDF joint angles (rad) -> follower joint values."""
        scale = self.scale or (1.0,) * len(self.joints)
        offset = self.offset or (0.0,) * len(self.joints)
        return [float(x) / s + o for x, s, o in zip(rad, scale, offset, strict=True)]

    def model_limits(
        self, low: Sequence[float], high: Sequence[float]
    ) -> tuple[list[float], list[float]]:
        """The follower's joint range in rad (a flipped joint swaps its ends)."""
        a, b = self.to_model(low), self.to_model(high)
        return (
            [min(x, y) for x, y in zip(a, b, strict=True)],
            [max(x, y) for x, y in zip(a, b, strict=True)],
        )


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
