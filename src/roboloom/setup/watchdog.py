"""Bench test: does the Dynamixel Bus Watchdog stop a current-mode motor when the host goes silent?"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from ..drivers.dynamixel_table import OPERATING_MODES
from ..errors import Cancelled, ConfigError, HardwareError
from ..operator import Operator
from .common import experiment_node, require_hardware


@dataclass
class WatchdogResult:
    joint: str
    period_ms: float
    current_mA: float
    readings: dict[str, object]  # before and after the silence, see `watchdog_trial`

    @property
    def fired(self) -> bool:
        after = self.readings.get("watchdog_after")
        return isinstance(after, int) and after < 0

    @property
    def stopped(self) -> bool:
        after = self.readings.get("current_after_mA")
        return isinstance(after, float) and abs(after) < 0.3 * abs(self.current_mA)

    @property
    def passed(self) -> bool:
        return self.fired and self.stopped

    def lines(self) -> list[str]:
        out = [
            f"{k}: {v:.1f}" if isinstance(v, float) else f"{k}: {v}"
            for k, v in self.readings.items()
        ]
        out.append(
            f"watchdog {'fired' if self.fired else 'DID NOT FIRE'} after {self.period_ms} ms "
            f"of silence; motor current {'dropped' if self.stopped else 'DID NOT DROP'}"
        )
        out.append(
            "PASS: silence stops this motor"
            if self.passed
            else "FAIL: do not rely on the watchdog; keep the arm supported"
        )
        return out


def watchdog_trial(
    bus, current_mA: float, period_ms: float, sleep=time.sleep
) -> dict[str, object]:
    """Push one current-mode motor with `current_mA`, go silent, and read what the motor did.

    `bus` holds exactly one motor. Returns readings before and after the silence; the
    motor is left with zero goal current, torque off and the watchdog cleared.
    """
    if bus.read_register("operating_mode") != [OPERATING_MODES["current"]]:
        raise HardwareError("the motor is not in current mode; commission it first")
    if any(bus.read_register("torque_enable")):
        raise HardwareError("torque is on; stop the dataflow first")
    out: dict[str, object] = {}
    try:
        bus.write_goal_currents([0], [0.0])
        bus.set_bus_watchdog(period_ms)
        bus.set_torque([0], True)
        bus.write_goal_currents([0], [current_mA])
        currents_mA: list[float] | None = None
        for _ in range(10):  # keep talking: the watchdog must not fire yet
            sleep(period_ms / 4000)
            currents_mA = bus.read_state().currents_mA
        out["current_before_mA"] = currents_mA[0] if currents_mA else None
        out["watchdog_before"] = bus.read_register("bus_watchdog")[0]
        # silence: the host process died or the cable came out
        sleep(3 * period_ms / 1000)
        out["watchdog_after"] = bus.read_register("bus_watchdog")[0]
        out["torque_after"] = bus.read_register("torque_enable")[0]
        out["goal_current_after_mA"] = bus.read_goal_currents()[0]
        state = bus.read_state()
        out["current_after_mA"] = state.currents_mA[0] if state.currents_mA else None
        out["hardware_error_after"] = bus.read_register("hardware_error")[0]
        bus.write_goal_currents([0], [0.0])  # does a fired watchdog refuse new goals?
        out["goal_after_zero_write_mA"] = bus.read_goal_currents()[0]
    finally:
        bus.set_torque([0], False)
        bus.set_bus_watchdog(None)  # clears the fired state
        bus.write_goal_currents([0], [0.0])
    return out


def watchdog_test(
    experiment: str | Path,
    node: str,
    joint: str,
    operator: Operator,
    current_mA: float = 30.0,
    *,
    hardware: bool = False,
) -> WatchdogResult:
    from ..drivers.dynamixel import DynamixelBus

    cfg, owner = experiment_node(experiment, node)
    expected = getattr(owner, "expected_eeprom", None)
    if expected is None:
        raise ConfigError(f"{node}: not a Dynamixel node")
    require_hardware(cfg, hardware, "watchdog-test")
    period_ms = getattr(owner, "cfg", {}).get("bus_watchdog_ms")
    if not period_ms:
        raise ConfigError(f"{node}: bus_watchdog_ms is not set")
    joints, ids, _ = expected()
    if joint not in joints:
        raise ConfigError(f"{joint}: not a joint of {node}")
    motor_id = ids[joints.index(joint)]
    if not operator.confirm(
        f"{joint} (ID {motor_id}) will push with {current_mA:g} mA for about "
        f"{0.6 + 3 * period_ms / 1000:.1f} s. Support the arm."
    ):
        raise Cancelled("watchdog-test cancelled")
    bus = DynamixelBus(str(getattr(owner, "port", "")), [motor_id])
    try:
        readings = watchdog_trial(bus, current_mA, period_ms)
    finally:
        bus.close()
    return WatchdogResult(joint, period_ms, current_mA, readings)
