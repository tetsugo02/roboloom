"""Intel RealSense colour stream (extra: hardware)."""

from __future__ import annotations

import sys
import time
from importlib import import_module
from typing import Any

import numpy as np

from ...core.checks import identity, positive
from ...core.source import Reader, Sample
from .base import ImageSensor


class RealSenseReader:
    def __init__(self, pipeline: Any, timeout_ms: int):
        self.pipeline, self.timeout_ms = pipeline, timeout_ms

    def read(self) -> Sample | None:
        ok, frames = self.pipeline.try_wait_for_frames(self.timeout_ms)
        frame = frames.get_color_frame() if ok else None
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
        conf.enable_stream(
            rs.stream.color, self.shape[1], self.shape[0], rs.format.rgb8, int(self.fps)
        )
        profile = pipeline.start(conf)
        usb = profile.get_device().get_info(rs.camera_info.usb_type_descriptor)
        if not usb.startswith("3"):
            print(
                f"{self.name}: RealSense {self.serial} is on USB {usb}; frames may drop",
                file=sys.stderr,
            )
        # Wait at most one frame period per tick so a stalled camera never blocks the node for long.
        return RealSenseReader(pipeline, max(1, int(1000 / self.fps)))
