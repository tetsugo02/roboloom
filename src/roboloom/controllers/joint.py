"""Joint-to-joint mapping with start-up alignment and a speed limit."""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from typing import ClassVar

from ..control.homing import HomeSpec, parse_home
from ..control.takeover import JointPickup
from ..core.checks import positions, positive
from ..core.protocol import Envelope
from ..errors import ConfigError
from ..inputs.base import InputDevice, JointInput
from ..robots.base import Follower
from .base import Controller, FollowerView
from .coupling import JointCouplings
from .feedback import FeedbackMap


class JointController(Controller):
    """One leader's joints onto one follower's joints."""

    max_followers: ClassVar[int | None] = 1

    def __init__(
        self,
        name: str,
        cfg: dict,
        source: InputDevice,
        followers: Mapping[str, Follower],
    ):
        super().__init__(name, cfg, source, followers)
        robot = self.follower
        if not isinstance(source, JointInput):
            raise TypeError(
                f"{name}: joint controller cannot map {type(source).__name__} input {source.name!r}"
            )
        if not cfg.get("unit") == source.unit == robot.unit:
            raise ValueError(
                f"{name}: unit must match input {source.unit!r} and robot {robot.unit!r}"
            )
        mapping = cfg.get("joints")
        if not isinstance(mapping, list) or not all(
            isinstance(j, dict) for j in mapping
        ):
            raise ValueError(
                f"{name} needs a complete, ordered, one-to-one joint mapping"
            )
        leaders = [j.get("leader") for j in mapping]
        if (
            [j.get("follower") for j in mapping] != list(robot.joint_names)
            or len(set(leaders)) != len(leaders)
            or not set(leaders) <= set(source.joint_names)
        ):
            raise ValueError(
                f"{name} needs a complete, ordered, one-to-one joint mapping"
            )
        for j in mapping:
            if (
                j.get("sign") not in (-1, 1)
                or not isinstance(j.get("offset"), (int, float))
                or not math.isfinite(j["offset"])
            ):
                raise ValueError("joint sign must be +/-1 and offset finite")
        if "max_speed_counts_per_s" in cfg:
            raise ConfigError(
                f"{name}.max_speed_counts_per_s was renamed: use max_speed "
                f"({robot.unit}/s, the follower's unit)"
            )
        for field in ("alignment_tolerance", "max_speed", "input_timeout_ms"):
            positive(cfg.get(field), f"{name}.{field}")
        self.source_joints = source.joint_names
        self.couplings = JointCouplings(
            cfg.get("couplings", []), robot.joint_names, name
        )
        home = parse_home(
            cfg.get("home"),
            name,
            cfg.get("__dir__"),
            robot,
            cfg["max_speed"],
        )
        if home is not None:
            self.homes[robot.name] = home
        if "feedback" in cfg:
            self.feedback = FeedbackMap(cfg["feedback"], name, mapping)
        self.last_seq = -1
        self.last_boot: str | None = None
        self.last_target: list[float] | None = None
        self.last_target_ns = 0
        self.aligned = False
        self.state = "waiting_input"
        # Joint farthest from the leader at the last update, also while following: every
        # start is checked against it, not only the first alignment.
        self.worst: tuple[str, float] | None = None
        # a takeover in progress (`begin_takeover`): joints hold until the leader reaches them
        self.pickup: JointPickup | None = None

    def reset(self) -> None:
        self.aligned = False
        self.pickup = None
        self.state = "follower_fault"

    def begin_takeover(self, views: Mapping[str, FollowerView]) -> None:
        """Take the follower over from the target it holds: each joint holds until the
        leader's mapped value comes within `alignment_tolerance` of it or crosses it."""
        view = views[self.follower.name]
        held = list(view.target or view.positions)
        self.pickup = JointPickup(held, self.cfg["alignment_tolerance"])
        self.aligned = True
        self.last_target, self.last_target_ns = held, time.monotonic_ns()
        self.state = "picking_up"

    def leader_pose(self, follower: list[float]) -> dict[str, float]:
        """Leader joint values that map onto `follower` (a pose at rest): the inverse of
        the joint map, couplings included, so the controller sees no difference there."""
        added = self.couplings.apply([0.0] * len(follower), follower)
        return {
            j["leader"]: j["sign"] * (f - j["offset"] - extra)
            for j, f, extra in zip(self.cfg["joints"], follower, added, strict=True)
        }

    @property
    def home(self) -> HomeSpec | None:
        """The follower's saved pose `home` moves to (with the leader), if configured."""
        return self.homes.get(self.follower.name)

    def status(self) -> dict:
        out: dict = {"state": self.state, "tolerance": self.cfg["alignment_tolerance"]}
        if self.home is not None:
            out["home"] = self.home.pose.name
        if self.pickup is not None and not self.pickup.done:
            names = self.follower.joint_names
            out["pickup"] = {
                names[i]: float(f"{d:.4g}")
                for i, d in enumerate(self.pickup.remaining)
                if not self.pickup.caught[i]
            }
        if self.worst is not None and self.state in ("aligning", "following"):
            out["worst_joint"], out["worst_diff"] = (
                self.worst[0],
                float(f"{self.worst[1]:.4g}"),  # 4 significant digits in any unit
            )
        if self.feedback is not None:
            out["feedback_gate"] = self.feedback.gate
            if self.feedback.error:
                out["feedback_error"] = self.feedback.error
        return out

    def update(
        self,
        intent: Envelope,
        views: Mapping[str, FollowerView],
        now_ns: int | None = None,
    ) -> dict[str, Envelope]:
        view = views[self.follower.name]
        command = self.step(
            intent,
            view.positions,
            now_ns,
            follower_target=view.target,
            follower_velocity=view.velocities,
        )
        return {} if command is None else {self.follower.name: command}

    def step(
        self,
        intent: Envelope,
        follower: list[float],
        now_ns: int | None = None,
        follower_target: list[float] | None = None,
        follower_velocity: list[float] | None = None,
    ) -> Envelope | None:
        """The next command for the follower at `follower`, or None while it must not
        move (input stale, not aligned yet)."""
        now = time.monotonic_ns() if now_ns is None else now_ns
        if (
            intent.kind != JointInput.kind
            or now - intent.t_ready_ns > self.cfg["input_timeout_ms"] * 1e6
            or intent.t_ready_ns > now
        ):
            # a takeover keeps holding its joints; it resumes when the input is back
            self.aligned = self.pickup is not None
            self.state = "input_stale"
            return None
        if intent.boot_id != self.last_boot:
            self.last_boot, self.last_seq = intent.boot_id, -1
            self.aligned = self.pickup is not None
        if intent.seq <= self.last_seq:
            return None
        self.last_seq = intent.seq
        incoming = positions(intent.payload["positions"], len(self.source_joints))
        by_name = dict(zip(self.source_joints, incoming, strict=True))
        target = [
            by_name[j["leader"]] * j["sign"] + j["offset"] for j in self.cfg["joints"]
        ]
        current = positions(follower, len(self.follower.joint_names))
        target = self.couplings.apply(target, current, follower_velocity)
        if self.pickup is not None:  # joints not reached yet keep their held value
            target = self.pickup.apply(target)
            if self.pickup.done:
                self.pickup = None
        diffs = [abs(a - b) for a, b in zip(target, current, strict=True)]
        worst = max(range(len(diffs)), key=diffs.__getitem__)
        self.worst = (self.follower.joint_names[worst], diffs[worst])
        if not self.aligned:
            if diffs[worst] > self.cfg["alignment_tolerance"]:
                self.state = "aligning"
                return None
            self.aligned = True
            self.last_target = current
            self.last_target_ns = now
        dt = max((now - self.last_target_ns) / 1e9, 1e-6)
        step = self.cfg["max_speed"] * dt
        # Step from what the follower holds, not from our own last output: while it is
        # not armed (or refuses a command) our targets would otherwise run ahead of it.
        previous = (
            list(follower_target) if follower_target is not None else self.last_target
        )
        if previous is None:
            raise RuntimeError("controller target missing after alignment")
        limited = [
            max(p - step, min(p + step, t))
            for p, t in zip(previous, target, strict=True)
        ]
        self.last_target, self.last_target_ns = limited, now
        self.state = "picking_up" if self.pickup is not None else "following"
        return self.command(self.follower.name, limited, now, input_seq=intent.seq)
