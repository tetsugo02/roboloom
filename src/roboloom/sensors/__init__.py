"""Sensors selected by `sensors.<name>.type`. Register new devices here.

Subpackages are modalities (`vision`, `tactile`, `audio`). Each modality's `base`
defines stream types that fix the payload and LeRobot features; a device module
next to it subclasses one and only implements `open_device`.
"""

from ..core.registry import Registry
from ..core.source import Source

SENSORS: Registry[Source] = Registry("sensor", {
    "realsense_rgb": "roboloom.sensors.vision.realsense:RealSenseRGB",
    "digit": "roboloom.sensors.tactile.digit:DigitSensor",
    "pcm_mono": "roboloom.sensors.audio.microphone:SoundDeviceMic",
})
