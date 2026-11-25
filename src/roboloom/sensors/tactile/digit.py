"""DIGIT tactile sensor frames (extra: digit)."""

from __future__ import annotations

import contextlib
import sys
import time
from collections.abc import Callable
from importlib import import_module
from typing import Any

import numpy as np

from ...core.checks import identity, positive
from ...core.source import Reader, Sample
from .base import TactileImageSensor
from .seam import find_seam

# digit_interface streams; get_frame() transposes, so frames are (width, height, 3) of the stream.
RESOLUTIONS = {"QVGA": (320, 240), "VGA": (640, 480)}

REOPEN_EVERY_S = 0.5  # fastest retry of a failed stream reopen


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


class DigitReader:
    """DIGIT frames, dropping seamed frames and reopening a rolled stream.

    A seam (`seam.find_seam`) marks a frame whose rows are circularly shifted or
    carry a pasted band; such a frame is dropped (read returns None). The roll
    persists until the stream is reopened, so `recover_after` consecutive seamed
    frames disconnect and open it again. A failed reopen is retried at most every
    0.5 s and raises ConnectionError once it has failed for longer than `lost_s`.
    """

    def __init__(
        self,
        open_digit: Callable[[], Any],
        name: str,
        *,
        seam_check: bool = True,
        recover_after: int = 3,
        warmup_frames: int = 10,
        lost_s: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
        log: Callable[[str], None] = _log,
    ):
        self.open_digit, self.name = open_digit, name
        self.seam_check, self.recover_after = seam_check, recover_after
        self.warmup_frames, self.lost_s = warmup_frames, lost_s
        self.clock, self.log = clock, log
        self.seams = 0
        self.recoveries = 0
        self.seam_row: int | None = None
        self._consecutive = 0
        self._recover_started: float | None = None
        self._last_try: float | None = None
        self.digit: Any = open_digit()
        self._warmup()

    def _warmup(self) -> None:
        for _ in range(self.warmup_frames):
            self.digit.get_frame()

    def _try_reopen(self) -> bool:
        """One open attempt while the stream is closed; True when it is open again."""
        now = self.clock()
        self._last_try = now
        try:
            self.digit = self.open_digit()
        except Exception as exc:
            if self._recover_started is None:
                self._recover_started = now
            if now - self._recover_started > self.lost_s:
                raise ConnectionError(
                    f"{self.name}: cannot reopen the DIGIT stream for {self.lost_s:.0f} s: {exc}"
                ) from exc
            return False
        self._recover_started = None
        self._warmup()
        return True

    def read(self) -> Sample | None:
        if self.digit is None:  # a failed reopen: retry slowly until it works
            now = self.clock()
            if self._last_try is not None and now - self._last_try < REOPEN_EVERY_S:
                return None
            if not self._try_reopen():
                return None
        frame = self.digit.get_frame()  # OpenCV BGR
        if self.seam_check:
            row = find_seam(frame)
            if row is not None:
                self.seams += 1
                self.seam_row = row
                self._consecutive += 1
                if self._consecutive >= self.recover_after:
                    self._consecutive = 0
                    self.recoveries += 1
                    self.log(
                        f"{self.name}: row seam at {row}, reopening the DIGIT stream "
                        f"(recovery {self.recoveries})"
                    )
                    with contextlib.suppress(Exception):
                        self.digit.disconnect()
                    self.digit = None
                    self._recover_started = self.clock()
                    self._try_reopen()
                return None
        self._consecutive = 0
        return Sample(np.ascontiguousarray(frame[..., ::-1]), time.monotonic_ns())

    def status(self) -> dict:
        if not self.seam_check:
            return {}
        return {
            "seams": self.seams,
            "recoveries": self.recoveries,
            "seam_row": self.seam_row,
        }

    def close(self) -> None:
        if self.digit is not None:
            self.digit.disconnect()


class DigitSensor(TactileImageSensor):
    keys = (
        *TactileImageSensor.keys,
        "resolution",
        "serial",
        "name",
        "seam_check",
        "recover_after",
        "warmup_frames",
    )

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
        seam_check = cfg.get("seam_check", True)
        if not isinstance(seam_check, bool):
            raise TypeError(f"{name}.seam_check must be a bool")
        self.seam_check = seam_check
        recover_after = cfg.get("recover_after", 3)
        if type(recover_after) is not int or recover_after < 1:
            raise ValueError(f"{name}.recover_after must be an integer >= 1")
        self.recover_after = recover_after
        warmup_frames = cfg.get("warmup_frames", 10)
        if type(warmup_frames) is not int or warmup_frames < 0:
            raise ValueError(f"{name}.warmup_frames must be an integer >= 0")
        self.warmup_frames = warmup_frames

    def device_ids(self) -> tuple[str, ...]:
        return (self.serial,)

    def open_device(self) -> Reader:
        Digit = import_module("digit_interface").Digit

        stream = Digit.STREAMS[self.resolution]
        if self.fps not in stream["fps"].values():
            raise ValueError(
                f"{self.name}: {self.resolution} supports fps {sorted(stream['fps'].values())}"
            )
        device_name = self.cfg.get("name", self.serial)

        def open_digit() -> Any:
            digit = Digit(serial=self.serial, name=device_name)
            digit.connect()
            try:
                digit.set_resolution(stream)
                digit.set_fps(int(self.fps))
            except Exception:
                digit.disconnect()
                raise
            return digit

        return DigitReader(
            open_digit,
            self.name,
            seam_check=self.seam_check,
            recover_after=self.recover_after,
            warmup_frames=self.warmup_frames,
        )
