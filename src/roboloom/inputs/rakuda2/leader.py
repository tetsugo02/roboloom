"""Rakuda2 leader arm: the follower's joints, read-only, published as joint intents."""

from __future__ import annotations

from ...core.checks import identity
from ...robots.base import RobotBus
from ...robots.rakuda2.spec import (
    JOINTS,
    LEADER_MODELS,
    MOTOR_IDS,
    UNIT,
    check_motor_ids,
    expected_registers,
    open_rakuda_bus,
)
from ..base import JointInput


class RakudaLeader(JointInput):
    def __init__(self, name: str, cfg: dict):
        super().__init__(name, cfg, JOINTS, UNIT)
        check_motor_ids(cfg, name)
        expected_registers(cfg, name)
        self.port = identity(cfg.get("port"), f"{name}.port")

    def expected_eeprom(self) -> tuple[list[str], list[int], dict[str, dict[str, float]]]:
        """Joints, motor IDs and the EEPROM values `roboloom commission` writes."""
        return list(JOINTS), list(MOTOR_IDS), expected_registers(self.cfg, self.name)

    def current_limits_mA(self) -> dict[str, float]:
        return expected_registers(self.cfg, self.name).get("current_limit", {})

    def device_ids(self) -> tuple[str, ...]:
        return (self.port,)

    def open_bus(self, mock: bool) -> RobotBus:
        return open_rakuda_bus(self.port, mock, LEADER_MODELS, self.cfg, self.name)
