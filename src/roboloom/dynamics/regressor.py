"""Gravity model identified from measured holding currents.

Kinematics (joint axes and frames) come from a URDF; masses do not, because the
CAD masses do not describe the leader. For output joint j, gravity current is
linear in the first moments of every body below it:

    i_j(q) = sum_b [ -(g x z_j) . (o_b - o_j) ] m_b + [ -R_b^T (g x z_j) ] . w_b + c_j

with body origin o_b, rotation R_b, mass m_b, first moment w_b = m_b c_b in the
body frame, and a constant c_j (cable bias, current offset). Each joint is fit
separately in mA, so the unknown torque constant and gear ratio of every motor
are absorbed. Directions that the data cannot excite are left at zero
(minimum-norm least squares); the rank is reported.
"""

from __future__ import annotations

import datetime
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

from .kinematics import UrdfTree

GRAVITY = np.array([0.0, 0.0, -1.0])  # magnitude is absorbed by the parameters
COUNTS_PER_RAD = 4096 / (2 * np.pi)


@dataclass
class JointMap:
    name: str  # device joint
    urdf: str  # URDF joint
    zero: float  # raw count at URDF angle 0
    direction: int  # +1 / -1: sign between raw counts and URDF angle

    def angle(self, count: float) -> float:
        return self.direction * (count - self.zero) / COUNTS_PER_RAD


@dataclass
class Fit:
    theta: list[list[float]]
    rank: list[int]
    condition: list[float]
    rms_mA: list[float]
    holdout_rms_mA: list[float] = field(default_factory=list)


class Regressor:
    """Builds regressor rows for one URDF, a set of input joints and output joints."""

    def __init__(self, urdf_text: str, inputs: list[JointMap], outputs: list[str]):
        self.inputs, self.outputs = inputs, outputs
        tree = UrdfTree.parse(urdf_text)
        movable = set(tree.movable())
        names = {m.urdf for m in inputs}
        if not names <= movable:
            raise ValueError(f"unknown URDF joints {sorted(names - movable)}")
        by_name = {m.name: m for m in inputs}
        if not set(outputs) <= set(by_name):
            raise ValueError("every output joint must also be an input")
        self.output_urdf = [by_name[o].urdf for o in outputs]
        # bodies below each output joint: the model joints in its subtree (itself included)
        self.bodies = {u: [b for b in tree.subtree_joints(u) if b in names] for u in self.output_urdf}
        # body frames are the child links of model joints; nothing else needs computing
        self.tree = tree.restricted(sorted(names))

    def rows(self, counts: Sequence[float]) -> list[np.ndarray]:
        """One regressor row per output joint: [m_b, w_b(3)] per body, then the constant."""
        angles = {m.urdf: m.angle(c) for m, c in zip(self.inputs, counts, strict=True)}
        links, joints = self.tree.frames(angles)
        out = []
        for u in self.output_urdf:
            frame = joints[u]
            z = frame.rotation @ self.tree.joints[u].axis
            gz = np.cross(GRAVITY, z)
            row = []
            for b in self.bodies[u]:
                body = links[self.tree.joints[b].child]
                row.append(-gz @ (joints[b].origin - frame.origin))
                row.extend(-(body.rotation.T @ gz))
            row.append(1.0)
            out.append(np.asarray(row))
        return out

    def fit(self, samples: np.ndarray, currents: np.ndarray, holdout: np.ndarray | None = None) -> Fit:
        """`samples` N x inputs (counts), `currents` N x outputs (mA); `holdout` marks validation rows."""
        mask = np.zeros(len(samples), bool) if holdout is None else holdout
        rows = [self.rows(q) for q in samples]
        result = Fit([], [], [], [], [])
        for k in range(len(self.outputs)):
            a = np.array([r[k] for r in rows])
            y = currents[:, k]
            train = ~mask
            theta, _, rank, sv = np.linalg.lstsq(a[train], y[train], rcond=1e-6)
            result.theta.append(theta.tolist())
            result.rank.append(int(rank))
            result.condition.append(float(sv[0] / sv[rank - 1]) if rank else float("inf"))
            result.rms_mA.append(float(np.sqrt(np.mean((a[train] @ theta - y[train]) ** 2))))
            if mask.any():
                result.holdout_rms_mA.append(float(np.sqrt(np.mean((a[mask] @ theta - y[mask]) ** 2))))
        return result


class RegressorGravityModel:
    """`GravityModel` backed by a `Regressor` and identified parameters."""

    def __init__(self, urdf_text: str, inputs: list[JointMap], outputs: list[str], theta: list[list[float]], meta: dict | None = None):
        self.regressor = Regressor(urdf_text, inputs, outputs)
        self.joint_names = tuple(m.name for m in inputs)
        self.output_joints = tuple(outputs)
        self.theta = [np.asarray(t) for t in theta]
        self.meta = meta or {}
        for t, u in zip(self.theta, self.regressor.output_urdf, strict=True):
            if len(t) != 4 * len(self.regressor.bodies[u]) + 1:
                raise ValueError("parameter count does not match the URDF bodies")

    def effort_mA(self, positions: Sequence[float]) -> list[float]:
        return [float(row @ t) for row, t in zip(self.regressor.rows(positions), self.theta, strict=True)]

    def save(self, path: str | Path, urdf_path: str | Path, fit: Fit, extra: dict | None = None) -> None:
        path = Path(path)
        urdf = Path(urdf_path).resolve()
        data = {
            "kind": "regressor_gravity",
            "unit": "mA",
            "urdf": str(urdf.relative_to(path.parent.resolve(), walk_up=True)),
            "urdf_sha256": hashlib.sha256(urdf.read_bytes()).hexdigest(),
            "created": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
            "inputs": [vars(m) for m in self.regressor.inputs],
            "outputs": list(self.output_joints),
            "theta": [t.tolist() for t in self.theta],
            "rank": fit.rank,
            "condition": fit.condition,
            "rms_mA": fit.rms_mA,
            "holdout_rms_mA": fit.holdout_rms_mA,
            **(extra or {}),
        }
        path.write_text(yaml.safe_dump(data, sort_keys=False))

    @classmethod
    def load(cls, path: str | Path) -> RegressorGravityModel:
        path = Path(path)
        data = yaml.safe_load(path.read_text())
        if data.get("kind") != "regressor_gravity" or data.get("unit") != "mA":
            raise ValueError(f"{path}: not a regressor gravity model in mA")
        urdf = (path.parent / data["urdf"]).resolve()
        text = urdf.read_bytes()
        if hashlib.sha256(text).hexdigest() != data["urdf_sha256"]:
            raise ValueError(f"{path}: {urdf} changed since the model was identified")
        inputs = [JointMap(m["name"], m["urdf"], float(m["zero"]), int(m["direction"])) for m in data["inputs"]]
        return cls(text.decode(), inputs, data["outputs"], data["theta"], data)
