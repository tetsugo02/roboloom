"""Screen for `roboloom tune-gravity`: explanation, live joint table, guide for the selected joint."""

from __future__ import annotations

import queue
import time

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..control.tuning import TuningSession
from .live import KeyReader

EXPLAIN = """\
sent current = clip( ramp x ( gain x g(q) + hold ) + range barrier )   [mA]
  g(q)  current the identified model says holds this pose; motor torque ~ current
  gain  share of the weight removed is about gain x g(q) / the current really needed:
        too low -> a released joint sinks, right -> it floats, too high -> it rises
  hold  breakaway hold: the joint stays where it is left and moves once pushed harder
        than hold mA (like friction). Covers pose-dependent model error; costs that
        much extra force to start a motion. 0 = off
feel                                   cause                     key
released joint sinks slowly            too little compensation   ]  gain +0.1
released joint rises slowly            too much                  [  gain -0.1
hard to start moving, sticky           hold too strong           -  hold -5 mA
sinks in some poses, rises in others   model error by pose       =  hold +5 mA"""

KEYS = "up/down (j/k) joint   ] [ gain   = - hold   0 compare without gravity   r resume   s save   q quit"
STATE_STYLE = {
    "off": "yellow",
    "free": "dim",
    "holding": "green",
    "sliding": "cyan",
    "gravity": "green",
}


def _num(value: float | None, fmt: str = "{:.0f}") -> str:
    return "-" if value is None else fmt.format(value)


def view(session: TuningSession, title: str, messages: list[str]) -> Group:
    table = Table(expand=True, show_edge=False)
    for col in (
        "",
        "ID",
        "joint",
        "gain",
        "hold mA",
        "g(q) mA",
        "sent mA",
        "meas mA",
        "q",
        "v",
        "state",
    ):
        table.add_column(col, no_wrap=True)
    rows = session.rows()
    for k, r in enumerate(rows):
        table.add_row(
            ">" if k == session.selected else "",
            _num(r.motor_id, "{}"),
            r.joint,
            f"{r.gain:.1f}",
            f"{r.hold_mA:.0f}",
            _num(r.model_mA),
            _num(r.sent_mA),
            _num(r.measured_mA),
            _num(r.position),
            _num(r.velocity),
            Text(r.state, style=STATE_STYLE.get(r.state, "")),
            style="bold" if k == session.selected else "",
        )
    r = rows[session.selected]
    guide = Text(
        f"step {session.selected + 1}/{len(rows)}  {r.joint}"
        + (f" (ID {r.motor_id})" if r.motor_id is not None else "")
        + f": {r.hint or 'a pose where this joint carries weight'}.\n"
        "Hold the arm there, let go and watch this joint: sinks -> ]   rises -> [   "
        "sticky -> -   pose-dependent -> =\n"
        "0 toggles its gravity term to feel the difference. Little load (gain 0)? leave it, go down.",
    )
    status = (
        Text(
            f"STOPPED: {session.stopped} - support the arm, press r to resume",
            style="bold red",
        )
        if session.stopped
        else Text(
            "running" + ("  (unsaved changes)" if session.dirty else ""), style="green"
        )
    )
    return Group(
        Text(title, style="bold"),
        Panel(Text(EXPLAIN), title="what the numbers mean", border_style="dim"),
        table,
        Panel(guide, title="guide", border_style="cyan"),
        status,
        Text("\n".join(messages[-3:]), style="dim"),
        Text(KEYS, style="dim"),
    )


def _keys(raw: queue.Queue[str]):
    """Characters to key names; arrow keys arrive as ESC [ A/B."""
    buffer = ""
    while True:
        try:
            ch = raw.get_nowait()
        except queue.Empty:
            return
        buffer += ch
        if buffer.startswith("\x1b"):
            if len(buffer) < 3:
                continue
            yield {"\x1b[A": "up", "\x1b[B": "down"}.get(buffer[:3], "")
            buffer = ""
            continue
        yield buffer
        buffer = ""


def run(session: TuningSession, period_s: float, title: str) -> str:
    messages: list[str] = []
    session.start()
    try:
        return _loop(session, period_s, title, messages)
    except KeyboardInterrupt:
        return "interrupted" + (" without saving" if session.dirty else "")


def _loop(
    session: TuningSession, period_s: float, title: str, messages: list[str]
) -> str:
    confirm_quit = False
    next_draw = 0.0
    with (
        KeyReader() as keys,
        Live(
            view(session, title, messages), console=Console(), auto_refresh=False
        ) as live,
    ):
        while True:
            tick = time.monotonic()
            session.step()
            for key in _keys(keys.keys):
                if key in ("q", "\x03", "\x04"):
                    if session.dirty and not confirm_quit:
                        messages.append(
                            "unsaved changes: s to save, q again to quit without saving"
                        )
                        confirm_quit = True
                        continue
                    return "quit without saving" if session.dirty else "done"
                confirm_quit = False
                message = session.key(key)
                if message:
                    messages.append(message)
            if tick >= next_draw:
                live.update(view(session, title, messages), refresh=True)
                next_draw = tick + 0.1
            time.sleep(max(0.0, period_s - (time.monotonic() - tick)))
