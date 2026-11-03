"""Pika Sense hardware description (from the vendor's pika_sdk; not measured here).

`TRACKER_TO_SENSE` moves the Vive tracker's pose to the centre between the Sense's jaws,
as pika_sdk's `PRODUCT_TRANSFORMS["sense"]` does (`pika/tracker/vive_tracker.py`):
roll -20 deg, then roll -90 deg and pitch -90 deg, then (0.172, 0, -0.076) m.
"""

from __future__ import annotations

import math

from ...kinematics.spec import pose_xyz_rpy

TRACKER_TO_SENSE = (
    pose_xyz_rpy((0, 0, 0), (-math.radians(20), 0, 0))
    @ pose_xyz_rpy((0, 0, 0), (-math.pi / 2, -math.pi / 2, 0))
    @ pose_xyz_rpy((0.172, 0.0, -0.076), (0, 0, 0))
)
JAW_RANGE = (0.0, 1.67)  # rad, the encoder angle of the jaws (closed .. open)
LIGHT, VIBRATE = 50, 51  # serial commands (not sent yet)
