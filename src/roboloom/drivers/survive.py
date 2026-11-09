"""Poses of one Vive tracker from libsurvive's Python binding (pysurvive).

pysurvive is installed by roboloom's `pika` extra as a wheel built by a fork of
libsurvive (github.com/tetsugo02/libsurvive, branch `roboloom`; PyPI has no Python 3.12
distribution): CPython 3.12, Linux x86_64, libusb bundled, nothing built at install time.
The tracker's udev rules need an administrator. Base stations must be set up and
calibrated (libsurvive's `--force-calibrate`); poses are in that calibrated world frame. As in the vendor's pika_sdk (`pika/tracker/vive_tracker.py`), an object is
named by libsurvive (e.g. `WM0`), and its rotation comes as w, x, y, z.

The frames carry libsurvive's own time; `SurviveTracker` stamps each pose when it
arrives (`clock`, monotonic seconds) so readers judge staleness on one clock.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any

from ..kinematics.spec import Pose, pose_from

INSTALL_HINT = (
    "pysurvive (libsurvive's Python binding) is unavailable: install roboloom[pika] "
    "(a wheel for Linux x86_64 only); ask an administrator for the tracker's udev rules "
    "(81-vive.rules); see the Pika Sense page of the docs"
)


def open_context(args: Sequence[str]) -> Any:
    try:
        import pysurvive  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ConnectionError(INSTALL_HINT) from exc
    return pysurvive.SimpleContext([sys.argv[0], *args])


class SurviveTracker:
    def __init__(
        self,
        name: str,
        *,
        args: Sequence[str] = (),
        context: Any | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.name, self.clock = name, clock
        self.context = open_context(args) if context is None else context
        self.lock = threading.Lock()
        self.pose: tuple[Pose, float] | None = None
        self.seen: set[str] = set()  # every object libsurvive reported
        self.error: Exception | None = None
        self.stopping = threading.Event()
        self.thread = threading.Thread(
            target=self._receive, name=f"survive:{name}", daemon=True
        )
        self.thread.start()

    def _receive(self) -> None:
        try:
            while not self.stopping.is_set() and self.context.Running():
                updated = self.context.NextUpdated()
                if not updated:
                    time.sleep(0.001)
                    continue
                self.take(_text(updated.Name()), updated.Pose()[0])
        except Exception as exc:  # noqa: BLE001  readers see the pose go stale
            self.error = exc

    def take(self, name: str, pose: Any) -> None:
        """One libsurvive pose (`Pos` x, y, z; `Rot` w, x, y, z) of object `name`."""
        with self.lock:
            self.seen.add(name)
        if name != self.name:
            return
        w, x, y, z = (float(v) for v in pose.Rot)
        matrix = pose_from([float(v) for v in pose.Pos], [x, y, z, w])
        with self.lock:
            self.pose = (matrix, self.clock())

    def latest(self) -> tuple[Pose, float] | None:
        """The tracker's last pose (world frame) and when it arrived, if any."""
        with self.lock:
            return None if self.pose is None else (self.pose[0].copy(), self.pose[1])

    def objects(self) -> list[str]:
        with self.lock:
            return sorted(self.seen)

    def close(self) -> None:
        self.stopping.set()
        if self.thread is not threading.current_thread():
            self.thread.join(timeout=1.0)


def _text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)
