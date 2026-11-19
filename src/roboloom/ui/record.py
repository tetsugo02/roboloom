"""`roboloom record` and `roboloom infer`: fixed-length episodes through a `Session`.

On a terminal the Session's screen (`ui.screen`) shows the nodes; this module adds the
keys: Enter starts each episode once the controller is ready, `h` moves to the saved home
pose before it (inactive without one), `q` (or Ctrl-C) discards the episode in progress
and stops, `e` latches the follower in ESTOP. With a policy that has `teleop:`, `t`
hands the followers to the leader (before an episode, or during one: an intervention) and
`p` hands them back to the policy during an episode. Without a terminal the episodes
start as soon as the controller is ready.
"""

from __future__ import annotations

import queue
import sys
import time
from collections.abc import Callable

from rich.text import Text

from ..errors import Cancelled
from ..runtime.node import start_warning
from ..runtime.session import (
    EpisodeResult,
    Session,
    SessionError,
    Task,
    steps_done,
)
from .live import KeyReader
from .render import command_line

KEYS = ("Enter: start", "h: home", "q: discard and quit", "e: emergency stop")
PLAIN_PROGRESS_S = 5.0  # without a screen: one progress line this often


def describe(result: EpisodeResult) -> str:
    if result.pending:
        return f"queued '{result.task}' for save ({result.frames} frames)"
    if not result.saved:
        return f"discarded '{result.task}' ({result.frames} rows)"
    verdict = f", labelled {result.label}" if result.label else ""
    return (
        f"saved episode {result.index}: '{result.task}', {result.frames} frames"
        f"{verdict}"
    )


def record(
    session: Session,
    task: Task,
    seconds: float,
    episodes: int = 1,
    keep: Callable[[EpisodeResult], bool] | None = None,
    home: bool = False,
    steps: int | None = None,
) -> list[EpisodeResult]:
    """Run `episodes` episodes of `seconds`; `keep`, `home` and `steps` as in
    `Session.record`."""
    if session.screen is None or not sys.stdin.isatty():
        return _plain(session, task, seconds, episodes, keep, home, steps)
    return _keys(session, task, seconds, episodes, keep, home, steps)


BAR = 20  # characters of the progress bar


def progress(
    index: int,
    planned: int,
    elapsed: float,
    seconds: float,
    step: int | None = None,
    steps: int | None = None,
) -> str:
    """One line on how far episode `index` (from 0) of `planned` is: by the policy's
    actions when the episode has `steps`, else by time.

        episode 2/10  step 137/500  [█████░░░░░░░░░░░░░░░] 27%  72.6 s left
    """
    number = (
        f"episode {index + 1}/{planned}"
        if index < planned
        else f"episode {index + 1} ({planned} planned)"
    )
    if steps:
        done = min(1.0, (step or 0) / steps)
        count = f"  step {min(step or 0, steps)}/{steps}"
    else:
        done = min(1.0, elapsed / seconds) if seconds > 0 else 1.0
        count = ""
    filled = int(done * BAR)
    bar = "█" * filled + "░" * (BAR - filled)
    left = max(0.0, seconds - elapsed)
    limit = "at most " if steps else ""
    return f"{number}{count}  [{bar}] {done:.0%}  {limit}{left:.1f} s left"


class _Progress:
    """Prints the progress line of an episode every PLAIN_PROGRESS_S (`on_tick`)."""

    def __init__(self, index: int, planned: int, seconds: float, steps: int | None):
        self.index, self.planned, self.seconds, self.steps = (
            index,
            planned,
            seconds,
            steps,
        )
        self.began: float | None = None  # the first tick: the episode has started
        self.shown = 0.0
        self.step = 0

    def __call__(self, status: dict) -> None:
        self.step = steps_done(status)
        now = time.monotonic()
        if self.began is None:  # not while moving home or waiting to be ready
            self.began = self.shown = now
        if now - self.shown >= PLAIN_PROGRESS_S:
            self.shown = now
            elapsed = now - self.began
            print(
                progress(
                    self.index,
                    self.planned,
                    elapsed,
                    self.seconds,
                    self.step,
                    self.steps,
                ),
                flush=True,
            )


def _collect_saves(
    session: Session, results: list[EpisodeResult], show: Callable[[str], None]
) -> list[EpisodeResult]:
    try:
        saved = session.wait_saves()
    except SessionError as exc:
        for result in exc.report.get("results", []):
            show(describe(result))
        raise
    for result in saved:
        show(describe(result))
    pending = sum(result.pending for result in results)
    completed = iter(saved[len(saved) - pending :])
    return [next(completed) if result.pending else result for result in results]


def _plain(
    session: Session,
    task: Task,
    seconds: float,
    episodes: int,
    keep: Callable[[EpisodeResult], bool] | None,
    home: bool,
    steps: int | None = None,
) -> list[EpisodeResult]:
    print("waiting until the controller is ready ...", flush=True)
    session.wait_ready(timeout=120)
    results = []
    for k in range(episodes):
        if home:
            print("moving home ...", flush=True)
        length = (
            f"{steps} steps (at most {seconds:.0f} s)" if steps else f"{seconds:g} s"
        )
        print(f"episode {k + 1}/{episodes}: recording {length}", flush=True)
        watch = _Progress(k, episodes, seconds, steps)
        results.append(
            session.record(
                task, seconds, keep=keep, home=home, steps=steps, on_tick=watch
            )
        )
        if steps and watch.step < steps:
            print(f"ended by time at {watch.step}/{steps} steps", flush=True)
        print(describe(results[-1]), flush=True)
        for warning in results[-1].warnings:
            print(f"  quality: {warning}", flush=True)
    return _collect_saves(session, results, lambda text: print(text, flush=True))


def _keys(
    session: Session,
    task: Task,
    seconds: float,
    episodes: int,
    keep: Callable[[EpisodeResult], bool] | None,
    home: bool,
    steps: int | None = None,
) -> list[EpisodeResult]:
    screen = session.screen
    assert screen is not None
    has_home = any(c.homes for c in session.cfg.controllers.values())
    teleop = any(getattr(c, "teleop", None) for c in session.cfg.controllers.values())
    screen.keys = command_line(
        has_home, (*KEYS, *(("t: teleop", "p: policy") if teleop else ()))
    )
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
            if teleop and ch in ("t", "p"):
                try:
                    session.teleop() if ch == "t" else session.policy()
                    session.note(
                        "teleop: the leader drives"
                        if ch == "t"
                        else "the policy drives"
                    )
                except SessionError as exc:  # refused: say why, go on
                    session.note(str(exc), "warn")
                return None
            return ch

        def go_home() -> None:
            """Move home; keys stay live (q, e) while the arms move."""
            sent_ns, limit = session.begin_home()
            deadline = time.monotonic() + limit
            while waiting := session.home_waiting(sent_ns):
                key()
                if time.monotonic() > deadline:
                    raise Cancelled(f"home not reached: {', '.join(waiting)}")
                prompt(f"moving home: {', '.join(waiting)}", "yellow")
                time.sleep(0.1)

        for k in range(episodes):
            if home:
                go_home()
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
                pressed = key()
                if pressed == "h" and has_home:
                    go_home()
                    continue
                if pressed in ("\r", "\n") and warning is None:
                    break
                time.sleep(0.1)
            began = time.monotonic()

            def tick(status: dict, k: int = k, began: float = began) -> None:
                key()
                elapsed = time.monotonic() - began
                done = steps_done(status)
                prompt(progress(k, episodes, elapsed, seconds, done, steps))

            prompt(progress(k, episodes, 0.0, seconds, 0, steps))
            results.append(
                session.record(task, seconds, keep=keep, on_tick=tick, steps=steps)
            )
            result = results[-1]
            session.note(
                describe(result), "info" if result.saved or result.pending else "warn"
            )
        if session.pending_saves:
            prompt("saving queued episodes ...")
        results = _collect_saves(session, results, session.note)
        prompt("done")
    return results
