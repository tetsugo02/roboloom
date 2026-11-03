"""Pika Sense as a pose input: the tracker's pose, the jaw angle and the clutch.

Two devices make one Sense: its Vive tracker (libsurvive, `drivers.survive`) gives the
pose, and its USB serial link (`drivers.pika_serial`, as the Pika Gripper) streams the
jaw encoder (`AS5047.rad`) and `Command`, which the vendor's teleoperation toggles with
a double-click. Each change of `Command` engages or disengages teleoperation; losing the
pose or the serial feedback disengages it, so the operator engages again on purpose.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Any

import numpy as np

from ...core.checks import identity, positive
from ...core.source import Reader, Sample
from ...drivers.pika_serial import PikaSerial
from ...kinematics.spec import Pose, pose_to, pose_xyz_rpy
from ..base import PoseInput
from .spec import JAW_RANGE, TRACKER_TO_SENSE


class SenseReader:
    """Samples of one Sense (`POSE_FIELDS`) from its tracker and serial link."""

    def __init__(
        self,
        link: Any,
        tracker: Any,
        stale_s: float,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.link, self.tracker, self.stale_s, self.clock = (
            link,
            tracker,
            stale_s,
            clock,
        )
        self.engaged = False
        self.command: Any = None  # the last `Command` value seen
        self.last_pose: Pose = np.eye(4)

    def _fresh(self, got: tuple[Any, float] | None, now: float) -> Any:
        if got is None or now - got[1] > self.stale_s:
            return None
        return got[0]

    def read(self) -> Sample:
        now = self.clock()
        pose = self._fresh(self.tracker.latest(), now)
        jaw = self._fresh(self.link.latest("AS5047"), now)
        command = self._fresh(self.link.latest("Command"), now)
        tracking = pose is not None
        if tracking:
            self.last_pose = pose @ TRACKER_TO_SENSE
        if command is None or not tracking:
            self.engaged = False  # nothing to follow, or no way to disengage
        elif self.command is not None and command != self.command:
            self.engaged = not self.engaged
        if command is not None:
            self.command = command
        gripper = (
            float(jaw["rad"]) if isinstance(jaw, dict) and "rad" in jaw else math.nan
        )
        position, quaternion = pose_to(self.last_pose)
        value = [
            *position,
            *quaternion,
            gripper,
            1.0 if tracking else 0.0,
            1.0 if self.engaged else 0.0,
        ]
        return Sample(np.asarray(value, dtype=float), time.monotonic_ns())

    def status(self) -> dict:
        return {"engaged": self.engaged}

    def close(self) -> None:
        try:
            self.tracker.close()
        finally:
            self.link.close()


class MockSense:
    """A Sense moved by an imaginary hand: a slow circle and a twist of the wrist, the jaws
    opening and closing. It engages 2 s after opening and then every 12 s (10 s engaged,
    2 s not), so a controller that stopped (e.g. for a move home) is engaged again."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock, self.t0 = clock, clock()

    def read(self) -> Sample:
        t = self.clock() - self.t0
        w = 2 * math.pi / 8.0
        pose = pose_xyz_rpy(
            (
                0.05 * math.sin(w * t),
                0.05 * (1 - math.cos(w * t)),
                0.03 * math.sin(2 * w * t),
            ),
            (0.3 * math.sin(w * t), 0.0, 0.0),  # a twist of the wrist (forward axis)
        )
        position, quaternion = pose_to(pose)
        low, high = JAW_RANGE
        jaw = low + (high - low) * (0.5 + 0.4 * math.sin(w * t))
        engaged = 1.0 if (t - 2.0) % 12.0 < 10.0 and t >= 2.0 else 0.0
        value = [*position, *quaternion, jaw, 1.0, engaged]
        return Sample(np.asarray(value, dtype=float), time.monotonic_ns())

    def close(self) -> None:
        pass


class PikaSense(PoseInput):
    """Keys: `port` (the Sense's serial port, a /dev/serial/by-path/... path), `tracker`
    (`{name: WM0}`: the libsurvive object of its tracker; `args`: extra libsurvive
    arguments), `stale_ms` (optional, default 100: older pose or serial feedback counts
    as lost), `poll_hz` (optional)."""

    world_frame = "libsurvive"

    def __init__(self, name: str, cfg: dict):
        super().__init__(name, cfg)
        self.rate_hz(0)
        self.port = identity(cfg.get("port"), f"{name}.port")
        tracker = cfg.get("tracker")
        if not isinstance(tracker, dict):
            raise TypeError(f"{name}.tracker: expected {{name: <libsurvive object>}}")
        self.tracker = identity(tracker.get("name"), f"{name}.tracker.name")
        args = tracker.get("args", [])
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise ValueError(f"{name}.tracker.args: expected a list of strings")
        self.tracker_args = list(args)
        self.stale_ms = positive(cfg.get("stale_ms", 100), f"{name}.stale_ms")

    def device_ids(self) -> tuple[str, ...]:
        return (self.port, f"libsurvive:{self.tracker}")

    def open(self, mock: bool, dataset_fps: float) -> Reader:
        if mock:
            return MockSense()
        from ...drivers.survive import SurviveTracker

        link = PikaSerial(self.port)
        try:
            tracker = SurviveTracker(self.tracker, args=self.tracker_args)
        except BaseException:
            link.close()
            raise
        return SenseReader(link, tracker, self.stale_ms / 1000)
