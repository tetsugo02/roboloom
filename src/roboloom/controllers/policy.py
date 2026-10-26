"""A learned policy as the robot's controller (`type: policy`).

The policy node keeps the latest sample of every observed source and, on its own timer
(`rate_hz`), sends the next joint target. When no action is queued it calls
`policy.infer` and queues the first `action_horizon` steps of the returned chunk
(synchronous chunking: while `infer` runs no command is sent and the follower's command
deadline turns into HOLD). Targets are speed-limited from what the follower holds, and
FollowerSafety checks them like any teleoperation command.

    type: policy
    robot: robot
    factory: my_lab.policies:load_act   # "module:callable" returning a Policy
    kwargs: {checkpoint: ...}
    observe: [camera, digit_left]      # inputs or sensors; the robot state is always seen
    rate_hz: 15
    action_horizon: 8
    max_speed_counts_per_s: 1024
    command_deadline_ms: 200
"""

from __future__ import annotations

import time
from collections import deque
from typing import TYPE_CHECKING, Any, ClassVar

import numpy as np

from ..core.checks import positive
from ..core.protocol import Envelope
from ..robots.base import Robot
from .base import Controller

if TYPE_CHECKING:
    from ..core.source import Recordable
    from ..inputs.base import InputDevice
    from ..policy import Policy


class PolicyController(Controller):
    uses_input: ClassVar[bool] = False

    def __init__(
        self,
        name: str,
        cfg: dict,
        source: InputDevice | None,
        robot: Robot,
        robot_id: str,
    ):
        super().__init__(name, cfg, source, robot, robot_id)
        factory = cfg.get("factory")
        if not isinstance(factory, str) or ":" not in factory:
            raise ValueError(f"{name}.factory must be 'module:callable'")
        if not isinstance(cfg.get("kwargs", {}), dict):
            raise TypeError(f"{name}.kwargs must be a mapping")
        observe = cfg.get("observe", [])
        if not isinstance(observe, list) or not all(
            isinstance(x, str) for x in observe
        ):
            raise ValueError(f"{name}.observe must be a list of input or sensor names")
        self.rate_hz = positive(cfg.get("rate_hz"), f"{name}.rate_hz")
        self.horizon = int(
            positive(cfg.get("action_horizon", 1), f"{name}.action_horizon")
        )
        self.max_speed = positive(
            cfg.get("max_speed_counts_per_s"), f"{name}.max_speed_counts_per_s"
        )
        self.policy: Policy | None = None
        self.sources: dict[str, Recordable] = {}  # set by `bind`
        self.latest: dict[str, Envelope] = {}
        self.queue: deque[np.ndarray] = deque()
        self.task = ""
        self.running = False
        self.state = "loading"
        self.error = ""
        self.infer_ms: deque[float] = deque(maxlen=20)
        self.last_target: list[float] | None = None
        self.last_ns = 0

    def observes(self) -> list[str]:
        return list(self.cfg.get("observe", []))

    def bind(self, sources: dict[str, Recordable]) -> None:
        """The specs of the observed sources, to build observations with dataset keys."""
        self.sources = {name: sources[name] for name in self.observes()}

    # -- lifecycle (the policy node calls these) --------------------------------

    def load(self, factory: str | None = None, kwargs: dict | None = None) -> None:
        """Import and build the policy; `factory`/`kwargs` override the configuration."""
        from ..policy import load_policy

        self.policy = load_policy(
            factory or self.cfg["factory"],
            self.cfg.get("kwargs", {}) if kwargs is None else kwargs,
        )
        self.state = "ready"

    def start(self, task: str) -> None:
        if self.policy is None:
            raise RuntimeError("policy not loaded")
        self.policy.reset()
        self.task, self.running = task, True
        self.queue.clear()
        self.last_target = None
        self.state = "running"

    def stop(self) -> None:
        self.running = False
        self.queue.clear()
        if self.state == "running":
            self.state = "ready"

    def reset(self) -> None:
        self.stop()

    def observe(self, name: str, msg: Envelope) -> None:
        self.latest[name] = msg

    # -- stepping ---------------------------------------------------------------

    def observation(self) -> dict[str, Any] | None:
        """Dataset-keyed observation, or None until every observed source has a sample."""
        robot = self.latest.get(self.robot.name)
        if robot is None or any(n not in self.latest for n in self.sources):
            return None
        out: dict[str, Any] = dict(self.robot.frame(robot, self.rate_hz))
        for name, spec in self.sources.items():
            out.update(spec.frame(self.latest[name], self.rate_hz))
        out["task"] = self.task
        return out

    def tick(self, now_ns: int | None = None) -> Envelope | None:
        """The next command while an episode runs; infers when no action is queued."""
        now = time.monotonic_ns() if now_ns is None else now_ns
        if not self.running or self.policy is None:
            return None
        robot = self.latest.get(self.robot.name)
        if robot is None or robot.payload.get("mode") in ("FAULT", "ESTOP"):
            return None
        if not self.queue:
            observation = self.observation()
            if observation is None:
                self.state = "waiting_observation"
                return None
            t0 = time.perf_counter()
            actions = np.asarray(self.policy.infer(observation), dtype=np.float64)
            self.infer_ms.append((time.perf_counter() - t0) * 1000)
            n = len(self.robot.joint_names)
            if actions.ndim == 1:
                actions = actions[None, :]
            if (
                actions.ndim != 2
                or actions.shape[1] != n
                or not np.isfinite(actions).all()
            ):
                raise ValueError(
                    f"policy returned shape {actions.shape}; expected [{n}] or [H, {n}], finite"
                )
            self.queue.extend(actions[: self.horizon])
            self.state = "running"
            now = time.monotonic_ns()
        target = self.queue.popleft()
        # step from what the follower holds, as the joint controller does
        previous = list(robot.payload.get("target") or robot.payload["positions"])
        dt = max((now - self.last_ns) / 1e9, 1e-6) if self.last_ns else 1 / self.rate_hz
        step = self.max_speed * min(dt, 2 / self.rate_hz)
        limited = [
            max(p - step, min(p + step, float(t)))
            for p, t in zip(previous, target, strict=True)
        ]
        self.last_target, self.last_ns = limited, now
        return self.command(limited, now)

    def update(
        self,
        intent: Envelope,
        follower: list[float],
        now_ns: int | None = None,
        follower_target: list[float] | None = None,
    ) -> Envelope | None:
        raise TypeError(f"{self.name}: a policy controller is stepped by `tick`")

    def status(self) -> dict:
        out: dict = {"state": self.state, "queued": len(self.queue)}
        if self.infer_ms:
            out["infer_ms"] = round(self.infer_ms[-1], 1)
            out["infer_max_ms"] = round(max(self.infer_ms), 1)
        if self.error:
            out["error"] = self.error
        return out
