"""USB / built-in RGB cameras via OpenCV, hardware unverified."""

from __future__ import annotations

import math
import os
import sys
import warnings
from importlib import import_module
from pathlib import PurePosixPath
from typing import Protocol, cast

from ...core.checks import positive
from ...core.source import Reader
from ._opencv import Capture, ColorConverter, OpenCVReader, fourcc_name
from .base import ImageSensor

BACKENDS = {
    "linux": {"v4l2": 200},
    "darwin": {"avfoundation": 1200},
    "win32": {"msmf": 1400, "dshow": 700},
}


class VideoCapture(Capture, Protocol):
    def isOpened(self) -> bool: ...
    def set(self, prop: int, value: float) -> bool: ...
    def get(self, prop: int) -> float: ...


class OpenCV(ColorConverter, Protocol):
    CAP_PROP_FOURCC: int
    CAP_PROP_FRAME_WIDTH: int
    CAP_PROP_FRAME_HEIGHT: int
    CAP_PROP_FPS: int
    CAP_PROP_BUFFERSIZE: int

    def VideoCapture(self, device: int | str, api: int) -> VideoCapture: ...
    def VideoWriter_fourcc(self, *chars: str) -> int: ...


class OpenCVRGB(ImageSensor):
    """HWC uint8 RGB. Size is strict; fps and optional transport format are requests.

    Constructing or opening in mock mode never imports OpenCV or opens a camera.
    """

    def __init__(self, name: str, cfg: dict):
        super().__init__(name, cfg)
        device = cfg.get("device")
        if isinstance(device, bool) or not (
            isinstance(device, int)
            and device >= 0
            or isinstance(device, str)
            and device.startswith("/dev/")
            and ".." not in PurePosixPath(device).parts
        ):
            raise ValueError(
                f"{name}.device: expected non-negative index or /dev/ path"
            )
        self.device: int | str = device
        self.backend = cfg.get("backend", "auto")
        if self.backend not in ("auto", "v4l2", "avfoundation", "msmf", "dshow"):
            raise ValueError(
                f"{name}.backend: expected auto, v4l2, avfoundation, msmf or dshow"
            )
        if isinstance(device, str) and self.backend not in ("auto", "v4l2"):
            raise ValueError(f"{name}.device: paths require the v4l2 backend")
        for key in ("width", "height"):
            value = cfg.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name}.{key}: expected positive integer")
        self.fps = positive(cfg.get("fps"), f"{name}.fps")
        self.format = cfg.get("format")
        if self.format is not None and self.format not in ("MJPG", "YUYV"):
            raise ValueError(f"{name}.format: expected MJPG or YUYV")

    def device_ids(self) -> tuple[str, ...]:
        if isinstance(self.device, str):
            path = self.device
        elif (
            self.backend == "v4l2" or self.backend == "auto" and sys.platform == "linux"
        ):
            path = f"/dev/video{self.device}"
        else:
            return (f"opencv:camera:{self.device}",)
        return tuple(dict.fromkeys((path, os.path.realpath(path))))

    def open_device(self) -> Reader:
        choices = BACKENDS.get(sys.platform, {})
        backend = next(iter(choices), "") if self.backend == "auto" else self.backend
        if backend not in choices or isinstance(self.device, str) and backend != "v4l2":
            raise ValueError(
                f"{self.name}: backend {backend!r} / device {self.device!r} unavailable on {sys.platform}"
            )
        try:
            cv2 = cast(OpenCV, import_module("cv2"))
        except ImportError as exc:  # missing, or a broken / mixed cv2 install
            raise type(exc)(
                f"cannot import OpenCV ({exc}); it is a core dependency "
                "(opencv-python-headless): reinstall roboloom or run uv sync"
            ) from exc
        device = (
            os.path.realpath(self.device)
            if isinstance(self.device, str)
            else self.device
        )
        capture = cv2.VideoCapture(device, choices[backend])
        context = f"{self.name}: {self.device} ({backend})"
        try:
            if not capture.isOpened():
                raise ConnectionError(
                    f"{context}: cannot open camera; check device index/path, camera permissions and other applications"
                )
            if self.format is not None:
                wanted = cv2.VideoWriter_fourcc(*self.format)
                accepted = capture.set(cv2.CAP_PROP_FOURCC, wanted)
                reported = capture.get(cv2.CAP_PROP_FOURCC)
                self._warn_setting(
                    context,
                    "format",
                    self.format,
                    fourcc_name(int(reported))
                    if math.isfinite(reported) and reported > 0
                    else f"{reported:g}",
                    accepted and reported == wanted,
                )
            height, width, _ = self.shape
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            accepted = capture.set(cv2.CAP_PROP_FPS, float(self.fps))
            reported = capture.get(cv2.CAP_PROP_FPS)
            self._warn_setting(
                context,
                "fps",
                self.fps,
                f"{reported:g}",
                accepted
                and math.isfinite(reported)
                and reported > 0
                and abs(reported - self.fps) <= 0.5,
            )
            capture.set(
                cv2.CAP_PROP_BUFFERSIZE, 1
            )  # best effort; not a newest-frame guarantee
        except BaseException:
            capture.release()
            raise
        # Size is checked on actual frames (ImageSensor.open wraps this reader),
        # not on the unreliable width/height property readback.
        return OpenCVReader(capture, cv2, str(self.device))

    @staticmethod
    def _warn_setting(
        context: str, key: str, requested: str | float, reported: str, matches: bool
    ) -> None:
        if not matches:
            warnings.warn(
                f"{context}: {key} requested={requested}, reported={reported}; setting unsupported, unconfirmed or different",
                RuntimeWarning,
                stacklevel=3,
            )
