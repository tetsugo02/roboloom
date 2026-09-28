"""DIGIT tactile sensor frames (extra: hardware)."""

from __future__ import annotations

import time
from importlib import import_module
from typing import Any

from ...core.checks import identity, positive
from ...core.source import Reader, Sample
from .base import TactileImageSensor


class DigitReader:
    def __init__(self, digit: Any):
        self.digit = digit

    def read(self) -> Sample:
        return Sample(self.digit.get_frame().copy(), time.monotonic_ns())

    def close(self) -> None:
        self.digit.disconnect()


class DigitSensor(TactileImageSensor):
    def __init__(self, name: str, cfg: dict):
        super().__init__(name, cfg)
        self.serial = identity(cfg.get("serial"), f"{name}.serial")
        self.fps = positive(cfg.get("fps"), f"{name}.fps")

    def device_ids(self) -> tuple[str, ...]:
        return (self.serial,)

    def open_device(self) -> Reader:
        Digit = import_module("digit_interface").Digit

        digit = Digit(serial=self.serial, name=self.cfg.get("name", self.serial))
        digit.connect()
        digit.set_fps(self.fps)
        return DigitReader(digit)
