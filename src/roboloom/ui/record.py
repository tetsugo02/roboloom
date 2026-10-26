"""`roboloom record`: fixed-length episodes on the operator screen, through a `Session`.

Enter starts each episode once the controller is ready; `q` (or Ctrl-C) discards the
episode in progress and stops, `e` latches the follower in ESTOP. Without a terminal
the episodes start as soon as the controller is ready.
"""

from __future__ import annotations

import queue
import sys
import time
from collections import deque

from rich.console import Console, RenderableType
from rich.live import Live
from rich.text import Text

from ..errors import Cancelled
from ..runtime.node import start_warning
from ..runtime.session import EpisodeResult, Session, Task
from .live import KeyReader
from .render import describe_report, render

KEYS = "Enter: start | q: discard and quit | e: emergency stop"


def describe(result: EpisodeResult) -> Text:
    if not result.saved:
        return Text(f"discarded '{result.task}' ({result.frames} rows)", style="yellow")
    text = Text(
        f"saved episode {result.index}: '{result.task}', {result.frames} frames",
        style="green",
    )
    for warning in result.warnings:
        text.append(f"\n  quality: {warning}", style="yellow")
    return text


def record(
    session: Session, task: Task, seconds: float, episodes: int = 1
) -> list[EpisodeResult]:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return _plain(session, task, seconds, episodes)
    return _screen(session, task, seconds, episodes)


def _plain(
    session: Session, task: Task, seconds: float, episodes: int
) -> list[EpisodeResult]:
    print("waiting until the controller is ready ...", flush=True)
    session.wait_ready(timeout=120)
    results = []
    for k in range(episodes):
        print(f"episode {k + 1}/{episodes}: recording {seconds:g} s", flush=True)
        results.append(session.record(task, seconds))
        print(describe(results[-1]).plain, flush=True)
    return results


def _screen(
    session: Session, task: Task, seconds: float, episodes: int
) -> list[EpisodeResult]:
    messages: deque[Text] = deque(maxlen=8)
    results: list[EpisodeResult] = []
    title = f"roboloom record  {seconds:g} s x {episodes}"

    def view(prompt: str) -> RenderableType:
        messages.extend(describe_report(r) for r in session.reports())
        return render(
            session.client.status(),
            messages,
            Text(prompt, style="bold"),
            title=title,
            log_path=session.log_path,
            keys=KEYS,
        )

    with (
        KeyReader() as keys,
        Live(view(""), console=Console(), auto_refresh=False) as live,
    ):

        def key() -> str | None:
            try:
                ch = keys.keys.get_nowait()
            except queue.Empty:
                return None
            if ch in ("q", "\x03", "\x04"):
                raise Cancelled("stopped by the operator")
            if ch == "e":
                session.estop()
                raise Cancelled("emergency stop: the follower is latched in ESTOP")
            return ch

        for k in range(episodes):
            while True:  # ready and Enter
                warning = start_warning(
                    session.cfg, session.status(), time.monotonic_ns()
                )
                prompt = (
                    f"not ready: {warning}"
                    if warning
                    else f"episode {k + 1}/{episodes}: press Enter to record {seconds:g} s"
                )
                live.update(view(prompt), refresh=True)
                if key() in ("\r", "\n") and warning is None:
                    break
                time.sleep(0.1)
            end = time.monotonic() + seconds
            label = f"episode {k + 1}/{episodes}: recording"

            def tick(_status: dict, end: float = end, label: str = label) -> None:
                key()
                left = max(0.0, end - time.monotonic())
                live.update(view(f"{label}, {left:.0f} s left"), refresh=True)

            results.append(session.record(task, seconds, on_tick=tick))
            messages.append(describe(results[-1]))
            live.update(view("saved"), refresh=True)
    return results
