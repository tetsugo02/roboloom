"""Relative pose representations of a hand-held trajectory (numpy only).

A recorded hand-held device gives absolute poses `P[t]` in its tracker's world frame. A
policy that runs on a robot cannot use that frame (the robot's base is elsewhere), so the
training data expresses motion relative to the device itself, as UMI does:

- `deltas(P)`: `inv(P[t]) @ P[t+1]`, one step at a time (the last step stays put).
- `relative_chunks(P, H)`: `inv(P[t]) @ P[t+k]` for k = 1..H (past the end: the last pose).

A relative pose is stored as 9 numbers: the position (m) and the rotation's first two
columns ("6D", continuous, unlike quaternions or Euler angles). `targets_from_deltas` and
`targets_from_chunk` turn them back into absolute targets from the pose observed when the
policy ran, which is how a robot executes them.
"""

from __future__ import annotations

import numpy as np

from ..kinematics.spec import matrix_quaternion, quaternion_matrix

POSE_SIZE = 9  # x, y, z, r0..r5
POSE_NAMES = ("x", "y", "z", "r0", "r1", "r2", "r3", "r4", "r5")


def rot6d(r: np.ndarray) -> np.ndarray:
    """The first two columns of rotation(s) `[..., 3, 3]` -> `[..., 6]`."""
    r = np.asarray(r, dtype=float)
    return np.concatenate([r[..., :, 0], r[..., :, 1]], axis=-1)


def from_rot6d(v: np.ndarray) -> np.ndarray:
    """Rotation(s) `[..., 3, 3]` from 6D vectors (Gram-Schmidt, so any output works)."""
    v = np.asarray(v, dtype=float)
    a, b = v[..., :3], v[..., 3:6]
    x = a / np.linalg.norm(a, axis=-1, keepdims=True)
    b = b - np.sum(x * b, axis=-1, keepdims=True) * x
    y = b / np.linalg.norm(b, axis=-1, keepdims=True)
    z = np.cross(x, y)
    return np.stack([x, y, z], axis=-1)


def encode(pose: np.ndarray) -> np.ndarray:
    """Pose(s) `[..., 4, 4]` -> `[..., 9]` (position, 6D rotation)."""
    pose = np.asarray(pose, dtype=float)
    return np.concatenate([pose[..., :3, 3], rot6d(pose[..., :3, :3])], axis=-1)


def decode(v: np.ndarray) -> np.ndarray:
    """`[..., 9]` -> pose(s) `[..., 4, 4]`."""
    v = np.asarray(v, dtype=float)
    out = np.zeros((*v.shape[:-1], 4, 4))
    out[..., :3, :3] = from_rot6d(v[..., 3:9])
    out[..., :3, 3] = v[..., :3]
    out[..., 3, 3] = 1.0
    return out


def inverse(pose: np.ndarray) -> np.ndarray:
    """Inverse of rigid transform(s) `[..., 4, 4]`."""
    out = np.zeros_like(pose, dtype=float)
    rt = np.swapaxes(pose[..., :3, :3], -1, -2)
    out[..., :3, :3] = rt
    out[..., :3, 3] = -np.einsum("...ij,...j->...i", rt, pose[..., :3, 3])
    out[..., 3, 3] = 1.0
    return out


def poses_from(position: np.ndarray, quaternion: np.ndarray) -> np.ndarray:
    """`[N, 3]` positions and `[N, 4]` quaternions (xyzw) -> `[N, 4, 4]`."""
    out = np.tile(np.eye(4), (len(position), 1, 1))
    out[:, :3, :3] = [quaternion_matrix(q) for q in quaternion]
    out[:, :3, 3] = position
    return out


def deltas(poses: np.ndarray) -> np.ndarray:
    """`inv(P[t]) @ P[t+1]` for every t; the last is the identity (no next pose)."""
    out = np.tile(np.eye(4), (len(poses), 1, 1))
    out[:-1] = inverse(poses[:-1]) @ poses[1:]
    return out


def relative_chunks(poses: np.ndarray, horizon: int) -> np.ndarray:
    """`[N, H, 4, 4]`: `inv(P[t]) @ P[min(t+k, N-1)]` for k = 1..H."""
    n = len(poses)
    index = np.minimum(np.arange(n)[:, None] + np.arange(1, horizon + 1), n - 1)
    return inverse(poses)[:, None] @ poses[index]


def targets_from_deltas(observed: np.ndarray, steps: np.ndarray) -> np.ndarray:
    """Absolute targets `[H, 4, 4]` from the observed pose and `[H, 9]` encoded deltas."""
    out, pose = [], np.asarray(observed, dtype=float)
    for step in decode(steps):
        pose = pose @ step
        out.append(pose)
    return np.stack(out)


def targets_from_chunk(observed: np.ndarray, chunk: np.ndarray) -> np.ndarray:
    """Absolute targets `[H, 4, 4]` from the observed pose and a `[H, 9]` encoded chunk."""
    return np.asarray(observed, dtype=float) @ decode(chunk)


def _slerp(q0: np.ndarray, q1: np.ndarray, s: float) -> np.ndarray:
    dot = float(np.dot(q0, q1))
    if dot < 0:
        q1, dot = -q1, -dot
    if dot > 0.9995:
        q = q0 + s * (q1 - q0)
        return q / np.linalg.norm(q)
    theta = np.arccos(dot)
    return (np.sin((1 - s) * theta) * q0 + np.sin(s * theta) * q1) / np.sin(theta)


def fill_gaps(
    poses: np.ndarray, tracked: np.ndarray, max_gap: int
) -> tuple[np.ndarray, int, str | None]:
    """Fill untracked rows: inside, interpolate (position linearly, rotation by slerp);
    at either end, hold the nearest tracked pose. Returns (poses, filled rows, problem):
    `problem` names a gap longer than `max_gap` rows, or a trajectory never tracked."""
    tracked = np.asarray(tracked, dtype=bool)
    if not tracked.any():
        return poses, 0, "never tracked"
    out = poses.copy()
    filled, t, n = 0, 0, len(poses)
    while t < n:
        if tracked[t]:
            t += 1
            continue
        end = t
        while end < n and not tracked[end]:
            end += 1
        length = end - t
        if length > max_gap:
            return poses, filled, f"tracking lost for {length} rows from row {t}"
        before, after = t - 1, end
        for i in range(t, end):
            if before < 0:
                out[i] = poses[after]
            elif after >= n:
                out[i] = poses[before]
            else:
                s = (i - before) / (after - before)
                out[i] = np.eye(4)
                out[i, :3, 3] = (1 - s) * poses[before, :3, 3] + s * poses[after, :3, 3]
                q = _slerp(
                    np.asarray(matrix_quaternion(poses[before, :3, :3])),
                    np.asarray(matrix_quaternion(poses[after, :3, :3])),
                    s,
                )
                out[i, :3, :3] = quaternion_matrix(q.tolist())
        filled += length
        t = end
    return out, filled, None
