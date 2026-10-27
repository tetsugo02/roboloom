"""Rakuda2 hardware description: 17 Dynamixel joints in robopy's canonical order.

Shared by the follower and by Rakuda-mini, its teleoperation arm (`roboloom.inputs.rakuda_mini`).
"""

from __future__ import annotations

import sys

from ...drivers.dynamixel_table import model_by_name
from ...drivers.mock import MockBus
from ..base import RobotBus

JOINTS = (
    "torso_yaw",
    "head_yaw",
    "head_pitch",
    "r_arm_sh_pitch1",
    "r_arm_sh_roll",
    "r_arm_sh_pitch2",
    "r_arm_el_yaw",
    "r_arm_wr_roll",
    "r_arm_wr_yaw",
    "r_arm_grip",
    "l_arm_sh_pitch1",
    "l_arm_sh_roll",
    "l_arm_sh_pitch2",
    "l_arm_el_yaw",
    "l_arm_wr_roll",
    "l_arm_wr_yaw",
    "l_arm_grip",
)
MOTOR_IDS = (27, 28, 29, 1, 3, 5, 7, 9, 11, 31, 2, 4, 6, 8, 10, 12, 30)
UNIT = "dynamixel_count"

_SHOULDER = (
    "torso_yaw",
    "r_arm_sh_pitch1",
    "r_arm_sh_roll",
    "l_arm_sh_pitch1",
    "l_arm_sh_roll",
)
FOLLOWER_MODELS = tuple(
    "XM540-W270" if j in _SHOULDER else "XM430-W350" for j in JOINTS
)
RAKUDA_MINI_MODELS = tuple(
    "XM430-W350" if j == "torso_yaw" else "XC330-T288" for j in JOINTS
)

# EEPROM registers verified at startup; a node YAML `registers:` section can name more.
# Values: operating_mode/drive_mode/shutdown raw, current_limit in mA, return_delay in us.
REGISTERS = (
    "operating_mode",
    "drive_mode",
    "homing_offset",
    "current_limit",
    "return_delay",
    "shutdown",
)


def check_motor_ids(cfg: dict, name: str) -> None:
    if cfg.get("motor_ids") != list(MOTOR_IDS):
        raise ValueError(
            f"{name}: Rakuda2 motor IDs/order must match explicit canonical mapping"
        )


def expected_registers(cfg: dict, name: str) -> dict[str, dict[str, float]]:
    """`registers: {operating_mode: {default: 3, r_arm_grip: 5}, ...}` -> per-joint values.

    With a `control` section, Operating Mode follows from the laws; listed values must agree.
    """
    raw = cfg.get("registers")
    has_control = "control" in cfg
    if (
        not isinstance(raw, dict)
        or not set(raw) <= set(REGISTERS)
        or ("operating_mode" not in raw and not has_control)
    ):
        raise ValueError(
            f"{name}.registers must list operating_mode (or use control) and may list {', '.join(REGISTERS[1:])}"
        )
    out: dict[str, dict[str, float]] = {}
    for register, values in raw.items():
        if not isinstance(values, dict) or not set(values) <= {"default", *JOINTS}:
            raise ValueError(
                f"{name}.registers.{register}: map 'default' or joint names to values"
            )
        default = values.get("default")
        chosen = {j: values.get(j, default) for j in JOINTS}
        out[register] = {j: float(v) for j, v in chosen.items() if v is not None}
    if has_control:
        from ...control.device import expected_modes, parse_groups

        derived = expected_modes(parse_groups(cfg["control"], JOINTS, name))
        clash = [
            j
            for j, v in out.get("operating_mode", {}).items()
            if j in derived and derived[j] != v
        ]
        if clash:
            raise ValueError(
                f"{name}: registers.operating_mode disagrees with control laws for {clash}"
            )
        out["operating_mode"] = {**out.get("operating_mode", {}), **derived}
    return out


def mock_modes(cfg: dict, name: str) -> list[int]:
    """Operating modes a commissioned robot would report, for the mock bus."""
    modes = expected_registers(cfg, name).get("operating_mode", {})
    return [int(modes.get(j, 3)) for j in JOINTS]


def open_rakuda_bus(
    port: str,
    mock: bool,
    models: tuple[str, ...],
    cfg: dict,
    name: str,
    limits: list[dict] | None = None,
) -> RobotBus:
    """Open the bus and refuse to continue when the motors' EEPROM differs from `cfg.registers`."""
    if mock:
        return MockBus(dimension=len(JOINTS), modes=mock_modes(cfg, name))
    from ...drivers.dynamixel import DynamixelBus, latency_timer_ms, verify

    latency = latency_timer_ms(port)
    if latency is not None and latency > 1:
        print(
            f"{name}: {port} latency_timer is {latency} ms; set it to 1 ms for full bus speed",
            file=sys.stderr,
        )
    bus = DynamixelBus(port, list(MOTOR_IDS), [model_by_name(m) for m in models])
    try:
        problems = verify(bus, list(JOINTS), expected_registers(cfg, name), limits)
        if problems:
            raise RuntimeError(
                f"{name}: motor configuration differs from {name} YAML:\n  "
                + "\n  ".join(problems)
            )
        bus.set_bus_watchdog(cfg.get("bus_watchdog_ms"))
    except BaseException:
        bus.close()
        raise
    return bus
