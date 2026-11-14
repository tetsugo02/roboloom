"""A hand-held pose onto an arm's joints through inverse kinematics (`type: pose_ik`).

The mapping is relative, as the vendor's Pika teleoperation does: when the operator
engages (a rising `engaged` of the pose input), the controller keeps the input's pose
T_s0 and the arm's tool pose T_a0 (forward kinematics of the target the arm holds), and
from then on commands `T_a0 · inv(T_s0) · T_s`. No calibration between the tracker's
world and the arm's base is needed; the hand's motion, in the input's own frame, moves
the tool in the tool's frame.

    type: pose_ik
    input: left_sense
    followers: [left, left_gripper]
    arm: left                     # the follower whose kinematics() the IK solves
    gripper: left_gripper         # optional: a one-joint follower set from the jaw angle
    tool_offset: {xyz: [0, 0, 0.19], rpy: [0, -1.5708, 0]}  # tool frame on the flange
    workspace: {min: [x, y, z], max: [x, y, z]}  # m, in the arm's base frame
    max_input_jump: {position_m: 0.05, rotation_rad: 0.5}
    ik: {iterations: 30, damping: 0.001, position_tolerance_m: 0.005,
         rotation_tolerance_rad: 0.05}
    gripper_map: {scale: 1.0, offset: 0.0}
    max_speed: {left: 1.5, left_gripper: 3.0}  # per follower, in its unit/s
    home: {left: {pose: ../poses/left/ready.yaml, max_speed: 0.5, tolerance: 0.02}}
    command_deadline_ms: 100
    input_timeout_ms: 150

Nothing is sent (the followers hold) while the target leaves `workspace` or the IK does
not reach it. Teleoperation stops, and waits for the operator to engage again, when the
pose is lost or stale, when it jumps by more than `max_input_jump` between samples, while
a follower moves home, and after `reset()` (a follower latched FAULT or ESTOP). `home`
gives followers a saved pose to move to (`Move home` on the operator screen) while the
operator has not engaged; an arm folded at its rest pose is usually not where the IK can
follow a hand.
"""

from __future__ import annotations

import math
import time
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from ..control.homing import parse_home
from ..core.checks import positive
from ..core.protocol import Envelope
from ..inputs.base import InputDevice, PoseInput
from ..kinematics.spec import (
    Pose,
    invert,
    pose_from,
    pose_xyz_rpy,
    rotation_angle,
)
from ..robots.base import Follower
from .base import Controller, FollowerView

IK_DEFAULTS = {
    "iterations": 30,
    "damping": 1e-3,
    "position_tolerance_m": 0.005,
    "rotation_tolerance_rad": 0.05,
}


def _vector(value: Any, size: int, where: str) -> list[float]:
    if (
        not isinstance(value, list)
        or len(value) != size
        or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            for v in value
        )
    ):
        raise ValueError(f"{where}: expected {size} numbers")
    return [float(v) for v in value]


def _mapping(cfg: dict, key: str, where: str) -> dict:
    value = cfg.get(key)
    if not isinstance(value, dict):
        raise TypeError(f"{where}.{key}: expected a mapping")
    return value


class PoseIkController(Controller):
    def __init__(
        self,
        name: str,
        cfg: dict,
        source: InputDevice,
        followers: Mapping[str, Follower],
    ):
        super().__init__(name, cfg, source, followers)
        if not isinstance(source, PoseInput):
            raise TypeError(
                f"{name}: pose_ik maps a pose input, not {type(source).__name__} "
                f"{source.name!r}"
            )
        self.arm = cfg.get("arm")
        self.gripper = cfg.get("gripper")
        wanted = [self.arm, *([self.gripper] if self.gripper is not None else [])]
        if self.arm not in self.followers or sorted(map(str, wanted)) != sorted(
            self.followers
        ):
            raise ValueError(
                f"{name}: arm (and gripper) must name exactly its followers "
                f"{list(self.followers)}"
            )
        arm = self.followers[str(self.arm)]
        spec = arm.kinematics()
        if spec is None:
            raise ValueError(f"{name}.arm: {arm.model} has no kinematic model")
        if spec.names != tuple(arm.joint_names):
            raise ValueError(f"{name}.arm: the model's joints differ from {arm.name}'s")
        self.spec = spec
        if (
            self.gripper is not None
            and len(self.followers[self.gripper].joint_names) != 1
        ):
            raise ValueError(f"{name}.gripper: expected a follower with one joint")
        offset = _mapping(cfg, "tool_offset", name)
        self.tool = pose_xyz_rpy(
            _vector(offset.get("xyz"), 3, f"{name}.tool_offset.xyz"),
            _vector(offset.get("rpy"), 3, f"{name}.tool_offset.rpy"),
        )
        box = _mapping(cfg, "workspace", name)
        self.low = np.asarray(_vector(box.get("min"), 3, f"{name}.workspace.min"))
        self.high = np.asarray(_vector(box.get("max"), 3, f"{name}.workspace.max"))
        if not np.all(self.low < self.high):
            raise ValueError(f"{name}.workspace: min must be below max on every axis")
        jump = _mapping(cfg, "max_input_jump", name)
        self.jump_m = positive(
            jump.get("position_m"), f"{name}.max_input_jump.position_m"
        )
        self.jump_rad = positive(
            jump.get("rotation_rad"), f"{name}.max_input_jump.rotation_rad"
        )
        ik = {**IK_DEFAULTS, **(cfg.get("ik") or {})}
        unknown = set(ik) - set(IK_DEFAULTS)
        if unknown:
            raise ValueError(f"{name}.ik: unknown keys {sorted(unknown)}")
        for key in IK_DEFAULTS:
            positive(ik[key], f"{name}.ik.{key}")
        self.ik = {**ik, "iterations": int(ik["iterations"])}
        grip = cfg.get("gripper_map") or {}
        self.grip_scale = float(grip.get("scale", 1.0))
        self.grip_offset = float(grip.get("offset", 0.0))
        speeds = _mapping(cfg, "max_speed", name)
        if sorted(speeds) != sorted(self.followers):
            raise ValueError(f"{name}.max_speed: one value per follower")
        self.max_speed = {
            f: positive(v, f"{name}.max_speed.{f}") for f, v in speeds.items()
        }
        self.input_timeout_ms = positive(
            cfg.get("input_timeout_ms"), f"{name}.input_timeout_ms"
        )
        homes = cfg.get("home") or {}
        if not isinstance(homes, dict) or not set(homes) <= set(self.followers):
            raise ValueError(f"{name}.home: a mapping of its followers to home poses")
        for f, raw in homes.items():
            home = parse_home(
                raw,
                f"{name}.home.{f}",
                cfg.get("__dir__"),
                self.followers[f],
                self.max_speed[f],
            )
            if home is not None:
                self.homes[f] = home
        self.limits = {
            f: (
                [lim["min"] for lim in follower.limits],
                [lim["max"] for lim in follower.limits],
            )
            for f, follower in self.followers.items()
        }
        from ..kinematics.ik import ArmModel

        self.model = ArmModel(spec, self.tool)
        self.anchor: Pose | None = None  # T_a0 · inv(T_s0) while engaged
        self.previous: Pose | None = None  # the last input pose while engaged
        self.was_engaged = False
        self.last_boot, self.last_seq = "", -1
        self.last_ns: dict[str, int] = {}  # when each follower's last step was taken
        self.last_input_ns = 0  # t_ready of the last accepted input
        self.state = "waiting_input"
        self.errors: tuple[float, float] | None = None

    # -- state ------------------------------------------------------------------------

    def check_hardware(self) -> None:
        """Refuse real hardware while the arm's joint map is not confirmed."""
        if not self.spec.confirmed:
            raise ValueError(
                f"{self.name}.arm: the kinematic joint map of {self.arm} is not "
                "confirmed (zeros and directions; set confirmed: true in its "
                "calibration file after checking each joint on the robot)"
            )

    def _stop(self, state: str) -> dict[str, Envelope]:
        """Stop following; the operator engages again to continue."""
        self.anchor = self.previous = None
        self.state = state
        return {}

    def reset(self) -> None:
        self._stop("follower_fault")

    def status(self) -> dict:
        out: dict = {"state": self.state, "engaged": self.anchor is not None}
        if self.errors is not None:
            out["position_error_mm"] = round(self.errors[0] * 1000, 1)
            out["rotation_error_deg"] = round(math.degrees(self.errors[1]), 1)
        return out

    # -- one step ---------------------------------------------------------------------

    def _held(self, view: FollowerView) -> list[float]:
        return list(view.target if view.target is not None else view.positions)

    def _withhold(self, now: int) -> dict[str, Envelope]:
        """Send nothing now; the followers hold, so no speed budget builds up meanwhile."""
        self.last_ns = dict.fromkeys(self.followers, now)
        return {}

    def _limited(
        self, follower: str, target: Sequence[float], view: FollowerView, now: int
    ) -> list[float]:
        last = self.last_ns.get(follower, now)
        # never more than one input period's worth of motion in one command
        dt = min(max((now - last) / 1e9, 1e-6), self.input_timeout_ms / 1000)
        step = self.max_speed[follower] * dt
        self.last_ns[follower] = now
        return [
            max(p - step, min(p + step, t))
            for p, t in zip(self._held(view), target, strict=True)
        ]

    def update(
        self,
        intent: Envelope,
        views: Mapping[str, FollowerView],
        now_ns: int | None = None,
    ) -> dict[str, Envelope]:
        now = time.monotonic_ns() if now_ns is None else now_ns
        if (
            intent.kind != PoseInput.kind
            or now - intent.t_ready_ns > self.input_timeout_ms * 1e6
            or intent.t_ready_ns > now
        ):
            return self._stop("input_stale")
        if intent.boot_id != self.last_boot:
            self.last_boot, self.last_seq = intent.boot_id, -1
            self._stop("waiting_input")
        if intent.seq <= self.last_seq:
            return {}
        self.last_seq = intent.seq
        # a gap in delivery longer than the timeout is a stale input too, even when the
        # packet that ends it is fresh: the operator engages again
        gap = intent.t_ready_ns - self.last_input_ns
        self.last_input_ns = intent.t_ready_ns
        if self.anchor is not None and gap > self.input_timeout_ms * 1e6:
            return self._stop("input_stale")
        p = intent.payload
        # the device's own clutch: following starts only on its rising edge, so after
        # any stop the operator disengages and engages again
        engaged = bool(p["engaged"])
        rising = engaged and not self.was_engaged
        self.was_engaged = engaged
        if not p["tracking"]:
            return self._stop("tracking_lost")
        if not engaged:
            return self._stop("ready")
        if any(views[f].mode == "HOMING" for f in self.followers):
            return self._stop("homing")
        sense = pose_from(p["position"], p["quaternion"])
        arm = str(self.arm)
        if self.anchor is None:
            if not rising:
                return {}  # stopped while engaged: wait for the operator to engage again
            start = self.model.fk(self.spec.to_model(self._held(views[arm])))
            self.anchor = start @ invert(sense)
            self.last_ns = {}
        elif self.previous is not None:
            delta = invert(self.previous) @ sense
            if (
                np.linalg.norm(delta[:3, 3]) > self.jump_m
                or rotation_angle(delta[:3, :3]) > self.jump_rad
            ):
                return self._stop("input_jump")
        self.previous = sense
        target = self.anchor @ sense
        if np.any(target[:3, 3] < self.low) or np.any(target[:3, 3] > self.high):
            self.state = "out_of_workspace"
            return self._withhold(now)
        # the IK works in the URDF's rad; the follower's unit only at its two ends
        low, high = self.spec.model_limits(*self.limits[arm])
        seed = self.spec.to_model(self._held(views[arm]))
        result = self.model.solve(target, seed, low, high, **self.ik)
        self.errors = (result.position_error_m, result.rotation_error_rad)
        if not result.reached:
            self.state = "unreachable"
            return self._withhold(now)
        out = {
            arm: self.command(
                arm,
                self._limited(arm, self.spec.from_model(result.q), views[arm], now),
                now,
                input_seq=intent.seq,
            )
        }
        if self.gripper is not None and p.get("gripper") is not None:
            (lo,), (hi,) = self.limits[self.gripper]
            opening = self.grip_scale * float(p["gripper"]) + self.grip_offset
            wanted = [min(hi, max(lo, opening))]
            out[self.gripper] = self.command(
                self.gripper,
                self._limited(self.gripper, wanted, views[self.gripper], now),
                now,
                input_seq=intent.seq,
            )
        self.state = "following"
        return out
