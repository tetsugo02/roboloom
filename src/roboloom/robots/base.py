"""Follower contract: joint space, limits, and the bus the robot node owns exclusively."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

import numpy as np

from ..core.checks import finite, names, positive
from ..core.protocol import Envelope
from ..core.source import Features


class RobotBus(Protocol):
    def read_positions(self) -> list[float]: ...
    def write_positions(self, values: list[float]) -> None: ...
    def enable_torque(self) -> None: ...
    def close(self) -> None: ...


def check_limits(joint_names: Sequence[str], limits: object, name: str) -> list[dict]:
    if not isinstance(limits, list) or len(limits) != len(joint_names):
        raise ValueError(f"{name}.limits needs {len(joint_names)} explicit bounds")
    for joint, limit in zip(joint_names, limits, strict=True):
        if not isinstance(limit, dict) or limit.get("name") != joint or not all(finite(limit.get(k)) for k in ("min", "max", "max_step")) or not (limit["min"] < limit["max"] and limit["max_step"] > 0):
            raise ValueError(f"invalid bounds for {joint}")
    return limits


class Robot:
    """Joint-position follower. Used directly when the caller supplies the bus.

    Models subclass this with fixed joint names and unit and implement `open_bus`.
    """

    robot_type = "external"

    def __init__(self, name: str, cfg: dict, joint_names: Sequence[str] | None = None, unit: str | None = None):
        self.name, self.cfg = name, cfg
        self.joint_names = names(cfg.get("joints") if joint_names is None else joint_names, f"{name}.joints")
        self.unit = unit or cfg.get("unit", "dynamixel_count")
        self.control_hz = positive(cfg.get("control_hz"), f"{name}.control_hz")
        self.limits = check_limits(self.joint_names, cfg.get("limits"), name)

    def device_ids(self) -> tuple[str, ...]:
        return ()

    def open_bus(self, mock: bool) -> RobotBus:
        raise RuntimeError(f"{self.name}: no bus driver; pass an opened bus instead")

    def safety_config(self, robot_id: str) -> dict:
        return {"name": self.name, "robot_id": robot_id, "limits": self.limits, "unit": self.unit}

    def features(self, dataset_fps: float) -> Features:
        return {"observation.state": {"dtype": "float32", "shape": (len(self.joint_names),), "names": None}}

    def frame(self, msg: Envelope | None, dataset_fps: float) -> dict[str, Any]:
        values = msg.payload["positions"] if msg else [0] * len(self.joint_names)
        return {"observation.state": np.asarray(values, dtype=np.float32)}
