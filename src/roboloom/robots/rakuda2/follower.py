"""Rakuda2 follower: the follower node's exclusive owner of the follower bus."""

from __future__ import annotations

from ...control.device import law_class
from ...core.checks import identity
from ..base import Follower, JointBus, SafetyTraits
from .spec import (
    FOLLOWER_MODELS,
    JOINTS,
    MOTOR_IDS,
    UNIT,
    check_motor_ids,
    expected_registers,
    open_rakuda_bus,
)


class RakudaFollower(Follower):
    model = "rakuda2"
    effort_signal = ("currents_mA", "mA")

    def __init__(self, name: str, cfg: dict):
        super().__init__(name, cfg, JOINTS, UNIT)
        check_motor_ids(cfg, name)
        expected_registers(cfg, name)
        self.port = identity(cfg.get("port"), f"{name}.port")

    def declared_traits(self) -> SafetyTraits:
        # The arms and head fall without torque. Position-mode joints keep their last goal
        # when the node stops writing; current-mode joints go limp (JointDevice.close and
        # the bus watchdog), so a follower running current laws does not hold.
        current = any(law_class(g.law).current_mode for g in self.control or [])
        return SafetyTraits(
            torque_off="falls", unattended="torque_off" if current else "holds"
        )

    def expected_eeprom(
        self,
    ) -> tuple[list[str], list[int], dict[str, dict[str, float]]]:
        """Joints, motor IDs and the EEPROM values `roboloom commission` writes."""
        return list(JOINTS), list(MOTOR_IDS), expected_registers(self.cfg, self.name)

    def current_limits_mA(self) -> dict[str, float]:
        return expected_registers(self.cfg, self.name).get("current_limit", {})

    def device_ids(self) -> tuple[str, ...]:
        return (self.port,)

    def open_bus(self, mock: bool) -> JointBus:
        return open_rakuda_bus(
            self.port, mock, FOLLOWER_MODELS, self.cfg, self.name, self.limits
        )
