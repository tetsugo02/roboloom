"""Tactile stream types.

Camera-based tactile sensors (DIGIT, GelSight) produce RGB frames and are stored
like vision streams. Force or taxel-array sensors add their own stream type here.
"""

from __future__ import annotations

from ..vision.base import ImageSensor


class TactileImageSensor(ImageSensor):
    """Tactile sensor whose reading is an RGB image of the contact surface."""
