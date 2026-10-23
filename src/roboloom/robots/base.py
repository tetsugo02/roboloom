"""Follower contract: joint space, limits, and the bus the robot node owns exclusively."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from ..control.device import (
    GroupSpec,
    JointDevice,
    build_laws,
    check_hardware,
    parse_groups,
)
from ..core.checks import finite, names, positive
from ..core.protocol import Envelope
from ..core.source import Features
from ..drivers.base import RobotBus

__all__ = ["Robot", "RobotBus", "check_limits"]


LIMIT_KEYS = ("min", "max", "max_speed", "max_jump")


def check_limits(joint_names: Sequence[str], limits: object, name: str) -> list[dict]:
    """Per-joint bounds: position range, soft speed clamp (units/s) and hard jump rejection (units)."""
    if not isinstance(limits, list) or len(limits) != len(joint_names):
        raise ValueError(f"{name}.limits needs {len(joint_names)} explicit bounds")
    for joint, limit in zip(joint_names, limits, strict=True):
        if not isinstance(limit, dict) or limit.get("name") != joint or not all(finite(limit.get(k)) for k in LIMIT_KEYS):
            raise ValueError(f"invalid bounds for {joint}: needs name and {', '.join(LIMIT_KEYS)}")
        if not (limit["min"] < limit["max"] and limit["max_speed"] > 0 and limit["max_jump"] > 0):
            raise ValueError(f"invalid bounds for {joint}")
    return limits


def check_health(cfg: object, dimension: int, name: str) -> dict:
    """Health limits: checked every `every_ticks`; FAULT before the motor firmware shuts down."""
    if cfg is None:
        return {}
    if not isinstance(cfg, dict):
        raise TypeError(f"{name}.health must be a mapping")
    out: dict[str, Any] = {"every_ticks": int(positive(cfg.get("every_ticks", 10), f"{name}.health.every_ticks"))}
    if "max_temperature_c" in cfg:
        out["max_temperature_c"] = positive(cfg["max_temperature_c"], f"{name}.health.max_temperature_c")
    if "max_current_mA" in cfg:
        currents = cfg["max_current_mA"]
        if not isinstance(currents, list) or len(currents) != dimension:
            raise ValueError(f"{name}.health.max_current_mA needs one value per joint")
        out["max_current_mA"] = [positive(x, f"{name}.health.max_current_mA") for x in currents]
        out["over_current_s"] = positive(cfg.get("over_current_s", 1.0), f"{name}.health.over_current_s")
    return out


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
        self.health = check_health(cfg.get("health"), len(self.joint_names), name)
        self.record_effort = bool(cfg.get("record_effort", False))
        # false: never torque on; records state only (first hardware data-path check)
        self.torque = bool(cfg.get("torque", True))
        # control: per-joint law groups; without it the bus receives plain position goals
        self.control: list[GroupSpec] | None = parse_groups(cfg["control"], self.joint_names, name) if "control" in cfg else None
        if self.control:
            build_laws(self.control, self.joint_names, cfg.get("__dir__"))  # validate law parameters now

    def device_ids(self) -> tuple[str, ...]:
        return ()

    def open_bus(self, mock: bool) -> RobotBus:
        raise RuntimeError(f"{self.name}: no bus driver; pass an opened bus instead")

    def open_device(self, mock: bool) -> RobotBus:
        """The bus, wrapped in its control-law groups when `control` is configured."""
        bus = self.open_bus(mock)
        if self.control is None:
            return bus
        return JointDevice(bus, self.joint_names, build_laws(self.control, self.joint_names, self.cfg.get("__dir__")), self.name)

    def current_limits_mA(self) -> dict[str, float]:
        """EEPROM Current Limit the node verifies, per joint (empty when the model does not declare it)."""
        return {}

    def check_hardware(self) -> None:
        if self.control:
            check_hardware(self.control, self.cfg, self.name, self.current_limits_mA())

    def safety_config(self, robot_id: str) -> dict:
        return {
            "name": self.name, "robot_id": robot_id, "limits": self.limits, "unit": self.unit,
            "control_hz": self.control_hz, "health": self.health, "torque": self.torque,
        }

    def features(self, dataset_fps: float) -> Features:
        dim = (len(self.joint_names),)
        out: Features = {"observation.state": {"dtype": "float32", "shape": dim, "names": None}}
        if self.record_effort:
            out["observation.effort"] = {"dtype": "float32", "shape": dim, "names": None}
        return out

    def frame(self, msg: Envelope | None, dataset_fps: float) -> dict[str, Any]:
        zeros = [0.0] * len(self.joint_names)
        out = {"observation.state": np.asarray(msg.payload["positions"] if msg else zeros, dtype=np.float32)}
        if self.record_effort:
            effort = msg.payload.get("currents_mA") if msg else None
            out["observation.effort"] = np.asarray(effort if effort is not None else zeros, dtype=np.float32)
        return out
