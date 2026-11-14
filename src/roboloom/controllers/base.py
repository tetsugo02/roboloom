"""Controller contract: one input's intents -> deadline-bound commands for its followers.

A controller drives one or more followers (`followers: [...]` in its YAML; each follower
has exactly one controller). It sees each follower's latest state as a `FollowerView`
and returns at most one command per follower.

Safety contract for every controller: after `reset()` (a follower latched FAULT or
ESTOP, or its state went stale) it sends no command until it has re-aligned with what
the followers actually do. A follower that gets no command keeps holding its target
(`FollowerSafety`), still armed, so this is what keeps a stopped group from moving again
on its own.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Protocol, runtime_checkable

from ..control.homing import HomeSpec
from ..core.checks import positive
from ..core.protocol import Envelope, Publisher
from ..estimators.base import Estimator
from ..inputs.base import InputDevice
from ..robots.base import Follower
from ..robots.safety import make_command
from .feedback import FeedbackMap


@dataclass(frozen=True)
class FollowerView:
    """A follower's latest `follower_state`, as its controller sees it."""

    positions: list[float]
    target: list[float] | None  # the goal it holds or tracks; steps start from here
    velocities: list[float] | None  # measured, when the follower reports them
    mode: str
    t_ns: int  # when the controller received it

    @classmethod
    def of(cls, msg: Envelope, t_ns: int) -> FollowerView:
        p = msg.payload
        return cls(
            list(p["positions"]),
            p.get("target"),
            p.get("velocities"),
            str(p.get("mode", "")),
            t_ns,
        )


class Controller(ABC):
    # False for controllers that do not follow one operator input (e.g. a policy); they get
    # `source=None` and name what they read in `observes()`.
    uses_input: ClassVar[bool] = True
    # how many followers one controller of this type drives (None: any number)
    max_followers: ClassVar[int | None] = None
    # True for a controller that must drive every follower, in configuration order (a
    # policy: its action is the recorded one, which joins them all)
    drives_all_followers: ClassVar[bool] = False

    def __init__(
        self,
        name: str,
        cfg: dict,
        source: InputDevice | None,
        followers: Mapping[str, Follower],
    ):
        self.name, self.cfg, self.source = name, cfg, source
        self.followers = dict(followers)
        if not self.followers:
            raise ValueError(f"{name}.followers: name at least one follower")
        if self.max_followers is not None and len(self.followers) > self.max_followers:
            raise ValueError(
                f"{name}: a {type(self).__name__} drives {self.max_followers} "
                f"follower(s), not {len(self.followers)}"
            )
        self.deadline_ms = positive(
            cfg.get("command_deadline_ms"), f"{name}.command_deadline_ms"
        )
        self.publisher = Publisher(name)
        # saved poses `home` moves the followers (and the leader) to, by follower
        self.homes: dict[str, HomeSpec] = {}
        # force feedback to the input (`feedback:`), for controllers that support it
        self.feedback: FeedbackMap | None = None
        # fields every command carries (a policy marks its teleop commands)
        self.command_extra: dict[str, object] = {}

    @property
    def follower(self) -> Follower:
        """The follower of a controller that drives exactly one."""
        if len(self.followers) != 1:
            raise RuntimeError(f"{self.name} drives {len(self.followers)} followers")
        (follower,) = self.followers.values()
        return follower

    def bind_feedback(self, estimators: Mapping[str, Estimator]) -> None:
        """Connect `feedback:` to its estimator and check the input takes it."""
        if self.feedback is None:
            if "feedback" in self.cfg:
                raise ValueError(
                    f"{self.name}: {type(self).__name__} cannot send feedback"
                )
            return
        if len(self.followers) != 1:
            raise ValueError(f"{self.name}.feedback needs a controller of one follower")
        estimator = estimators.get(self.feedback.estimator_name)
        if estimator is None:
            raise ValueError(
                f"{self.name}.feedback.estimator: no estimator "
                f"{self.feedback.estimator_name!r} in the configuration"
            )
        units = getattr(self.source, "feedback_units", None)
        self.feedback.bind(
            estimator, self.follower, units() if units is not None else {}
        )

    def command(
        self, follower: str, target: list[float], now_ns: int, **extra: object
    ) -> Envelope:
        """A command for `follower`, in its unit, valid for `command_deadline_ms`."""
        return make_command(
            self.publisher,
            follower=follower,
            unit=self.followers[follower].unit,
            target=target,
            now_ns=now_ns,
            deadline_ms=self.deadline_ms,
            **{**self.command_extra, **extra},
        )

    @abstractmethod
    def update(
        self,
        intent: Envelope,
        views: Mapping[str, FollowerView],
        now_ns: int | None = None,
    ) -> dict[str, Envelope]:
        """The next command per follower; an empty dict when nothing may move.

        `views` holds the latest state of every follower of this controller. Controllers
        step from each view's `target` (what the follower holds) so they never drift
        away from what the follower actually does.
        """

    @abstractmethod
    def reset(self) -> None:
        """Require re-alignment before any further command (see the module docstring)."""

    def nested(self) -> list[Controller]:
        """Controllers this one owns and steps itself (a policy's teleop controllers,
        the parts of a `type: parts` controller); they follow inputs too."""
        return []

    def intent_inputs(self) -> list[str]:
        """Inputs whose samples its nested controllers follow; the node receives each
        as `intent_<input>`."""
        return []

    def update_from(
        self,
        input_name: str,
        intent: Envelope,
        views: Mapping[str, FollowerView],
        now_ns: int | None = None,
    ) -> dict[str, Envelope]:
        """`update` for a sample of `input_name` (controllers with several inputs)."""
        return self.update(intent, views, now_ns)

    def observes(self) -> list[str]:
        """Inputs and sensors whose samples this controller reads besides its input."""
        return []

    def status(self) -> dict:
        """Why the controller is (not) commanding, for the operator screen. Override to add fields."""
        return {}


@runtime_checkable
class Takeover(Protocol):
    """A teleoperation controller that can take its followers over from where they are
    held (a policy's `teleop:`): after `begin_takeover` every joint holds until the input
    reaches it, then follows (`control.takeover.JointPickup`). `status()` then reports
    `pickup`: joint -> signed distance still to go, for the joints not caught yet."""

    def begin_takeover(self, views: Mapping[str, FollowerView]) -> None: ...
