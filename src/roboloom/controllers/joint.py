"""Joint-to-joint mapping with start-up alignment and a speed limit."""

from __future__ import annotations

import math
import time

from ..core.checks import positions, positive
from ..core.protocol import Envelope
from ..inputs.base import InputDevice, JointInput
from ..robots.base import Robot
from .base import Controller


class JointController(Controller):
    def __init__(self, name: str, cfg: dict, source: InputDevice, robot: Robot, robot_id: str):
        super().__init__(name, cfg, source, robot, robot_id)
        if not isinstance(source, JointInput):
            raise TypeError(f"{name}: joint controller cannot map {type(source).__name__} input {source.name!r}")
        if not cfg.get("unit") == source.unit == robot.unit:
            raise ValueError(f"{name}: unit must match input {source.unit!r} and robot {robot.unit!r}")
        mapping = cfg.get("joints")
        if not isinstance(mapping, list) or not all(isinstance(j, dict) for j in mapping):
            raise ValueError(f"{name} needs a complete, ordered, one-to-one joint mapping")
        leaders = [j.get("leader") for j in mapping]
        if [j.get("follower") for j in mapping] != list(robot.joint_names) or len(set(leaders)) != len(leaders) or not set(leaders) <= set(source.joint_names):
            raise ValueError(f"{name} needs a complete, ordered, one-to-one joint mapping")
        for j in mapping:
            if j.get("sign") not in (-1, 1) or not isinstance(j.get("offset"), (int, float)) or not math.isfinite(j["offset"]):
                raise ValueError("joint sign must be +/-1 and offset finite")
        for field in ("alignment_tolerance", "max_speed_counts_per_s", "input_timeout_ms"):
            positive(cfg.get(field), f"{name}.{field}")
        self.source_joints = source.joint_names
        self.last_seq = -1
        self.last_boot: str | None = None
        self.last_target: list[float] | None = None
        self.last_target_ns = 0
        self.aligned = False

    def reset(self) -> None:
        self.aligned = False

    def update(self, intent: Envelope, follower: list[float], now_ns: int | None = None) -> Envelope | None:
        now = time.monotonic_ns() if now_ns is None else now_ns
        if (
            intent.kind != JointInput.kind
            or now - intent.t_ready_ns > self.cfg["input_timeout_ms"] * 1e6
            or intent.t_ready_ns > now
        ):
            self.aligned = False
            return None
        if intent.boot_id != self.last_boot:
            self.last_boot, self.last_seq = intent.boot_id, -1
            self.aligned = False
        if intent.seq <= self.last_seq:
            return None
        self.last_seq = intent.seq
        incoming = positions(intent.payload["positions"], len(self.source_joints))
        by_name = dict(zip(self.source_joints, incoming, strict=True))
        target = [by_name[j["leader"]] * j["sign"] + j["offset"] for j in self.cfg["joints"]]
        current = positions(follower, len(self.robot.joint_names))
        if not self.aligned:
            if max(abs(a - b) for a, b in zip(target, current, strict=True)) > self.cfg["alignment_tolerance"]:
                return None
            self.aligned = True
            self.last_target = current
            self.last_target_ns = now
        dt = max((now - self.last_target_ns) / 1e9, 1e-6)
        step = self.cfg["max_speed_counts_per_s"] * dt
        previous = self.last_target
        if previous is None:
            raise RuntimeError("controller target missing after alignment")
        limited = [max(p - step, min(p + step, t)) for p, t in zip(previous, target, strict=True)]
        self.last_target, self.last_target_ns = limited, now
        return self.command(limited, now, input_seq=intent.seq)
