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

`rate_hz` is the policy's action rate (the rate it was trained at). With
`interpolation_multiplier: N` the node runs at `rate_hz * N`, takes a new action every N
ticks and sends the straight line to it in N steps (`control.interpolation`, LeRobot's
scheme): the actions keep their trained spacing and the followers get smooth targets.
Without it (or `auto`) N is the largest that keeps `rate_hz * N` whole Hz and at most
the slowest follower's `control_hz`; 1 sends each action as is.

    type: policy
    followers: [follower]               # every follower, in configuration order
    factory: my_lab.policies:load_act   # "module:callable" returning a Policy (also
                                        # found in the robot's directory)
    kwargs: {checkpoint: ...}
    observe: [camera, digit_left]      # inputs or sensors; follower states are always seen
    rate_hz: 15
    interpolation_multiplier: auto      # commands at rate_hz * N (auto: up to control_hz)
    action_horizon: 8
    max_speed: {follower: 1024}         # per follower, in its unit/s
    command_deadline_ms: 200
    home:                               # optional: `home` moves here first
      pose: ../poses/follower/ready.yaml  # (roboloom capture-pose ready)
      max_speed: 200                    # <= max_speed; tolerance: measured, per joint
      tolerance: 30
    teleop: [controller.yaml]           # optional: leader teleoperation before and
                                        # during an episode (paths next to this file)

With `teleop:` the operator can drive the followers with the leader before an episode
(session command `teleop`, nothing recorded; `stop_teleop` ends it), let the policy take over at `start`, take
over again during the episode (`teleop`: an intervention) and hand back (`policy`).
Each teleop controller takes over joint by joint from where the followers are held
(`Takeover`, `control.takeover`); every command carries `intervention` (True from the
teleop controllers), which the recorder stores as `action.intervention`.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar

import numpy as np

from ..control.homing import parse_home
from ..control.interpolation import ActionInterpolator, auto_multiplier, whole_hz
from ..core.checks import positive
from ..core.protocol import Envelope
from ..errors import ConfigError
from ..robots.base import Follower
from .base import Controller, FollowerView, Takeover

if TYPE_CHECKING:
    from ..core.source import Recordable
    from ..inputs.base import InputDevice
    from ..policy import Policy, PolicySpec


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
        slowest = min(f.control_hz for f in self.followers.values())
        multiplier = cfg.get("interpolation_multiplier", "auto")
        if multiplier in (None, "auto"):  # as often as the followers take commands
            multiplier = auto_multiplier(self.rate_hz, slowest)
        elif (
            isinstance(multiplier, bool)
            or not isinstance(multiplier, int)
            or multiplier < 1
        ):
            raise ValueError(
                f"{name}.interpolation_multiplier must be auto or an integer >= 1, "
                f"not {multiplier!r}"
            )
        self.multiplier = multiplier
        self.interpolator = ActionInterpolator(multiplier)
        self.command_hz = self.rate_hz * multiplier  # the node's timer
        if multiplier > 1:
            if not whole_hz(self.command_hz):
                raise ValueError(
                    f"{name}: rate_hz * interpolation_multiplier = {self.command_hz:g} "
                    "Hz; the node's timer needs whole Hz"
                )
            if self.command_hz > slowest:
                raise ValueError(
                    f"{name}: rate_hz * interpolation_multiplier = {self.command_hz:g} "
                    f"Hz exceeds the follower control_hz {slowest:g}; lower "
                    "interpolation_multiplier"
                )
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
        self._parse_homes(cfg.get("home"))
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
        # teleoperation (`teleop:`): set by `bind_teleop`
        self.teleop: dict[str, Controller] = {}
        self.control = ""  # who commands the followers: "", "policy" or "teleop"
        self.received: dict[str, int] = {}  # when each follower's state arrived

    def bind_teleop(self, controllers: Mapping[str, Controller]) -> None:
        """The teleoperation controllers of `teleop:`; together they drive every
        follower exactly once, and each takes over from where its followers are held."""
        owners: dict[str, str] = {}
        for name, c in controllers.items():
            if not isinstance(c, Takeover):
                raise ConfigError(
                    f"{self.name}.teleop: {name} ({c.cfg.get('type')}) cannot take over "
                    "from a policy yet; only type: joint controllers can"
                )
            if c.feedback is not None:
                raise ConfigError(f"{self.name}.teleop: {name} must not send feedback")
            for follower in c.followers:
                if follower not in self.followers:
                    raise ConfigError(
                        f"{self.name}.teleop: {name} drives {follower!r}, which the "
                        "policy does not"
                    )
                if follower in owners:
                    raise ConfigError(
                        f"{self.name}.teleop: {follower!r} is driven by both "
                        f"{owners[follower]} and {name}"
                    )
                owners[follower] = name
        missing = [f for f in self.followers if f not in owners]
        if missing:
            raise ConfigError(
                f"{self.name}.teleop: no teleop controller drives {', '.join(missing)}"
            )
        for c in controllers.values():
            c.publisher = self.publisher  # one command sequence per follower
            c.command_extra = {"intervention": True}
        self.command_extra = {"intervention": False}
        self.teleop = dict(controllers)

    def teleop_inputs(self) -> list[str]:
        """The inputs the teleop controllers follow (not observed by the policy)."""
        return [c.source.name for c in self.teleop.values() if c.source is not None]

    def _views(self) -> dict[str, FollowerView]:
        return {
            name: FollowerView.of(msg, self.received.get(name, 0))
            for name, msg in self.latest.items()
            if name in self.followers
        }

    def begin_teleop(self) -> None:
        """Hand the followers to the teleop controllers, joint by joint from where they
        are held (before an episode, or during one: an intervention)."""
        if not self.teleop:
            raise RuntimeError(f"{self.name} has no teleop controllers (teleop:)")
        views = self._views()
        missing = [f for f in self.followers if f not in views]
        if missing:
            raise RuntimeError(f"no state yet from {', '.join(missing)}")
        for c in self.teleop.values():
            c.begin_takeover(views)  # type: ignore[attr-defined]  # Takeover, checked
        self.queue.clear()
        self.interpolator.reset()
        self.control = "teleop"

    def resume_policy(self) -> None:
        """Hand back to the policy during an episode; it restarts from the held targets
        with a fresh history (`policy.reset`)."""
        if not self.running or self.policy is None:
            raise RuntimeError(
                "no episode running: start one (the policy starts with it)"
            )
        self.policy.reset()
        self.queue.clear()
        self.interpolator.reset()
        self.last_ns = 0
        self.control = "policy"

    def end_teleop(self) -> None:
        """End teleoperation outside an episode; the followers hold."""
        if not self.running:
            self.control = ""

    def teleop_update(self, input_name: str, intent: Envelope) -> dict[str, Envelope]:
        """Commands from the teleop controllers following `input_name`, while they drive."""
        if self.control != "teleop":
            return {}
        views = self._views()
        out: dict[str, Envelope] = {}
        for c in self.teleop.values():
            if c.source is None or c.source.name != input_name:
                continue
            if all(f in views for f in c.followers):
                out.update(c.update(intent, {f: views[f] for f in c.followers}))
        return out

    def _parse_homes(self, raw: object) -> None:
        """`home:` the saved pose(s) `home` moves the followers to before an episode: one
        spec with a single follower, else {follower: spec} (followers left out stay)."""
        if raw is None:
            return
        if len(self.followers) == 1 and isinstance(raw, dict) and "pose" in raw:
            raw = {self.follower.name: raw}
        if not isinstance(raw, dict) or not set(raw) <= set(self.followers):
            raise ConfigError(
                f"{self.name}.home: {{pose, max_speed, tolerance}}"
                + (
                    ""
                    if len(self.followers) == 1
                    else f" per follower ({', '.join(self.followers)})"
                )
            )
        for follower, spec in raw.items():
            home = parse_home(
                spec,
                f"{self.name}.home.{follower}"
                if len(self.followers) > 1
                else self.name,
                self.cfg.get("__dir__"),
                self.followers[follower],
                self.max_speed[follower],
            )
            if home is not None:
                self.homes[follower] = home

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

        policy = load_policy(
            factory or self.cfg["factory"],
            self.cfg.get("kwargs", {}) if kwargs is None else kwargs,
            search=[str(self.cfg.get("__robot_dir__") or "")],
        )
        bind = getattr(policy, "bind", None)
        if callable(bind):  # the policy checks it gets what it was trained on
            bind(self.spec())
        self.policy = policy
        self.state = "ready"

    def spec(self) -> PolicySpec:
        """The observation's features and the action's names this policy is given."""
        from ..policy import PolicySpec
        from ..recording.schema import observation_features, state_names

        return PolicySpec(
            observation=observation_features(
                {**self.followers, **self.sources}, self.dataset_fps
            ),
            action=tuple(state_names(self.followers)),
            rate_hz=self.rate_hz,
            dataset_fps=self.dataset_fps,
        )

    def start(self, task: str) -> None:
        if self.policy is None:
            raise RuntimeError("policy not loaded")
        self.policy.reset()
        self.task, self.running = task, True
        self.queue.clear()
        self.interpolator.reset()
        self.last_ns = 0
        self.state = "running"
        self.control = "policy"  # also after teleoperation before the episode

    def stop(self) -> None:
        self.running = False
        self.control = ""
        self.queue.clear()
        self.interpolator.reset()
        if self.state == "running":
            self.state = "ready"

    def reset(self) -> None:
        self.stop()
        for c in self.teleop.values():
            c.reset()

    def observe(self, name: str, msg: Envelope) -> None:
        self.latest[name] = msg
        if name in self.followers:
            self.received[name] = time.monotonic_ns()

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
        """The next command per follower while an episode runs: a new action every
        `interpolation_multiplier` ticks (inferring when none is queued) and the steps
        toward it in between. Nothing while a follower has no state yet or latched
        FAULT/ESTOP."""
        now = time.monotonic_ns() if now_ns is None else now_ns
        if not self.running or self.policy is None or self.control != "policy":
            return {}
        states = {name: self.latest.get(name) for name in self.followers}
        if any(
            s is None or s.payload.get("mode") in ("FAULT", "ESTOP")
            for s in states.values()
        ):
            return {}
        if self.interpolator.needs_new_action():
            if not self.queue:
                if not self._infer():
                    return {}
                if now_ns is None:  # infer took time
                    now = time.monotonic_ns()
            # after a reset the line starts from what the followers hold
            held = np.concatenate(
                [
                    np.asarray(
                        s.payload.get("target") or s.payload["positions"],  # type: ignore[union-attr]
                        dtype=np.float64,
                    )
                    for s in states.values()
                ]
            )
            self.interpolator.add(self.queue.popleft(), previous=held)
        action = self.interpolator.get()
        assert action is not None  # an action was just added if the steps ran out
        period = 1 / self.command_hz
        dt = max((now - self.last_ns) / 1e9, 1e-6) if self.last_ns else period
        span = min(dt, 2 * period)
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

    def _infer(self) -> bool:
        """Queue the first `action_horizon` steps of the policy's output; False while an
        observed source has no sample yet."""
        assert self.policy is not None
        observation = self.observation()
        if observation is None:
            self.state = "waiting_observation"
            return False
        t0 = time.perf_counter()
        actions = np.asarray(self.policy.infer(observation), dtype=np.float64)
        self.infer_ms.append((time.perf_counter() - t0) * 1000)
        n = sum(len(f.joint_names) for f in self.followers.values())
        if actions.ndim == 1:
            actions = actions[None, :]
        if actions.ndim != 2 or actions.shape[1] != n or not np.isfinite(actions).all():
            raise ValueError(
                f"policy returned shape {actions.shape}; expected [{n}] or [H, {n}], finite"
            )
        self.queue.extend(actions[: self.horizon])
        self.state = "running"
        return True

    def update(
        self,
        intent: Envelope,
        views: Mapping[str, FollowerView],
        now_ns: int | None = None,
    ) -> dict[str, Envelope]:
        raise TypeError(f"{self.name}: a policy controller is stepped by `tick`")

    def status(self) -> dict:
        out: dict = {
            "state": self.state,
            "queued": len(self.queue),
            "interpolation": self.multiplier,
        }
        if self.infer_ms:
            out["infer_ms"] = round(self.infer_ms[-1], 1)
            out["infer_max_ms"] = round(max(self.infer_ms), 1)
        if self.teleop:
            out["control"] = self.control or "hold"
            if self.control == "teleop":
                pickup: dict[str, float] = {}
                for c in self.teleop.values():
                    pickup.update(c.status().get("pickup", {}))
                    out["teleop_state"] = c.status().get("state")
                if pickup:
                    out["pickup"] = pickup
        if self.error:
            out["error"] = self.error
        return out
