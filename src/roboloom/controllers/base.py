"""Controller contract: one input's intents -> deadline-bound commands for one robot."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..core.checks import positive
from ..core.protocol import Envelope, Publisher
from ..inputs.base import InputDevice
from ..robots.base import Robot
from ..robots.safety import make_command


class Controller(ABC):
    def __init__(self, name: str, cfg: dict, source: InputDevice, robot: Robot, robot_id: str):
        self.name, self.cfg, self.source, self.robot, self.robot_id = name, cfg, source, robot, robot_id
        self.deadline_ms = positive(cfg.get("command_deadline_ms"), f"{name}.command_deadline_ms")
        self.publisher = Publisher(name)

    def command(self, target: list[float], now_ns: int, **extra: object) -> Envelope:
        return make_command(
            self.publisher, robot_id=self.robot_id, unit=self.robot.unit, target=target,
            now_ns=now_ns, deadline_ms=self.deadline_ms, **extra,
        )

    @abstractmethod
    def update(self, intent: Envelope, follower: list[float], now_ns: int | None = None) -> Envelope | None:
        """Return the next command, or None when the robot must not move."""

    @abstractmethod
    def reset(self) -> None:
        """Require re-alignment, e.g. after the robot latched FAULT or ESTOP."""
