"""Serialize imports of accepted episodes into a single dataset writer."""

from __future__ import annotations

import contextlib
import queue
import threading
from collections.abc import Callable
from pathlib import Path

from . import spool
from .recorder import EpisodeRecorder


class BackgroundSaver:
    def __init__(
        self,
        writer: EpisodeRecorder,
        on_report: Callable[[dict], None],
        *,
        close_writer: bool = False,
    ):
        self._writer = writer
        self._on_report = on_report
        self._queue: queue.Queue[tuple[Path, int | None] | None] = queue.Queue()
        self._condition = threading.Condition()
        self._pending = 0
        self._episodes = writer.episodes
        self._stopped = False
        self._close_writer = close_writer
        self._close_error: Exception | None = None
        self._thread = threading.Thread(
            target=self._run, name="save-episodes", daemon=False
        )
        self._thread.start()

    @property
    def pending(self) -> int:
        return self.progress[0]

    @property
    def progress(self) -> tuple[int, int]:
        """Pending and committed episodes from the same completed save."""
        with self._condition:
            return self._pending, self._episodes

    def submit(self, path: Path, save_id: int | None) -> None:
        with self._condition:
            if self._stopped:
                raise RuntimeError("the saver has stopped")
            self._pending += 1
            self._queue.put((path, save_id))

    def drain(self, timeout: float | None = None) -> bool:
        with self._condition:
            return self._condition.wait_for(lambda: self._pending == 0, timeout)

    def stop(self) -> None:
        with self._condition:
            if not self._stopped:
                self._stopped = True
                self._queue.put(None)
        self._thread.join()
        if self._close_error is not None:
            raise self._close_error

    def _run(self) -> None:
        while (work := self._queue.get()) is not None:
            path, ident = work
            report = {"command": "saved", "save_id": ident}
            task = ""
            with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
                task = spool.metadata(path)["task"]
            try:
                report.update(self._writer.save_spooled(path))
            except Exception as exc:  # noqa: BLE001 - report the drop and continue saving
                report.update(task=task, error=str(exc), dropped=True)
            with self._condition:
                self._on_report(report)
                self._episodes = self._writer.episodes
                self._pending -= 1
                self._condition.notify_all()
        if self._close_writer:
            try:
                self._writer.close()
            except Exception as exc:  # noqa: BLE001 - re-raised by stop
                self._close_error = exc
