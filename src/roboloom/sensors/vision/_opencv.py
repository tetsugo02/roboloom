"""Shared synchronous OpenCV capture reader; importing this module needs no cv2."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol

import numpy as np

from ...core.source import Sample

LOST_S = 1.0


def fourcc_name(code: int) -> str:
    """The four characters of an OpenCV FOURCC code, e.g. 1196444237 -> "MJPG"."""
    return "".join(chr((code >> (8 * i)) & 0xFF) for i in range(4))


class Capture(Protocol):
    def read(self) -> tuple[bool, np.ndarray | None]: ...
    def release(self) -> None: ...


class ColorConverter(Protocol):
    @property
    def COLOR_BGR2RGB(self) -> int: ...
    def cvtColor(self, frame: np.ndarray, code: int) -> np.ndarray: ...


class OpenCVReader:
    def __init__(
        self,
        capture: Capture,
        cv2: ColorConverter,
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
