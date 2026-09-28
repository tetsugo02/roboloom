"""Rakuda2 leader arm: the follower's joints, read-only, published as joint intents."""

from __future__ import annotations

from ...core.checks import identity
from ...robots.base import RobotBus
from ...robots.rakuda2.spec import JOINTS, UNIT, check_motor_ids, open_rakuda_bus
from ..base import JointInput


class RakudaLeader(JointInput):
    def __init__(self, name: str, cfg: dict):
        super().__init__(name, cfg, JOINTS, UNIT)
        check_motor_ids(cfg, name)
        self.port = identity(cfg.get("port"), f"{name}.port")

    def device_ids(self) -> tuple[str, ...]:
        return (self.port,)

    def open_bus(self, mock: bool) -> RobotBus:
        return open_rakuda_bus(self.port, mock)
