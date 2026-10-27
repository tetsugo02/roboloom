"""Controller contract: one input's intents -> deadline-bound commands for one robot."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from ..control.homing import HomeSpec
from ..core.checks import positive
from ..core.protocol import Envelope, Publisher
from ..inputs.base import InputDevice
from ..robots.base import Robot
from ..robots.safety import make_command


class Controller(ABC):
    # False for controllers that do not follow one operator input (e.g. a policy); they get
    # `source=None` and name what they read in `observes()`.
    uses_input: ClassVar[bool] = True

    def __init__(
        self,
        name: str,
        cfg: dict,
        source: InputDevice | None,
        robot: Robot,
        robot_id: str,
    ):
        self.name, self.cfg, self.source, self.robot, self.robot_id = (
            name,
            cfg,
            source,
            robot,
            robot_id,
        )
        self.deadline_ms = positive(
            cfg.get("command_deadline_ms"), f"{name}.command_deadline_ms"
        )
        self.publisher = Publisher(name)
        # the saved pose `home` moves this pair to (leader and robot), if configured
        self.home: HomeSpec | None = None

    def command(self, target: list[float], now_ns: int, **extra: object) -> Envelope:
        return make_command(
            self.publisher,
            robot_id=self.robot_id,
            unit=self.robot.unit,
            target=target,
            now_ns=now_ns,
            deadline_ms=self.deadline_ms,
            **extra,
        )

    @abstractmethod
    def update(
        self,
        intent: Envelope,
        follower: list[float],
        now_ns: int | None = None,
        follower_target: list[float] | None = None,
        follower_velocity: list[float] | None = None,
    ) -> Envelope | None:
        """Return the next command, or None when the robot must not move.

        `follower_target` is the goal the robot currently holds or tracks; controllers limit
        their steps from it so they never drift away from what the follower actually does.
        `follower_velocity` is the measured velocity, when the robot reports one.
        """

    @abstractmethod
    def reset(self) -> None:
        """Require re-alignment, e.g. after the robot latched FAULT or ESTOP."""

    def observes(self) -> list[str]:
        """Inputs and sensors whose samples this controller reads besides its input."""
        return []

    def status(self) -> dict:
        """Why the controller is (not) commanding, for the operator screen. Override to add fields."""
        return {}
