"""USB (UVC) cameras through Video4Linux2 and OpenCV (extra: hardware), e.g. the
fisheye cameras on the Pika Sense and Pika Gripper.

Name a camera by a stable path: `/dev/v4l/by-path/...-video-index0` follows the USB
socket and `/dev/v4l/by-id/...` the camera model; `/dev/video<n>` can change between
boots. Opening sets the pixel format, size and rate and refuses a camera that does not
deliver them (OpenCV would otherwise fall back silently).
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from importlib import import_module
from typing import Any

import numpy as np

from ...core.checks import identity, positive
from ...core.source import Reader, Sample
from .base import ImageSensor

FORMATS = ("MJPG", "YUYV")
LOST_S = 1.0  # no frame for this long: the camera is gone
HINT = (
    "list the cameras with `ls -l /dev/v4l/by-path/` and what one delivers with "
    "`v4l2-ctl -d <device> --list-formats-ext` (package v4l-utils)"
)


class V4l2Reader:
    def __init__(
        self,
        capture: Any,
        cv2: Any,
        device: str,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.capture, self.cv2, self.device, self.clock = capture, cv2, device, clock
        self.last_frame = clock()

    def read(self) -> Sample | None:
        ok, frame = self.capture.read()
        now = self.clock()
        if not ok or frame is None:
            if now - self.last_frame > LOST_S:
                raise ConnectionError(
                    f"{self.device}: no frame for {now - self.last_frame:.1f} s "
                    "(cable or camera lost)"
                )
            return None
        self.last_frame = now
        rgb = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2RGB)
        return Sample(np.ascontiguousarray(rgb), time.monotonic_ns())

    def close(self) -> None:
        self.capture.release()


class V4l2RGB(ImageSensor):
    """Keys: `device` (a /dev/v4l/by-path/... or by-id path), `width`, `height`, `fps`,
    `format` (MJPG, the default, or YUYV)."""

    def __init__(self, name: str, cfg: dict):
        super().__init__(name, cfg)
        self.device = identity(cfg.get("device"), f"{name}.device")
        self.fps = positive(cfg.get("fps"), f"{name}.fps")
        self.format = cfg.get("format", "MJPG")
        if self.format not in FORMATS:
            raise ValueError(f"{name}.format must be one of {list(FORMATS)}")

    def device_ids(self) -> tuple[str, ...]:
        # the same camera under two names (by-path and by-id) is still one camera
        real = os.path.realpath(self.device)
        return (self.device,) if real == self.device else (self.device, real)

    def open_device(self) -> Reader:
        cv2 = import_module("cv2")
        path = os.path.realpath(self.device)
        capture = cv2.VideoCapture(path, cv2.CAP_V4L2)
        if not capture.isOpened():
            raise ConnectionError(f"{self.name}: cannot open {self.device}; {HINT}")
        height, width, _ = self.shape
        try:
            capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.format))
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            capture.set(cv2.CAP_PROP_FPS, float(self.fps))
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # the newest frame, not a backlog
            got = (
                int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                float(capture.get(cv2.CAP_PROP_FPS)),
                _fourcc(int(capture.get(cv2.CAP_PROP_FOURCC))),
            )
            wanted = (width, height, float(self.fps), self.format)
            if (
                got[:2] != wanted[:2]
                or got[3] != wanted[3]
                or abs(got[2] - wanted[2]) > 0.5
            ):
                raise ValueError(
                    f"{self.name}: {self.device} delivers {got[0]}x{got[1]} "
                    f"{got[2]:g} fps {got[3]}, not {width}x{height} {self.fps:g} fps "
                    f"{self.format}; {HINT}"
                )
        except BaseException:
            capture.release()
            raise
        return V4l2Reader(capture, cv2, self.device)


def _fourcc(code: int) -> str:
    return "".join(chr((code >> (8 * i)) & 0xFF) for i in range(4))
