"""DIGIT tactile sensor frames (extra: hardware)."""

from __future__ import annotations

import time
from importlib import import_module
from typing import Any

import numpy as np

from ...core.checks import identity, positive
from ...core.source import Reader, Sample
from .base import TactileImageSensor

# digit_interface streams; get_frame() transposes, so frames are (width, height, 3) of the stream.
RESOLUTIONS = {"QVGA": (320, 240), "VGA": (640, 480)}


class DigitReader:
    def __init__(self, digit: Any):
        self.digit = digit

    def read(self) -> Sample:
        frame = self.digit.get_frame()  # OpenCV BGR
        return Sample(np.ascontiguousarray(frame[..., ::-1]), time.monotonic_ns())

    def close(self) -> None:
        self.digit.disconnect()


class DigitSensor(TactileImageSensor):
    def __init__(self, name: str, cfg: dict):
        resolution = cfg.get("resolution", "QVGA")
        if resolution not in RESOLUTIONS:
            raise ValueError(f"{name}.resolution must be one of {sorted(RESOLUTIONS)}")
        height, width = RESOLUTIONS[resolution]
        if (cfg.get("height"), cfg.get("width")) != (height, width):
            raise ValueError(
                f"{name}: {resolution} frames are height {height}, width {width}"
            )
        super().__init__(name, cfg)
        self.resolution = resolution
        self.serial = identity(cfg.get("serial"), f"{name}.serial")
        self.fps = positive(cfg.get("fps"), f"{name}.fps")

    def device_ids(self) -> tuple[str, ...]:
        return (self.serial,)

    def open_device(self) -> Reader:
        Digit = import_module("digit_interface").Digit

        stream = Digit.STREAMS[self.resolution]
        if self.fps not in stream["fps"].values():
            raise ValueError(
                f"{self.name}: {self.resolution} supports fps {sorted(stream['fps'].values())}"
            )
        digit = Digit(serial=self.serial, name=self.cfg.get("name", self.serial))
        digit.connect()
        try:
            digit.set_resolution(stream)
            digit.set_fps(int(self.fps))
        except Exception:
            digit.disconnect()
            raise
        return DigitReader(digit)
