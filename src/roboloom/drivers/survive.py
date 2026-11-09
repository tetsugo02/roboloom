"""Every Vive tracker libsurvive sees, from one context (pysurvive, its Python binding).

pysurvive is installed by roboloom's `pika` extra as a wheel built by a fork of
libsurvive (github.com/tetsugo02/libsurvive, branch `roboloom`; PyPI has no Python 3.12
distribution): CPython 3.12, Linux x86_64, libusb bundled, nothing built at install time.
The tracker's udev rules need an administrator. Base stations must be set up and
calibrated (libsurvive's `--force-calibrate`); poses are in that calibrated world frame,
and the rotation comes as w, x, y, z (as in the vendor's pika_sdk,
`pika/tracker/vive_tracker.py`).

One context per host: libsurvive claims the USB receivers, so a second context in
another process finds no tracker. `SurviveSystem` therefore runs in one node and serves
every input (`roboloom.trackers`). Its single thread calls libsurvive (the simple API is
not thread-safe) and keys poses by serial number, because names (`WM0`) follow the
enumeration order, and an object that comes back after a USB reconnect is a new one.

libsurvive reports a lost object with an all-zero rotation; that marks the serial lost
(`tracking` False) instead of stopping the thread, and the next good pose recovers it.
Each pose is stamped when it arrives (`time.monotonic_ns`), so readers in other
processes judge staleness on the same clock.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any

from ..trackers.base import TrackedPose, unit_quaternion

INSTALL_HINT = (
    "pysurvive (libsurvive's Python binding) is unavailable: install roboloom[pika] "
    "(a wheel for Linux x86_64 only); ask an administrator for the tracker's udev rules "
    "(81-vive.rules); see the Pika Sense page of the docs"
)


def _pysurvive() -> Any:
    try:
        import pysurvive  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ConnectionError(INSTALL_HINT) from exc
    return pysurvive


def open_context(args: Sequence[str]) -> Any:
    return _pysurvive().SimpleContext([sys.argv[0], *args])


def serial_number(obj: Any) -> str:
    """The object's serial (`LHR-...`); empty until libsurvive has read its config.
    pysurvive's `SimpleObject` does not wrap it, so call the C API on its pointer."""
    return _text(_pysurvive().simple_serial_number(obj.ptr) or b"")


class SurviveSystem:
    def __init__(
        self,
        args: Sequence[str] = (),
        *,
        context: Any | None = None,
        serial: Callable[[Any], str] = serial_number,
        clock: Callable[[], int] = time.monotonic_ns,
    ):
        self.serial, self.clock = serial, clock
        self.context = open_context(args) if context is None else context
        self.lock = threading.Lock()
        self.poses: dict[str, TrackedPose] = {}
        self.names: dict[str, str] = {}  # serial -> libsurvive's current name
        self.lost = 0  # all-zero or invalid rotations received
        self.unidentified = 0  # updates before the object's serial was known
        self.error: Exception | None = None  # what stopped the thread, if anything
        self.stopping = threading.Event()
        self.thread = threading.Thread(
            target=self._receive, name="survive", daemon=True
        )
        self.thread.start()

    def _receive(self) -> None:
        try:
            while not self.stopping.is_set() and self.context.Running():
                updated = self.context.NextUpdated()
                if not updated:
                    time.sleep(0.001)
                    continue
                serial = self.serial(updated)
                if not serial:
                    with self.lock:
                        self.unidentified += 1
                    continue
                self.take(serial, _text(updated.Name()), updated.Pose()[0])
        except Exception as exc:  # noqa: BLE001  readers see the poses go stale
            self.error = exc

    def take(self, serial: str, name: str, pose: Any) -> None:
        """One libsurvive pose (`Pos` x, y, z; `Rot` w, x, y, z) of object `serial`."""
        now = self.clock()
        w, x, y, z = (float(v) for v in pose.Rot)
        rotation = unit_quaternion((x, y, z, w))
        position = tuple(float(v) for v in pose.Pos)
        with self.lock:
            self.names[serial] = name
            last = self.poses.get(serial)
            if rotation is None or len(position) != 3:
                self.lost += 1
                if last is not None:  # keep the last tracked pose, marked lost
                    self.poses[serial] = TrackedPose(
                        last.position, last.quaternion, now, False
                    )
                return
            self.poses[serial] = TrackedPose(position, rotation, now, True)  # type: ignore[arg-type]

    def read(self) -> dict[str, TrackedPose]:
        with self.lock:
            return dict(self.poses)

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {
                "objects": len(self.poses),
                "serials": ", ".join(
                    f"{s} ({self.names[s]})" for s in sorted(self.poses)
                ),
                "lost": self.lost,
                "unidentified": self.unidentified,
                "error": None if self.error is None else str(self.error),
            }

    def close(self) -> None:
        self.stopping.set()
        if self.thread is not threading.current_thread():
            self.thread.join(timeout=1.0)


def _text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)
