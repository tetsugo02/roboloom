"""Rakuda2 hardware description: 17 Dynamixel joints in robopy's canonical order.

Shared by the follower and the leader arm in `roboloom.inputs.rakuda2`.
"""

from __future__ import annotations

from ...drivers.dynamixel import DynamixelBus
from ...drivers.mock import MockBus
from ..base import RobotBus

JOINTS = (
    "torso_yaw", "head_yaw", "head_pitch",
    "r_arm_sh_pitch1", "r_arm_sh_roll", "r_arm_sh_pitch2", "r_arm_el_yaw",
    "r_arm_wr_roll", "r_arm_wr_yaw", "r_arm_grip",
    "l_arm_sh_pitch1", "l_arm_sh_roll", "l_arm_sh_pitch2", "l_arm_el_yaw",
    "l_arm_wr_roll", "l_arm_wr_yaw", "l_arm_grip",
)
MOTOR_IDS = (27, 28, 29, 1, 3, 5, 7, 9, 11, 31, 2, 4, 6, 8, 10, 12, 30)
UNIT = "dynamixel_count"


def check_motor_ids(cfg: dict, name: str) -> None:
    if cfg.get("motor_ids") != list(MOTOR_IDS):
        raise ValueError(f"{name}: Rakuda2 motor IDs/order must match explicit canonical mapping")


def open_rakuda_bus(port: str, mock: bool) -> RobotBus:
    return MockBus(dimension=len(JOINTS)) if mock else DynamixelBus(port, list(MOTOR_IDS))
