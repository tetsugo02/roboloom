"""Write the EEPROM registers (Operating Mode, Current Limit) a node's configuration expects."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..errors import Cancelled, ConfigError, HardwareError
from ..operator import Operator
from .common import experiment_node, require_hardware

REGISTERS = ("operating_mode", "current_limit")


@dataclass
class RegisterChange:
    joint: str
    index: int  # position on the node's bus
    register: str
    current: int
    target: int  # raw register value


@dataclass
class CommissionPlan:
    node: str
    port: str
    ids: list[int]
    changes: list[RegisterChange] = field(default_factory=list)

    def lines(self) -> list[str]:
        return [
            f"{c.joint}: {c.register} {c.current} -> {c.target}" for c in self.changes
        ]


def _open(port: str, ids: list[int]):
    from ..drivers.dynamixel import DynamixelBus

    return DynamixelBus(port, ids)


def plan_commission(
    experiment: str | Path, node: str, *, hardware: bool = False
) -> CommissionPlan:
    """Read the node's EEPROM and list the values that differ from its configuration."""
    cfg, owner = experiment_node(experiment, node)
    expected = getattr(owner, "expected_eeprom", None)
    if expected is None:
        raise ConfigError(f"{node}: not a commissionable Dynamixel node")
    require_hardware(cfg, hardware, "commission")
    joints, ids, want = expected()
    plan = CommissionPlan(node, str(getattr(owner, "port", "")), list(ids))
    bus = _open(plan.port, plan.ids)
    try:
        units = bus.current_units_mA()
        for register in REGISTERS:
            values = bus.read_register(register)
            for i, joint in enumerate(joints):
                if joint not in want.get(register, {}):
                    continue
                target = want[register][joint]
                raw = (
                    int(target)
                    if register == "operating_mode"
                    else round(target / units[i])
                )
                if raw != values[i]:
                    plan.changes.append(
                        RegisterChange(joint, i, register, int(values[i]), raw)
                    )
    finally:
        bus.close()
    return plan


def apply_commission(plan: CommissionPlan, operator: Operator) -> int:
    """Write the plan after the operator confirms; returns how many values were written
    (each write is read back by the driver). Refuses while any of the motors is torqued."""
    if not plan.changes:
        return 0
    bus = _open(plan.port, plan.ids)
    try:
        torque = bus.read_register("torque_enable")
        if any(torque[c.index] for c in plan.changes):
            raise HardwareError(
                "torque is on for some of these motors; support the arm, release it, then retry"
            )
        if not operator.confirm(
            f"{plan.node}: write {len(plan.changes)} EEPROM values."
        ):
            raise Cancelled("commission cancelled; nothing was written")
        for register in REGISTERS:
            items = {c.index: c.target for c in plan.changes if c.register == register}
            for value in sorted(set(items.values())):
                indices = [i for i, v in items.items() if v == value]
                bus.write_eeprom(register, indices, [value] * len(indices))
    finally:
        bus.close()
    return len(plan.changes)
