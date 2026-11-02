"""PiPER hardware description: six joints in rad, in the SDK's order (joint1 = base yaw).

The ranges are the vendor's joint limits (piper_sdk `JointCtrl`); a follower's `limits`
must lie inside them. Per-unit zero offsets and signs are not corrected here: probe the
arm (`roboloom probe <can>`) to compare.
"""

from __future__ import annotations

import math

JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5", "joint6")
UNIT = "rad"
RANGE = {
    "joint1": (-math.radians(150), math.radians(150)),
    "joint2": (0.0, math.radians(180)),
    "joint3": (-math.radians(170), 0.0),
    "joint4": (-math.radians(100), math.radians(100)),
    "joint5": (-math.radians(70), math.radians(70)),
    "joint6": (-math.radians(120), math.radians(120)),
}
# The pose the arm folds into at power-off (all joints 0); the mock bus starts here.
REST = (0.0,) * len(JOINTS)


def check_within_range(limits: list[dict], name: str) -> None:
    """Refuse `limits` that reach beyond the vendor's joint range."""
    for limit in limits:
        low, high = RANGE[limit["name"]]
        if limit["min"] < low - 1e-6 or limit["max"] > high + 1e-6:
            raise ValueError(
                f"{name}.limits.{limit['name']}: [{limit['min']}, {limit['max']}] rad "
                f"exceeds the PiPER range [{low:.4f}, {high:.4f}] rad"
            )
