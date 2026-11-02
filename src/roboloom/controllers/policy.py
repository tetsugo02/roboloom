"""A learned policy as the robot's controller (`type: policy`).

The policy drives every follower of the robot (`followers:` lists them all, in
configuration order): its observation and action have the recorded layout, so
`observation.state` and the action join the followers in that order (`recording.schema`).
The policy node keeps the latest sample of every observed source and, on its own timer
(`rate_hz`), sends each follower its part of the next action. When no action is queued
it calls `policy.infer` and queues the first `action_horizon` steps of the returned chunk
(synchronous chunking: while `infer` runs no command is sent and the followers' command
deadlines turn into HOLD). Targets are speed-limited from what each follower holds, and
FollowerSafety checks them like any teleoperation command.

    type: policy
    followers: [follower]               # every follower, in configuration order
    factory: my_lab.policies:load_act   # "module:callable" returning a Policy
    kwargs: {checkpoint: ...}
    observe: [camera, digit_left]      # inputs or sensors; follower states are always seen
    rate_hz: 15
    action_horizon: 8
    max_speed: {follower: 1024}         # per follower, in its unit/s
    command_deadline_ms: 200
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar

import numpy as np

from ..core.checks import positive
from ..core.protocol import Envelope
from ..errors import ConfigError
from ..robots.base import Follower
from .base import Controller, FollowerView

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
        followers: Mapping[str, Follower],
    ):
        super().__init__(name, cfg, source, followers)
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
        if "max_speed_counts_per_s" in cfg:
            raise ConfigError(
                f"{name}.max_speed_counts_per_s was renamed: use max_speed, one value "
                "per follower in its unit/s: {follower: ...}"
            )
        speeds = cfg.get("max_speed")
        if not isinstance(speeds, dict) or set(speeds) != set(self.followers):
            raise ValueError(
                f"{name}.max_speed: one value per follower, in that follower's unit/s "
                f"({', '.join(f'{n}: <{f.unit}/s>' for n, f in self.followers.items())})"
            )
        # followers differ in unit (rad, m, counts): never one speed for all of them
        self.max_speed = {
            n: positive(v, f"{name}.max_speed.{n}") for n, v in speeds.items()
        }
        self.policy: Policy | None = None
        self.sources: dict[str, Recordable] = {}  # set by `bind`
        self.dataset_fps = 30.0  # set by `bind`
        self.latest: dict[str, Envelope] = {}
        self.queue: deque[np.ndarray] = deque()
        self.task = ""
        self.running = False
        self.state = "loading"
        self.error = ""
        self.infer_ms: deque[float] = deque(maxlen=20)
        self.last_ns = 0

    def observes(self) -> list[str]:
        return list(self.cfg.get("observe", []))

    def bind(self, sources: dict[str, Recordable], dataset_fps: float) -> None:
        """The specs of the observed sources and the dataset rate, so observations have
        exactly the keys and shapes of the recorded rows (`recording.schema`)."""
        self.sources = {name: sources[name] for name in self.observes()}
        self.dataset_fps = dataset_fps

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
        self.last_ns = 0
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
        from ..recording.schema import observation_frame

        sources = {**self.followers, **self.sources}
        if any(n not in self.latest for n in sources):
            return None
        out = observation_frame(sources, self.latest, self.dataset_fps)
        out["task"] = self.task
        return out

    def tick(self, now_ns: int | None = None) -> dict[str, Envelope]:
        """The next command per follower while an episode runs; infers when no action
        is queued. Nothing while a follower has no state yet or latched FAULT/ESTOP."""
        now = time.monotonic_ns() if now_ns is None else now_ns
        if not self.running or self.policy is None:
            return {}
        states = {name: self.latest.get(name) for name in self.followers}
        if any(
            s is None or s.payload.get("mode") in ("FAULT", "ESTOP")
            for s in states.values()
        ):
            return {}
        if not self.queue:
            observation = self.observation()
            if observation is None:
                self.state = "waiting_observation"
                return {}
            t0 = time.perf_counter()
            actions = np.asarray(self.policy.infer(observation), dtype=np.float64)
            self.infer_ms.append((time.perf_counter() - t0) * 1000)
            n = sum(len(f.joint_names) for f in self.followers.values())
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
        action = self.queue.popleft()
        dt = max((now - self.last_ns) / 1e9, 1e-6) if self.last_ns else 1 / self.rate_hz
        span = min(dt, 2 / self.rate_hz)
        out: dict[str, Envelope] = {}
        start = 0
        for name, follower in self.followers.items():
            part = action[start : start + len(follower.joint_names)]
            start += len(follower.joint_names)
            payload = states[name].payload  # type: ignore[union-attr]  # checked above
            # step from what the follower holds, as the joint controller does
            previous = list(payload.get("target") or payload["positions"])
            step = self.max_speed[name] * span
            limited = [
                max(p - step, min(p + step, float(x)))
                for p, x in zip(previous, part, strict=True)
            ]
            out[name] = self.command(name, limited, now)
        self.last_ns = now
        return out

    def update(
        self,
        intent: Envelope,
        views: Mapping[str, FollowerView],
        now_ns: int | None = None,
    ) -> dict[str, Envelope]:
        raise TypeError(f"{self.name}: a policy controller is stepped by `tick`")

    def status(self) -> dict:
        out: dict = {"state": self.state, "queued": len(self.queue)}
        if self.infer_ms:
            out["infer_ms"] = round(self.infer_ms[-1], 1)
            out["infer_max_ms"] = round(max(self.infer_ms), 1)
        if self.error:
            out["error"] = self.error
        return out
