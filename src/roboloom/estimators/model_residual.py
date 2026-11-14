"""Residual of the follower's effort against a gravity model identified on the follower.

`residual = measured effort - g(q)`: the effort the motors spend beyond holding the arm
up. No training needed, so it is the first baseline; friction, inertia and position
tracking error stay in the residual, so it reads non-zero while the arm moves freely
(`contact_on` / `contact_off` keep that from opening the feedback).

Models are the `identify-gravity` output for a follower calibration
(`calibration/follower_<side>.yaml`), one per arm; together their output joints must be
exactly `joints`.
"""

from __future__ import annotations

from pathlib import Path

from ..dynamics.base import GravityModel, load_gravity_model
from ..robots.base import Follower
from .base import Estimator


class ModelResidual(Estimator):
    keys = (*Estimator.keys, "models")

    def __init__(self, name: str, cfg: dict):
        super().__init__(name, cfg)
        paths = cfg.get("models")
        if not isinstance(paths, list) or not paths:
            raise ValueError(f"{name}.models must list gravity model files")
        base = cfg.get("__dir__")
        self.models: list[GravityModel] = [
            load_gravity_model(
                str(
                    Path(p) if Path(p).is_absolute() or base is None else Path(base) / p
                )
            )
            for p in paths
        ]
        outputs = [j for m in self.models for j in m.output_joints]
        if sorted(outputs) != sorted(self.joint_names):
            raise ValueError(
                f"{name}: model output joints {outputs} must be exactly joints "
                f"{list(self.joint_names)}"
            )
        self.inputs: list[list[int]] = []
        self.outputs: list[list[int]] = []

    def bind(self, robot: Follower) -> None:
        super().bind(robot)
        for model in self.models:
            missing = set(model.joint_names) - set(robot.joint_names)
            if missing:
                raise ValueError(
                    f"{self.name}: a model reads joints robot {robot.name!r} lacks: "
                    f"{sorted(missing)}"
                )
        self.inputs = [
            [robot.joint_names.index(j) for j in m.joint_names] for m in self.models
        ]
        # position in `joints` of each model output
        self.outputs = [
            [self.joint_names.index(j) for j in m.output_joints] for m in self.models
        ]

    def residual(self, state: dict) -> list[float] | None:
        positions, effort = state.get("positions"), state.get(self.effort_field)
        if positions is None or effort is None:
            return None
        out = [float(effort[i]) for i in self.indices]
        for model, inputs, outputs in zip(
            self.models, self.inputs, self.outputs, strict=True
        ):
            for k, g in zip(
                outputs, model.effort_mA([positions[i] for i in inputs]), strict=True
            ):
                out[k] -= g
        return out
