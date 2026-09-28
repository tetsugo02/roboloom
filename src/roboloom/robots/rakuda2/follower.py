"""Rakuda2 follower: the robot node's exclusive owner of the follower bus."""

from __future__ import annotations

from ...core.checks import identity
from ..base import Robot, RobotBus
from .spec import JOINTS, UNIT, check_motor_ids, open_rakuda_bus


class RakudaFollower(Robot):
    robot_type = "rakuda2"

    def __init__(self, name: str, cfg: dict):
        super().__init__(name, cfg, JOINTS, UNIT)
        check_motor_ids(cfg, name)
        self.port = identity(cfg.get("port"), f"{name}.port")

    def device_ids(self) -> tuple[str, ...]:
        return (self.port,)

    def open_bus(self, mock: bool) -> RobotBus:
        return open_rakuda_bus(self.port, mock)
