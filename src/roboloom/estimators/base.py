"""Effort estimator contract: the effort a follower spends against the outside.

An estimator reads one robot's `state` and publishes, per follower joint, the residual
`measured - predicted for free motion` in the robot's effort unit (Dynamixel: mA), plus a
contact flag. External force acts along `-residual`. Controllers map the estimate to
leader feedback (`roboloom.controllers.feedback`); only `residual` is model specific.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

import numpy as np

from ..core.checks import finite, identity, names
from ..core.protocol import Envelope
from ..core.source import Features
from ..errors import ConfigError
from ..robots.base import Follower

STATE_FIELDS = (
    "positions",
    "velocities",
    "target",
)  # every follower_state carries these


@dataclass
class Estimate:
    residual: list[float]  # measured - predicted for free motion, per joint
    contact: bool
    valid: bool  # False: no estimate (no model, missing state); feedback stays closed


class Estimator(ABC):
    kind: ClassVar[str] = "effort_estimate"
    # follower_state fields `residual` reads besides the follower's effort signal
    needs: ClassVar[tuple[str, ...]] = ()

    def __init__(self, name: str, cfg: dict):
        self.name, self.cfg = name, cfg
        if "robot" in cfg:
            raise ConfigError(f"{name}.robot was renamed: use follower: <follower>")
        self.follower = identity(cfg.get("follower"), f"{name}.follower")
        self.joint_names = names(cfg.get("joints"), f"{name}.joints")
        alpha = cfg.get("smoothing_alpha", 1.0)
        if not finite(alpha) or not 0 < alpha <= 1:
            raise ValueError(f"{name}.smoothing_alpha must be in (0, 1]")
        self.alpha = float(alpha)
        # contact: hysteresis on the L1 norm of the residual (0 and 0: always in contact)
        on, off = cfg.get("contact_on", 0.0), cfg.get("contact_off", 0.0)
        if not (finite(on) and finite(off) and 0 <= off <= on):
            raise ValueError(f"{name}: needs 0 <= contact_off <= contact_on")
        self.contact_on, self.contact_off = float(on), float(off)
        # record: estimates become dataset features (see `features`)
        self.record = bool(cfg.get("record", False))
        self.effort_field = ""
        self.unit = ""
        self.indices: list[int] = []
        self.reset()

    def bind(self, robot: Follower) -> None:
        """Check the follower this estimator reads and take its effort signal and unit."""
        if robot.effort_signal is None:
            raise ValueError(
                f"{self.name}: follower {robot.name!r} reports no effort to estimate from"
            )
        missing = set(self.joint_names) - set(robot.joint_names)
        if missing:
            raise ValueError(
                f"{self.name}: joints {sorted(missing)} are not joints of follower {robot.name!r}"
            )
        unknown = set(self.needs) - set(STATE_FIELDS)
        if unknown:
            raise ValueError(f"{self.name}: follower state has no {sorted(unknown)}")
        self.effort_field, self.unit = robot.effort_signal
        self.indices = [robot.joint_names.index(j) for j in self.joint_names]

    def reset(self) -> None:
        self.smoothed: list[float] | None = None
        self.contact = False

    @abstractmethod
    def residual(self, state: dict) -> list[float] | None:
        """Residual per joint from a `follower_state` payload, or None when it cannot be told."""

    def update(self, state: dict) -> Estimate:
        raw = self.residual(state)
        if raw is None:
            self.reset()
            return Estimate([0.0] * len(self.joint_names), False, False)
        if self.smoothed is None:
            self.smoothed = list(raw)
        else:
            self.smoothed = [
                self.alpha * r + (1 - self.alpha) * s
                for r, s in zip(raw, self.smoothed, strict=True)
            ]
        norm = sum(abs(r) for r in self.smoothed)
        self.contact = norm >= (self.contact_off if self.contact else self.contact_on)
        return Estimate(list(self.smoothed), self.contact, True)

    def encode(self, estimate: Estimate, robot_t_ns: int) -> dict:
        return {
            "follower": self.follower,
            "joints": list(self.joint_names),
            "unit": self.unit,
            "residual": estimate.residual,
            "contact": estimate.contact,
            "valid": estimate.valid,
            "robot_t_ns": robot_t_ns,
        }

    def features(self, dataset_fps: float) -> Features:
        """External effort (`-residual`, estimator unit), its validity and contact."""
        one = {"dtype": "float32", "shape": (1,), "names": None}
        return {
            "observation.effort_ext": {
                "dtype": "float32",
                "shape": (len(self.joint_names),),
                "names": None,
            },
            "observation.effort_ext.valid": one,
            "observation.contact": one,
        }

    def frame(self, msg: Envelope | None, dataset_fps: float) -> dict[str, Any]:
        valid = msg is not None and bool(msg.payload.get("valid"))
        effort = (
            [-float(r) for r in msg.payload["residual"]]
            if msg is not None and valid
            else [0.0] * len(self.joint_names)
        )
        contact = valid and msg is not None and bool(msg.payload.get("contact"))
        return {
            "observation.effort_ext": np.asarray(effort, dtype=np.float32),
            "observation.effort_ext.valid": np.asarray([valid], dtype=np.float32),
            "observation.contact": np.asarray([contact], dtype=np.float32),
        }


class NoEstimator(Estimator):
    """Never estimates: the feedback path runs end to end with the gate closed."""

    def residual(self, state: dict) -> list[float] | None:
        return None
