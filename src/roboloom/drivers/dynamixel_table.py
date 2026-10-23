"""Dynamixel X-series control table and per-model units (ROBOTIS e-Manual, checked 2026-10-23)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Register:
    address: int
    size: int
    eeprom: bool = False


REGISTERS = {
    "model_number": Register(0, 2, True),
    "return_delay": Register(9, 1, True),  # 2 us per count
    "drive_mode": Register(10, 1, True),
    "operating_mode": Register(11, 1, True),
    "homing_offset": Register(20, 4, True),
    "current_limit": Register(38, 2, True),
    "velocity_limit": Register(44, 4, True),
    "max_position_limit": Register(48, 4, True),
    "min_position_limit": Register(52, 4, True),
    "shutdown": Register(63, 1, True),
    "torque_enable": Register(64, 1),
    "hardware_error": Register(70, 1),
    "bus_watchdog": Register(98, 1),  # 20 ms per count; reads -1 after it fired
    "goal_current": Register(102, 2),
    "goal_position": Register(116, 4),
    "present_current": Register(126, 2),
    "present_velocity": Register(128, 4),
    "present_position": Register(132, 4),
    "present_temperature": Register(146, 1),
}

# Present current, velocity and position are contiguous: one 10-byte sync read.
STATE_ADDRESS, STATE_SIZE = 126, 10

OPERATING_MODES = {
    "current": 0,
    "velocity": 1,
    "position": 3,
    "extended_position": 4,
    "current_position": 5,
    "pwm": 16,
}

COUNTS_PER_REV = 4096
VELOCITY_RPM = 0.229  # per count, all X-series
WATCHDOG_MS = 20


@dataclass(frozen=True)
class Model:
    name: str
    current_mA: float  # per count of goal/present current and current limit


MODELS = {
    1020: Model("XM430-W350", 2.69),
    1120: Model("XM540-W270", 2.69),
    1220: Model("XC330-T288", 1.0),
}


def model_by_name(name: str) -> int:
    for number, model in MODELS.items():
        if model.name == name:
            return number
    raise ValueError(
        f"unknown Dynamixel model {name!r}; add it to MODELS from the e-Manual"
    )
