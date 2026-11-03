"""Pika Gripper hardware description: one joint, the motor angle in rad.

0 rad is closed (after the gripper's zero is set); the opening grows with the angle up to
the 1.67 rad the vendor's ROS node allows (about 97 mm by the SDK's linkage model, not
measured). The width in mm is not used: the motor angle is what the device commands and
reports.
"""

from __future__ import annotations

JOINTS = ("gripper",)
UNIT = "rad"
RANGE = {"gripper": (0.0, 1.67)}
REST = (0.0,)  # closed; the mock bus starts here
MAX_CURRENT_A = 2.0  # the SDK's documented range for the current limit is 0~2 A


def check_within_range(limits: list[dict], name: str) -> None:
    """Refuse `limits` that reach beyond the gripper's range."""
    for limit in limits:
        low, high = RANGE[limit["name"]]
        if limit["min"] < low - 1e-6 or limit["max"] > high + 1e-6:
            raise ValueError(
                f"{name}.limits.{limit['name']}: [{limit['min']}, {limit['max']}] rad "
                f"exceeds the Pika Gripper range [{low}, {high}] rad"
            )
