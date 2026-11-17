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
    backend: process                    # who loads the policy: this node (process, the
                                        # default) or a policy server (server) started
                                        # with `roboloom serve-policy --from <this file>`
    server: {address: "127.0.0.1:18765"}  # read with backend: server (policy.remote)
    observe: [camera, digit_left]      # inputs or sensors; follower states are always seen
    rate_hz: 15
    interpolation_multiplier: auto      # commands at rate_hz * N (auto: up to control_hz)
    interpolation: linear               # or pchip: a monotone cubic through the actions
    action_horizon: 8
    max_speed: {follower: 1024}         # per follower, in its unit/s
    command_deadline_ms: 200
    home:                               # optional: `home` moves here first
      pose: ../poses/follower/ready.yaml  # (roboloom capture-pose ready)
      max_speed: 200                    # <= max_speed; tolerance: measured, per joint
      tolerance: 30
    teleop: [controller.yaml]           # optional: leader teleoperation before and
                                        # during an episode (paths next to this file)
    observation_history: 1              # N > 1: the policy also gets the last N frames
    hold: []                            # joints the policy does not drive (they stay)

`observation_history: N` samples the observation once per action (at `rate_hz`) and gives
`infer` `observation["history"]`: every observation stacked `[N, ...]`, oldest first and
the current frame last (the first frame fills the history), plus `"action"` `[N, n]`,
the action executed before each frame (the held targets at the start). `hold:` lists
`<follower>.<joint>` entries of the action the policy leaves alone: whatever it returns
there (NaN too) is replaced by the target the follower holds. A policy with `options()`
sets `observation_history`, `hold` and `action_horizon` itself (it wins over the YAML).

`inference: async` runs `policy.infer` on a worker thread: the node keeps sending the
queued actions meanwhile and asks for the next chunk when `replan_at` actions (auto:
half of `action_horizon`) are left. The new chunk replaces the queue without its first
d actions, d being the actions executed since the observation it was computed from, so
the actions keep their place in time. If the queue runs out first the followers hold
(`late_inference`). Commands are still sent from the node's own thread.

    inference: async                    # default sync: no command while infer runs
    replan_at: auto                     # or an integer < action_horizon

An observed input or sensor whose latest sample is older than the recorder's
`max_age_ms.<node>` stops the policy (`stale_observation`: nothing is sent, the followers
hold); once it is fresh again the policy restarts with `reset()`.

With `teleop:` the operator can drive the followers with the leader before an episode
(session command `teleop`, nothing recorded; `stop_teleop` ends it), let the policy take over at `start`, take
over again during the episode (`teleop`: an intervention) and hand back (`policy`).
Each teleop controller takes over joint by joint from where the followers are held
(`Takeover`, `control.takeover`); every command carries `intervention` (True from the
teleop controllers), which the recorder stores as `action.intervention`.

Local `hooks:` extensions run after hold substitution and before interpolation and
speed limiting, once per action period. The same chain runs after pickup/alignment
on policy teleop (only during episodes). Hook event workers serialize their own
methods; see `roboloom.hooks` and docs/explanation/hooks.md (mock only).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, Any, ClassVar, Literal

import numpy as np

from ..control.homing import parse_home
from ..control.interpolation import (
    METHODS,
    ActionInterpolator,
    auto_multiplier,
    whole_hz,
)
from ..core.checks import positive
from ..core.protocol import Envelope
from ..errors import ConfigError
from ..hooks import (
    ChunkPosition,
    ControlChanged,
    EndReason,
    EpisodeEnded,
    EpisodeStarted,
    Event,
    HookChain,
    HookError,
    HookSpec,
    ObservationStale,
    PolicyRestarted,
    StepContext,
)
from ..hooks.config import build_hooks, parse_hooks
from ..robots.base import Follower
from .base import Controller, FollowerView, Takeover

if TYPE_CHECKING:
    from ..core.source import Recordable
    from ..inputs.base import InputDevice
    from ..policy import Policy, PolicySpec


class _Inference:
    """One `policy.infer` on a worker thread; the node's thread collects the result."""

    def __init__(self, policy: Policy, observation: dict[str, Any], issued: int):
        self.issued = issued  # actions executed when the observation was taken
        self.actions: Any = None
        self.error: BaseException | None = None
        self.ms = 0.0
        self.done = threading.Event()
        self.thread = threading.Thread(
            target=self._run, args=(policy, observation), daemon=True, name="infer"
        )
        self.thread.start()

    def _run(self, policy: Policy, observation: dict[str, Any]) -> None:
        t0 = time.perf_counter()
        try:
            self.actions = policy.infer(observation)
        except BaseException as exc:  # noqa: BLE001 - raised again in the node's thread
            self.error = exc
        self.ms = (time.perf_counter() - t0) * 1000
        self.done.set()


log = logging.getLogger(__name__)

SETTLE_S = 10.0  # how long a reset waits for an inference that is still running


class PolicyController(Controller):
    uses_input: ClassVar[bool] = False
    accepts_hooks: ClassVar[bool] = True
    drives_all_followers: ClassVar[bool] = True
    keys = (
        *Controller.keys,
        "factory",
        "kwargs",
        "backend",
        "server",
        "observe",
        "rate_hz",
        "interpolation_multiplier",
        "interpolation",
        "observation_history",
        "hold",
        "action_horizon",
        "max_speed",
        "inference",
        "replan_at",
        "home",
        "teleop",
        "hooks",
    )

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
        from ..policy.remote import BACKENDS, server_settings

        self.backend = cfg.get("backend", "process")
        if self.backend not in BACKENDS:
            raise ValueError(
                f"{name}.backend must be one of {', '.join(BACKENDS)}, not "
                f"{self.backend!r}"
            )
        self.server = server_settings(cfg.get("server"), f"{name}.server")
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
        self.interpolation = cfg.get("interpolation", "linear")
        if self.interpolation not in METHODS:
            raise ValueError(
                f"{name}.interpolation must be one of {', '.join(METHODS)}, not "
                f"{self.interpolation!r}"
            )
        self.interpolator = ActionInterpolator(multiplier, self.interpolation)
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
        self.names = [
            f"{n}.{j}" for n, f in self.followers.items() for j in f.joint_names
        ]
        self.hook_entries = parse_hooks(
            cfg.get("hooks", []),
            self.names,
            teleop=bool(cfg.get("teleop")),
            backend=self.backend,
        )
        self.hooks = HookChain()
        self.hook_steps = 0
        self.episode: dict[str, Any] | None = None
        self._period_observation: Mapping[str, Any] | None = None
        self._filtered = np.zeros(len(self.names), dtype=bool)
        self._chunk_id = 0
        self._chunk_position = 0
        self._chunk_length = 0
        self.history = 1
        self.hold: tuple[str, ...] = ()
        self.hold_index: list[int] = []
        self.horizon = 1
        self.frames: deque[dict[str, Any]] = deque(maxlen=1)  # the last frames
        self.configure(
            cfg.get("observation_history", 1),
            cfg.get("hold", []),
            cfg.get("action_horizon", 1),
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
        self.inference = cfg.get("inference", "sync")
        if self.inference not in ("sync", "async"):
            raise ValueError(f"{name}.inference must be sync or async")
        replan = cfg.get("replan_at", "auto")
        if replan != "auto" and (
            isinstance(replan, bool) or not isinstance(replan, int) or replan < 0
        ):
            raise ValueError(f"{name}.replan_at must be auto or an integer >= 0")
        self.replan = replan
        self.job: _Inference | None = None  # the inference running (async)
        self.orphans: list[_Inference] = []  # running, their results no longer wanted
        self.popped = 0  # actions executed since the episode started
        self.sampled = False  # this action period's frame is already in the history
        self.dropped = 0  # actions of the last chunk that came too late
        self._parse_homes(cfg.get("home"))
        self.policy: Policy | None = None
        self.sources: dict[str, Recordable] = {}  # set by `bind`
        self.dataset_fps = 30.0  # set by `bind`
        self.max_age_ms: dict[str, float] = {}  # per observed source, set by `bind`
        self.last_commands: dict[str, list[float]] = {}
        self.executed: np.ndarray | None = None  # the action of the previous period
        self.stale = False  # an observed source went stale: restart with reset()
        self.latest: dict[str, Envelope] = {}
        self.queue: deque[np.ndarray] = deque()
        self.task = ""
        self.episode_index: int | None = None
        self.dataset_root: str | None = None
        self.running = False
        self.state = "loading"
        self.error = ""
        self.infer_ms: deque[float] = deque(maxlen=20)
        self.last_ns = 0
        # teleoperation (`teleop:`): set by `bind_teleop`
        self.teleop: dict[str, Controller] = {}
        self.control = ""  # who commands the followers: "", "policy" or "teleop"
        self.received: dict[str, int] = {}  # when each follower's state arrived

    def configure(self, history: object, hold: object, horizon: object) -> None:
        """`observation_history`, `hold` and `action_horizon`, from the YAML or from the
        policy's `options()`."""
        name = self.name
        if isinstance(history, bool) or not isinstance(history, int) or history < 1:
            raise ValueError(
                f"{name}.observation_history must be an integer >= 1, not {history!r}"
            )
        if not isinstance(hold, (list, tuple)) or not all(
            isinstance(x, str) for x in hold
        ):
            raise ValueError(f"{name}.hold must be a list of <follower>.<joint> names")
        unknown = [x for x in hold if x not in self.names]
        if unknown or len(set(hold)) != len(hold):
            raise ValueError(
                f"{name}.hold: {unknown or 'repeated names'}; the action's entries are "
                f"{', '.join(self.names)}"
            )
        self.history = history
        self.hold = tuple(hold)
        self.hold_index = [self.names.index(x) for x in self.hold]
        self.horizon = int(positive(horizon, f"{name}.action_horizon"))
        self.frames = deque(maxlen=history)

    def _clear(self) -> None:
        """Forget queued actions, the interpolation and the observation history."""
        self.queue.clear()
        self.interpolator.reset()
        self.frames.clear()
        self.executed = None
        self._filtered[:] = False
        self._period_observation = None
        if self.job is not None:  # its result belongs to what was forgotten
            self.orphans.append(self.job)
            self.job = None
        self.sampled = False

    @property
    def replan_at(self) -> int:
        """Queued actions left when the next inference starts (async)."""
        auto = max(1, self.horizon // 2)
        return min(self.horizon - 1, auto if self.replan == "auto" else self.replan)

    def _settle(self) -> None:
        """Wait for a running inference, so `policy.reset` never overlaps `infer`."""
        self._clear()
        deadline = time.monotonic() + SETTLE_S
        for job in self.orphans:
            if not job.done.wait(max(0.0, deadline - time.monotonic())):
                raise RuntimeError(
                    f"{self.name}: an inference is still running after {SETTLE_S:g} s"
                )
        self.orphans = []

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
            c.step_hooks = self.hooks
            c.step_context = self._teleop_context
        self.command_extra = {"intervention": False}
        self.teleop = dict(controllers)

    def teleop_inputs(self) -> list[str]:
        """The inputs the teleop controllers follow (not observed by the policy)."""
        return [c.source.name for c in self.teleop.values() if c.source is not None]

    def nested(self) -> list[Controller]:
        return list(self.teleop.values())

    def intent_inputs(self) -> list[str]:
        return self.teleop_inputs()

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
        self._clear()
        previous = self.control
        self.control = "teleop"
        if self.running and previous != "teleop":
            if self.episode is not None:
                self.episode["interventions"] += 1
                self.episode["teleop_since"] = time.monotonic()
            self._event(ControlChanged(previous, "teleop", "takeover"))

    def resume_policy(self) -> None:
        """Hand back to the policy during an episode; it restarts from the held targets
        with a fresh history (`policy.reset`)."""
        if not self.running or self.policy is None:
            raise RuntimeError(
                "no episode running: start one (the policy starts with it)"
            )
        self._settle()
        self.policy.reset()
        self._clear()
        self.stale = False
        self.last_ns = 0
        self._handed_back()
        previous = self.control
        self.control = "policy"
        self._event(ControlChanged(previous, "policy", "handback"))
        self._event(PolicyRestarted("handback"))

    def _handed_back(self) -> None:
        since = self.episode.pop("teleop_since", None) if self.episode else None
        if self.episode is not None and since is not None:
            self.episode["intervention_s"] += time.monotonic() - since

    def end_teleop(self) -> None:
        """End teleoperation outside an episode; the followers hold."""
        if not self.running:
            self.control = ""

    def teleop_update(self, input_name: str, intent: Envelope) -> dict[str, Envelope]:
        """Commands from the teleop controllers following `input_name`, while they drive."""
        if self.control != "teleop":
            return {}
        views = self._views()
        if any(v.mode in ("FAULT", "ESTOP") for v in views.values()):
            return {}
        self._period_observation = None
        out: dict[str, Envelope] = {}
        for c in self.teleop.values():
            if c.source is None or c.source.name != input_name:
                continue
            if all(f in views for f in c.followers):
                try:
                    sent = c.update(intent, {f: views[f] for f in c.followers})
                except HookError as exc:
                    self.fail(str(exc))
                    return {}
                out.update(sent)
                if sent and self.episode is not None:
                    self.hook_steps += 1
        if out and self.episode is not None:
            self.episode["commands"] += 1
        self.last_commands.update(
            {n: list(msg.payload["positions"]) for n, msg in out.items()}
        )
        if out and self.running:
            parts = []
            for name in self.followers:
                parts.append(
                    np.asarray(
                        self.last_commands.get(
                            name, views[name].target or views[name].positions
                        ),
                        dtype=float,
                    )
                )
            self.executed = np.concatenate(parts)
        return out

    def _teleop_context(self, ctx: StepContext) -> StepContext | None:
        if not self.running:
            return None
        previous = self.last_commands.get(ctx.names[0].split(".", 1)[0])
        return replace(
            ctx,
            _previous=(lambda: np.asarray(previous, dtype=float))
            if previous is not None
            else ctx._previous,
            step=self.hook_steps,
            task=self.task,
            episode_index=self.episode_index,
            _hold=self.hold,
            _observation=self._hook_observation,
        )

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

    def bind(
        self,
        sources: dict[str, Recordable],
        dataset_fps: float,
        max_age_ms: Mapping[str, object] | None = None,
    ) -> None:
        """The specs of the observed sources and the dataset rate, so observations have
        exactly the keys and shapes of the recorded rows (`recording.schema`), and the
        recorder's `max_age_ms` of each: a sample older than that is not inferred on."""
        self.sources = {name: sources[name] for name in self.observes()}
        self.dataset_fps = dataset_fps
        self.max_age_ms = {
            name: positive(age, f"max_age_ms.{name}")
            for name, age in (max_age_ms or {}).items()
            if name in self.sources
        }

    # -- lifecycle (the policy node calls these) --------------------------------

    def load(self, factory: str | None = None, kwargs: dict | None = None) -> None:
        """Import and build the policy; `factory`/`kwargs` override the configuration."""
        from ..policy import load_policy
        from ..policy.remote import connect

        if self.backend == "server" and (factory or kwargs is not None):
            raise ConfigError(
                f"{self.name}: with backend: server the policy server loads the "
                "policy; --policy and --policy-kwargs have nothing to replace here"
            )
        policy = (
            connect(**self.server)
            if self.backend == "server"
            else load_policy(
                factory or self.cfg["factory"],
                self.cfg.get("kwargs", {}) if kwargs is None else kwargs,
                search=[str(self.cfg.get("__robot_dir__") or "")],
            )
        )
        options = getattr(policy, "options", None)
        if callable(options):  # what the model needs, stated by the policy itself
            wanted = options()
            known = {"observation_history", "hold", "action_horizon"}
            if not isinstance(wanted, Mapping) or not set(wanted) <= known:
                raise ValueError(
                    f"{self.name}: the policy's options() must be a mapping with keys "
                    f"from {sorted(known)}"
                )
            self.configure(
                wanted.get("observation_history", self.history),
                wanted.get("hold", list(self.hold)),
                wanted.get("action_horizon", self.horizon),
            )
        bind = getattr(policy, "bind", None)
        if callable(bind):  # the policy checks it gets what it was trained on
            bind(self.spec())
        self.policy = policy
        try:
            self._bind_hooks()
        except BaseException:
            self.policy = None
            raise
        self.state = "ready"

    def _bind_hooks(self) -> None:
        """Called after policy.bind: factories and policy contributions share validation."""
        offered = getattr(self.policy, "hooks", None)
        contributed = offered() if callable(offered) else ()
        if not isinstance(contributed, Sequence) or isinstance(
            contributed, (str, bytes)
        ):
            raise ConfigError("policy hooks() must return a sequence of Hook objects")
        spec = self.spec()
        hook_spec = HookSpec(
            names=tuple(self.names),
            units=spec.units,
            hold=self.hold,
            observation=spec.observation,
            rate_hz=self.rate_hz,
            command_hz=self.command_hz,
            dataset_fps=self.dataset_fps,
            sources=("policy", "teleop") if self.teleop else ("policy",),
        )
        self.hooks.close()
        self.hooks = HookChain(
            build_hooks(
                self.hook_entries,
                contributed,
                hook_spec,
                search=[str(self.cfg.get("__robot_dir__") or "")],
            )
        )
        for controller in self.teleop.values():
            controller.step_hooks = self.hooks
            controller.step_context = self._teleop_context
        # Map observation keys to their producers once, without decoding any samples.
        from ..recording.schema import joined_parts

        sources = {**self.followers, **self.sources}
        self._hook_sources: dict[str, tuple[str, ...]] = {
            key: (name,)
            for name, source in sources.items()
            for key in source.features(self.dataset_fps)
        }
        self._hook_sources.update(
            {
                key: tuple(name for name, _ in parts)
                for key, parts in joined_parts(sources, self.dataset_fps).items()
            }
        )

    def _event(self, event: Event) -> None:
        try:
            self.hooks.emit(event, rate_hz=self.rate_hz)
        except HookError as exc:
            self.fail(str(exc))
            raise

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
            history=self.history,
            hold=self.hold,
            units=tuple(f.unit for f in self.followers.values() for _ in f.joint_names),
            inference=self.inference,
        )

    def start(self, task: str, episode_index: int | None = None) -> None:
        """Start after the previous end event; refuse a blocked start after 60 s."""
        if self.policy is None:
            raise RuntimeError("policy not loaded")
        if self.running:
            raise RuntimeError("an episode is already running")
        self._settle()
        started_at, t0 = time.time(), time.monotonic()
        # The barrier queues behind the preceding EpisodeEnded on each step hook.
        self.hooks.emit(
            EpisodeStarted(task, episode_index, self.dataset_root, started_at),
            rate_hz=self.rate_hz,
        )
        self.policy.reset()
        self.hooks.reset_stats()
        self.popped = self.hook_steps = 0
        self.task, self.episode_index, self.running = task, episode_index, True
        self._clear()
        self.stale, self.error = False, ""
        self.last_ns = 0
        self.state, self.control = "running", "policy"
        self.episode = {
            "task": task,
            "episode_index": episode_index,
            "dataset_root": self.dataset_root,
            "started_at": started_at,
            "t0": t0,
            "commands": 0,
            "interventions": 0,
            "intervention_s": 0.0,
        }

    def stop(self, reason: EndReason = "stopped", error: str = "") -> None:
        """End once, without blocking the control thread on event handlers."""
        self.running = False
        self.control = ""
        self._clear()
        if self.policy is not None:
            self.state = "ready"
        if self.episode is None:
            return
        self._handed_back()
        episode, self.episode = self.episode, None
        jobs = list(self.orphans)

        def settle() -> None:
            deadline = time.monotonic() + SETTLE_S
            for job in jobs:
                if not job.done.wait(max(0.0, deadline - time.monotonic())):
                    log.warning("inference still running before hook episode_ended")

        event = EpisodeEnded(
            task=episode["task"],
            reason=reason,
            error=error,
            episode_index=episode["episode_index"],
            dataset_root=episode["dataset_root"],
            steps=self.hook_steps,
            commands=episode["commands"],
            interventions=episode["interventions"],
            intervention_s=round(episode["intervention_s"], 3),
            filtered_steps=self.hooks.filtered,
            started_at=episode["started_at"],
            duration_s=round(time.monotonic() - episode["t0"], 3),
        )
        self.hooks.log_stats()
        self.hooks.emit(event, settle=settle)

    def fail(self, error: str) -> None:
        """Fail the episode; commands stop and the followers hold."""
        self.stop("failed", error)
        self.state, self.error = "failed", error

    def reset(self, why: str = "") -> None:
        self.stop("interrupted", why)
        for c in self.teleop.values():
            c.reset()

    def shutdown(self) -> None:
        """End a running episode, drain events (60 s cap), then close hooks."""
        self.stop("shutdown")
        self.hooks.close()

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

    def _hook_observation(self) -> Mapping[str, Any]:
        if self._period_observation is None:
            from ..recording.schema import observation_frame

            sources = {**self.followers, **self.sources}
            producers = {
                n for key in self.hooks.observe for n in self._hook_sources[key]
            }
            self._period_observation = observation_frame(
                {n: s for n, s in sources.items() if n in producers},
                self.latest,
                self.dataset_fps,
                keys=self.hooks.observe,
                lazy=True,
            )
        return self._period_observation

    def _context(
        self,
        source: Literal["policy", "teleop"],
        now: int,
        held: np.ndarray,
        chunk: ChunkPosition | None = None,
    ) -> StepContext:
        snapshots = dict(self.last_commands)

        def previous() -> np.ndarray:
            parts = []
            start = 0
            for name, follower in self.followers.items():
                stop = start + len(follower.joint_names)
                parts.append(
                    np.asarray(snapshots.get(name, held[start:stop]), dtype=float)
                )
                start = stop
            return np.concatenate(parts)

        return StepContext(
            source=source,
            step=self.hook_steps,
            t_ns=now,
            rate_hz=self.rate_hz,
            task=self.task,
            episode_index=self.episode_index,
            names=tuple(self.names),
            chunk=chunk,
            _held=lambda: held,
            _previous=previous,
            _state=lambda: np.concatenate(
                [
                    np.asarray(self.latest[n].payload["positions"], dtype=float)
                    for n in self.followers
                ]
            ),
            _observation=self._hook_observation,
            _hold=self.hold,
        )

    def _stale_sources(self, now: int) -> list[str]:
        """Observed inputs and sensors whose latest sample is older than `max_age_ms`."""
        return [
            name
            for name, age in self.max_age_ms.items()
            if name in self.latest and now - self.latest[name].t_capture_ns > age * 1e6
        ]

    def _remember(self, observation: dict[str, Any], held: np.ndarray) -> None:
        """Add this action period's frame to the history (the first one fills it)."""
        frame = {k: v for k, v in observation.items() if isinstance(v, np.ndarray)}
        frame["action"] = np.asarray(
            held if self.executed is None else self.executed, dtype=np.float32
        )
        for _ in range(1 if self.frames else self.history):
            self.frames.append(frame)

    def _with_history(self, observation: dict[str, Any]) -> dict[str, Any]:
        if self.history == 1:
            return observation
        frames = list(self.frames)
        history = {key: np.stack([f[key] for f in frames]) for key in frames[0]}
        return {**observation, "history": history}

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
        # checked on every command, also between two actions: the steps toward an
        # action inferred from a sample that has since gone stale are not sent either
        old = self._stale_sources(now)
        if old:  # e.g. a frozen camera: never act on what is no longer there
            self._clear()
            if not self.stale:
                self._event(ObservationStale(tuple(old)))
            self.stale = True
            self.state, self.error = "stale_observation", f"{old[0]} is stale"
            return {}
        if self.interpolator.needs_new_action():
            if self.stale:  # fresh again: the policy starts over
                self._settle()
                self.policy.reset()
                self.stale, self.error = False, ""
                self._event(PolicyRestarted("stale_recovered"))
            self._period_observation = None
            held = np.concatenate(
                [
                    np.asarray(
                        s.payload.get("target") or s.payload["positions"],  # type: ignore[union-attr]
                        dtype=np.float64,
                    )
                    for s in states.values()
                ]
            )
            if self.inference == "async":
                self._collect()
                wanted = self.job is None and len(self.queue) <= self.replan_at
            else:
                wanted = not self.queue
            if (self.history > 1 and not self.sampled) or wanted:
                observation = self.observation()
                self._period_observation = observation
                if observation is None:
                    self.state = "waiting_observation"
                    return {}
                if self.history > 1 and not self.sampled:
                    self._remember(observation, held)
                    self.sampled = True
                if wanted and self.inference == "async":
                    self.job = _Inference(
                        self.policy, self._with_history(observation), self.popped
                    )
                elif wanted:
                    t0 = time.perf_counter()
                    actions = self.policy.infer(self._with_history(observation))
                    self._queue(actions, (time.perf_counter() - t0) * 1000)
                    if now_ns is None:  # infer took time
                        now = time.monotonic_ns()
            if not self.queue:  # async: the chunk is not there yet; the followers hold
                self.state = "late_inference" if self.popped else "waiting_inference"
                return {}
            chosen = self.queue.popleft().copy()
            chosen[self.hold_index] = held[self.hold_index]
            try:
                filtered = self.hooks.run(
                    chosen,
                    self._context(
                        "policy",
                        now,
                        held,
                        ChunkPosition(
                            self._chunk_id, self._chunk_position, self._chunk_length
                        ),
                    ),
                )
            except HookError as exc:
                self.fail(str(exc))
                return {}
            if now_ns is None:
                now = time.monotonic_ns()
            self._filtered = filtered != chosen
            self.popped += 1
            self.hook_steps += 1
            self._chunk_position += 1
            self.sampled = False
            # after a reset the line starts from what the followers hold
            following = self.queue[0].copy() if self.queue else None
            if following is not None:
                following[self.hold_index] = held[self.hold_index]
                following[self._filtered] = filtered[self._filtered]
            self.interpolator.add(filtered, previous=held, next=following)
        action = self.interpolator.get()
        assert action is not None  # an action was just added if the steps ran out
        period = 1 / self.command_hz
        dt = max((now - self.last_ns) / 1e9, 1e-6) if self.last_ns else period
        span = min(dt, 2 * period)
        out: dict[str, Envelope] = {}
        sent: list[float] = []
        start = 0
        for name, follower in self.followers.items():
            part = action[start : start + len(follower.joint_names)]
            part_filtered = bool(
                self._filtered[start : start + len(follower.joint_names)].any()
            )
            start += len(follower.joint_names)
            payload = states[name].payload  # type: ignore[union-attr]  # checked above
            # step from what the follower holds, as the joint controller does
            previous = list(payload.get("target") or payload["positions"])
            step = self.max_speed[name] * span
            limited = [
                max(p - step, min(p + step, float(x)))
                for p, x in zip(previous, part, strict=True)
            ]
            out[name] = self.command(name, limited, now, filtered=part_filtered)
            self.last_commands[name] = limited
            sent += limited
        # the history's action is the command that went out (what the recorder writes
        # as `action`), not the policy's target before the speed limit
        self.executed = np.asarray(sent, dtype=np.float64)
        self.last_ns = now
        if self.episode is not None:
            self.episode["commands"] += 1
        return out

    def _collect(self) -> None:
        """Take over a finished inference (async): its chunk replaces the queue, without
        the actions whose time has passed while it was computed."""
        job = self.job
        if job is None or not job.done.is_set():
            return
        self.job = None
        if job.error is not None:
            raise job.error
        self.dropped = self.popped - job.issued
        self.queue.clear()
        self._queue(job.actions, job.ms, skip=self.dropped)

    def _queue(self, output: Any, ms: float, skip: int = 0) -> None:
        """Queue the first `action_horizon` steps of the policy's output (from `skip`)."""
        actions = np.asarray(output, dtype=np.float64)
        self.infer_ms.append(ms)
        n = sum(len(f.joint_names) for f in self.followers.values())
        if actions.ndim == 1:
            actions = actions[None, :]
        if actions.ndim != 2 or actions.shape[1] != n:
            raise ValueError(
                f"policy returned shape {actions.shape}; expected [{n}] or [H, {n}]"
            )
        driven = np.delete(actions, self.hold_index, axis=1)
        if not np.isfinite(driven).all():  # `hold` entries may be anything
            raise ValueError(
                f"policy returned non-finite targets (shape {actions.shape})"
            )
        self._chunk_id += 1
        self._chunk_position = skip
        self._chunk_length = min(len(actions), self.horizon)
        self.queue.extend(actions[skip : self.horizon])
        self.state = "running"

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
            "step": self.popped,  # actions executed since the episode started
        }
        if self.inference == "async":
            out["inference"] = "async"
            out["dropped"] = self.dropped
        if self.infer_ms:
            out["infer_ms"] = round(self.infer_ms[-1], 1)
            out["infer_max_ms"] = round(max(self.infer_ms), 1)
        if self.hooks.entries:
            out.update(self.hooks.status())
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
