"""Intel RealSense colour stream (extra: hardware)."""

from __future__ import annotations

import time
from importlib import import_module
from typing import Any

import numpy as np

from ...core.checks import identity, positive
from ...core.source import Reader, Sample
from .base import ImageSensor


class RealSenseReader:
    def __init__(self, pipeline: Any):
        self.pipeline = pipeline

    def read(self) -> Sample | None:
        frame = self.pipeline.wait_for_frames(timeout_ms=1000).get_color_frame()
        if not frame:
            return None
        return Sample(np.asarray(frame.get_data()).copy(), time.monotonic_ns())

    def close(self) -> None:
        self.pipeline.stop()


class RealSenseRGB(ImageSensor):
    def __init__(self, name: str, cfg: dict):
        super().__init__(name, cfg)
        self.serial = identity(cfg.get("serial"), f"{name}.serial")
        self.fps = positive(cfg.get("fps"), f"{name}.fps")

    def device_ids(self) -> tuple[str, ...]:
        return (self.serial,)

    def open_device(self) -> Reader:
        rs = import_module("pyrealsense2")

        pipeline = rs.pipeline()
        conf = rs.config()
        conf.enable_device(self.serial)
        conf.enable_stream(rs.stream.color, self.shape[1], self.shape[0], rs.format.rgb8, self.fps)
        pipeline.start(conf)
        return RealSenseReader(pipeline)
