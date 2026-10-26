"""`roboloom record` and `roboloom infer`: fixed-length episodes through a `Session`.

On a terminal the Session's screen (`ui.screen`) shows the nodes; this module adds the
keys: Enter starts each episode once the controller is ready, `q` (or Ctrl-C) discards
the episode in progress and stops, `e` latches the follower in ESTOP. Without a terminal
the episodes start as soon as the controller is ready.
"""

from __future__ import annotations

import queue
import sys
import time
from collections.abc import Callable

from rich.text import Text

from ..errors import Cancelled
from ..runtime.node import start_warning
from ..runtime.session import EpisodeResult, Session, Task
from .live import KeyReader

KEYS = "Enter: start | q: discard and quit | e: emergency stop"


def describe(result: EpisodeResult) -> str:
    if not result.saved:
        return f"discarded '{result.task}' ({result.frames} rows)"
    return f"saved episode {result.index}: '{result.task}', {result.frames} frames"


def record(
    session: Session,
    task: Task,
    seconds: float,
    episodes: int = 1,
    keep: Callable[[EpisodeResult], bool] | None = None,
) -> list[EpisodeResult]:
    """Run `episodes` episodes of `seconds`; `keep` as in `Session.record`."""
    if session.screen is None or not sys.stdin.isatty():
        return _plain(session, task, seconds, episodes, keep)
    return _keys(session, task, seconds, episodes, keep)


def _plain(
    session: Session,
    task: Task,
    seconds: float,
    episodes: int,
    keep: Callable[[EpisodeResult], bool] | None,
) -> list[EpisodeResult]:
    print("waiting until the controller is ready ...", flush=True)
    session.wait_ready(timeout=120)
    results = []
    for k in range(episodes):
        print(f"episode {k + 1}/{episodes}: recording {seconds:g} s", flush=True)
        results.append(session.record(task, seconds, keep=keep))
        print(describe(results[-1]), flush=True)
        for warning in results[-1].warnings:
            print(f"  quality: {warning}", flush=True)
    return results


def _keys(
    session: Session,
    task: Task,
    seconds: float,
    episodes: int,
    keep: Callable[[EpisodeResult], bool] | None,
) -> list[EpisodeResult]:
    screen = session.screen
    assert screen is not None
    screen.keys = KEYS
    results: list[EpisodeResult] = []

    def prompt(text: str, style: str = "bold") -> None:
        screen.prompt = Text(text, style=style)

    with KeyReader() as keys:

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
                if warning:
                    prompt(f"not ready: {warning}", "yellow")
                else:
                    prompt(
                        f"episode {k + 1}/{episodes}: press Enter to record {seconds:g} s"
                    )
                if key() in ("\r", "\n") and warning is None:
                    break
                time.sleep(0.1)
            end = time.monotonic() + seconds
            label = f"episode {k + 1}/{episodes}: recording"

            def tick(_status: dict, end: float = end, label: str = label) -> None:
                key()
                prompt(f"{label}, {max(0.0, end - time.monotonic()):.0f} s left")

            prompt(f"{label}, {seconds:.0f} s left")
            results.append(session.record(task, seconds, keep=keep, on_tick=tick))
            session.note(describe(results[-1]), "info" if results[-1].saved else "warn")
        prompt("done")
    return results
