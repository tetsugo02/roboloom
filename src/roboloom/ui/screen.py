"""The node-status screen of a `Session`, drawn on a background thread.

A script that drives a Session (or `roboloom record`) sees the same table as `roboloom
run`, while its own code runs in the main thread: the screen keeps refreshing while the
script sleeps or waits. Anything the script prints scrolls above the screen (rich Live
redirects stdout and stderr). The screen reads no keys, so `input()` keeps working;
callers that want keys (the `record` command) read them themselves.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import TYPE_CHECKING

from rich.console import Console, RenderableType
from rich.live import Live
from rich.text import Text

from .live import tail_alerts
from .render import describe_report, render

if TYPE_CHECKING:
    from ..runtime.session import Session

REFRESH_S = 0.1


class SessionScreen:
    def __init__(self, session: Session, title: str):
        self.session, self.title = session, title
        self.messages: deque[Text] = deque(maxlen=8)
        self.prompt = Text("Ctrl-C: discard the episode and stop", style="dim")
        self.keys: str | Text = ""  # help line; empty for scripts (no keys are read)
        self._log_offset = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._live: Live | None = None
        session.listen(self._on_report)

    def _on_report(self, report: dict) -> None:
        self.messages.append(describe_report(report))

    def view(self) -> RenderableType:
        return render(
            self.session.client.status(),
            self.messages,
            self.prompt,
            title=self.title,
            log_path=self.session.log_path,
            keys=self.keys,
        )

    def start(self) -> None:
        self._live = Live(
            self.view(),
            console=Console(),
            auto_refresh=False,
            redirect_stdout=True,
            redirect_stderr=True,
        )
        self._live.start()
        self._thread = threading.Thread(target=self._run, daemon=True, name="screen")
        self._thread.start()

    def _run(self) -> None:
        assert self._live is not None
        while not self._stop.is_set():
            try:
                self.session.poll()
                alerts, self._log_offset = tail_alerts(
                    self.session.log_path, self._log_offset
                )
                self.messages.extend(alerts)
                self._live.update(self.view(), refresh=True)
            except Exception as exc:  # noqa: BLE001 - the screen must never stop the session
                self.messages.append(Text(f"screen: {exc}", style="red"))
            self._stop.wait(REFRESH_S)

    def stop(self) -> None:
        """Draw once more and give the terminal back (normal printing and input)."""
        if self._thread is None or self._live is None:
            return
        self._stop.set()
        self._thread.join(timeout=2)
        try:
            self.session.poll()
            self._live.update(self.view(), refresh=True)
        finally:
            self._live.stop()
            self._thread = None


def wanted(screen: bool | str) -> bool:
    """`"auto"` shows the screen only when stdout is a terminal (not Jupyter, pipes, tests)."""
    if screen == "auto":
        import sys

        return sys.stdout.isatty()
    return bool(screen)
