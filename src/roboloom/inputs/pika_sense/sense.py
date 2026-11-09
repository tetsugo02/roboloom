"""Pika Sense as a pose input: the tracker's pose, the jaw angle and the clutch.

Two devices make one Sense: its Vive tracker gives the pose, read by a tracking system
node (`trackers:`, e.g. libsurvive) that serves every Sense and sends this node its
tracker's pose by serial number; and its USB serial link (`drivers.pika_serial`, as the Pika Gripper) streams the
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
from ...core.protocol import Envelope
from ...core.source import Reader, Sample
from ...drivers.pika_serial import PikaSerial
from ...kinematics.spec import Pose, pose_from, pose_to, pose_xyz_rpy
from ...trackers.base import Tracker
from ..base import PoseInput
from .spec import JAW_RANGE, TRACKER_TO_SENSE


class TrackerFeed:
    """The latest pose of one tracker (by serial) from the tracking system's node."""

    def __init__(self, serial: str):
        self.serial = serial
        self.pose: tuple[Pose, float] | None = None
        self.lost = False  # the system reported this tracker lost

    def on_tracker(self, msg: Envelope) -> None:
        got = Tracker.decode(msg.payload).get(self.serial)
        if got is None:
            return
        self.lost = not got.tracking
        if got.tracking:
            self.pose = (pose_from(got.position, got.quaternion), got.t_ns / 1e9)

    def latest(self) -> tuple[Pose, float] | None:
        """The tracker's last tracked pose (world frame) and when the tracking system
        received it (monotonic s), or None while it is lost or never seen."""
        return None if self.lost or self.pose is None else self.pose

    def close(self) -> None:
        pass


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

    def on_tracker(self, msg: Envelope) -> None:
        """The tracking system's poses (`runtime.node` passes its `tracker` input)."""
        self.tracker.on_tracker(msg)

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
    (`{system: <a node under trackers:>, serial: LHR-...}`: the tracking system that reads
    its Vive tracker, and the tracker's serial number), `stale_ms` (optional, default
    100: older pose or serial feedback counts as lost), `poll_hz` (optional)."""

    def __init__(self, name: str, cfg: dict):
        super().__init__(name, cfg)
        self.rate_hz(0)
        self.port = identity(cfg.get("port"), f"{name}.port")
        tracker = cfg.get("tracker")
        if not isinstance(tracker, dict):
            raise TypeError(
                f"{name}.tracker: expected {{system: <tracker node>, serial: LHR-...}}"
            )
        moved = sorted({"name", "args"} & set(tracker))
        if moved:
            raise ValueError(
                f"{name}.tracker: {', '.join(moved)} no longer apply: name the tracker by "
                "`serial` and its tracking system by `system`, a node under `trackers:` "
                "(libsurvive's `args` go there); see the Pika Sense page of the docs"
            )
        self.system = identity(tracker.get("system"), f"{name}.tracker.system")
        self.serial = identity(tracker.get("serial"), f"{name}.tracker.serial")
        self.world_frame = self.system
        self.stale_ms = positive(cfg.get("stale_ms", 100), f"{name}.stale_ms")

    def tracker_system(self) -> str:
        return self.system

    def device_ids(self) -> tuple[str, ...]:
        return (self.port, f"tracker:{self.system}:{self.serial}")

    def open(self, mock: bool, dataset_fps: float) -> Reader:
        if mock:
            return MockSense()
        return SenseReader(
            PikaSerial(self.port), TrackerFeed(self.serial), self.stale_ms / 1000
        )
