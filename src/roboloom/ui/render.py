"""Render node statuses (see `roboloom.core.status`) as rich renderables. No terminal I/O here.

Each status has a role; `RENDERERS[role]` turns its fields into (state, detail).
Unregistered roles fall back to key=value, so a new robot or sensor shows up by
publishing fields, and gets a tailored row by registering one function.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from functools import partial
from pathlib import Path

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

STALE_S = 2.0
LEVEL_STYLE = {"ok": "green", "warn": "yellow", "error": "bold red"}
ROLE_ORDER = ("robot", "controller", "input", "sensor", "recorder")

Renderer = Callable[[dict], tuple[str, "str | Text"]]  # fields -> (state, detail)
RENDERERS: dict[str, Renderer] = {}

# What the operator must notice stands out in the detail column.
HOME = "bold magenta"  # the saved pose `home` moves to
GOOD, WATCH, BAD = "green", "yellow", "bold red"


def register(role: str) -> Callable[[Renderer], Renderer]:
    def add(fn: Renderer) -> Renderer:
        RENDERERS[role] = fn
        return fn

    return add


def key_values(fields: dict, skip: Iterable[str] = ()) -> str:
    return "  ".join(
        f"{k}={v}"
        for k, v in fields.items()
        if k not in skip and v not in (None, "", {}, [])
    )


def generic(fields: dict) -> tuple[str, str]:
    state = fields.get("state", fields.get("mode", ""))
    return str(state), key_values(fields, ("state", "mode"))


def joined(parts: Iterable[Text | str | None], sep: str = "  ") -> Text:
    """Detail parts (plain or styled) separated by two spaces; None parts are left out."""
    out = Text()
    for part in (p for p in parts if p):
        if out:
            out.append(sep)
        out.append_text(part if isinstance(part, Text) else Text(part))
    return out


GC_SHOWN_MS = 5.0  # shorter collections are routine
BUSY = 0.7  # work beyond this share of the tick leaves too little room


def _work(f: dict) -> Text | None:
    if f.get("work_ms") is None:
        return None
    text = f"work {f['work_ms']} ms (max {f.get('work_max_ms')})"
    period = f.get("tick_ms") or (1000 / f["rate_hz"] if f.get("rate_hz") else None)
    busy = period and (f.get("work_max_ms") or 0) > BUSY * period
    return Text(text, style=WATCH if busy else "")


def _gc(f: dict) -> Text | None:
    pause = f.get("gc_max_ms") or 0
    return Text(f"gc pause {pause} ms", style=WATCH) if pause >= GC_SHOWN_MS else None


@register("robot")
def robot(f: dict) -> tuple[str, Text]:
    detail = joined(
        [
            Text(f"reason: {f['reason']}", style=BAD) if f.get("reason") else None,
            Text("armed", style=GOOD) if f.get("armed") else Text("not armed", "dim"),
            f"tick {f['tick_ms']} ms (max {f.get('tick_max_ms')})"
            if f.get("tick_ms") is not None
            else None,
            _work(f),
            Text(f"clamped {f['clamped_2s']}/2s", style=WATCH)
            if f.get("clamped_2s")
            else None,
            Text(f"REJECTED {f['rejected_2s']}/2s: {f.get('last_reject')}", style=BAD)
            if f.get("rejected_2s")
            else None,
            _gc(f),
            _home(f) if f.get("home") else None,
            Text(f"last error: {f['error']}", style=BAD) if f.get("error") else None,
        ]
    )
    return str(f.get("mode", "")), detail


def _home(f: dict) -> Text:
    """Progress of a move to the saved home pose (robot and actuated leader)."""
    text = Text("home ") + Text(f"{f['home']}", style=HOME) + Text(": ")
    state = f.get("home_state")
    if state == "moving":
        text.append(f"moving {round(100 * (f.get('home_progress') or 0))}%", WATCH)
    elif state == "short":  # friction stopped a spring short of the pose
        text.append("short", WATCH)
    else:
        text.append("reached", GOOD)
    if f.get("home_far"):
        off = ", ".join(f"{j} {d:+d}" for j, d in f["home_far"].items())
        text.append(f" (off by: {off})", WATCH)
    if f.get("home_skipped"):
        text.append(f" (not moved: {', '.join(f['home_skipped'])})", WATCH)
    return text


@register("controller")
def controller(f: dict) -> tuple[str, Text]:
    state = str(f.get("state", ""))
    if state == "aligning":
        detail = Text(
            f"move the leader: {f.get('worst_joint')} differs by "
            f"{f.get('worst_diff')} (tolerance {f.get('tolerance')})",
            style=WATCH,
        )
    elif state == "input_stale":
        detail = Text("no recent leader input", style=WATCH)
    elif state == "robot_fault":
        detail = Text("robot latched FAULT/ESTOP; re-align after recovery", style=BAD)
    else:
        detail = Text(
            key_values(f, ("state", "tolerance", "worst_joint", "worst_diff", "home"))
        )
    if f.get("home"):  # the saved pose `home` moves this pair to
        detail = joined([detail, Text("home pose: ") + Text(f"{f['home']}.yaml", HOME)])
    return state, detail


def _source(f: dict, work: bool = False) -> tuple[str, Text]:
    age = f.get("age_ms")
    state = "no samples" if age is None else "stale" if age >= 500 else "streaming"
    detail = joined(
        [
            f"{f.get('rate_hz', 0)} Hz",
            Text(f"age {age} ms", style=WATCH if age is None or age >= 500 else ""),
            _work(f) if work else None,
            _home(f) if f.get("home") else None,
            Text(f"home error: {f['home_error']}", style=BAD)
            if f.get("home_error")
            else None,
            Text(f"misses {f['misses']}", style=WATCH) if f.get("misses") else None,
            _gc(f),
        ]
    )
    if f.get("current_mA"):  # actuated leader: sent/measured mA of the pushed joints
        detail.append(
            "\nmA sent/measured: "
            + "  ".join(f"{j} {c[0]}/{c[1]}" for j, c in f["current_mA"].items()),
            style="dim",
        )
    return state, detail


RENDERERS["sensor"] = _source  # a camera's read waits for its next frame: no work time
RENDERERS["input"] = partial(_source, work=True)


@register("recorder")
def recorder(f: dict) -> tuple[str, Text]:
    detail = joined(
        [
            f"episodes {f.get('episodes')}",
            Text(f"task '{f['task']}'", style="bold cyan") if f.get("task") else None,
            f"{f.get('rows')} rows  {f.get('elapsed_s')} s"
            if f.get("state") == "recording"
            else None,
            Text(
                "missing " + ", ".join(f"{k}:{v}" for k, v in f["missing"].items()),
                style=WATCH,
            )
            if f.get("missing")
            else None,
        ]
    )
    return str(f.get("state", "")), detail


COMMANDS = (
    "start <task>",
    "stop",
    "save",
    "discard",
    "home",
    "estop",
    "release",
    "quit",
)


def home_available(status: dict | None) -> bool:
    """Whether a controller reports a saved home pose (else `home` is inactive)."""
    nodes = (status or {}).get("nodes", {})
    return any(
        item.get("role") == "controller" and item.get("fields", {}).get("home")
        for item in nodes.values()
    )


def command_line(home: bool, commands: Iterable[str] = COMMANDS) -> Text:
    """The help line; `home` is struck through when no home pose is configured."""
    out = Text(style="dim")
    for k, command in enumerate(commands):
        if k:
            out.append(" | ")
        if command.startswith(("home", "h:")) and not home:
            out.append(command, style="strike")
            out.append(" (no home pose)")
        else:
            out.append(command)
    return out


def node_table(status: dict | None, now_ns: int) -> Table:
    table = Table(expand=True, show_edge=False, pad_edge=False)
    table.add_column("node", style="bold", no_wrap=True)
    table.add_column("role", style="dim", no_wrap=True)
    table.add_column("state", no_wrap=True)
    table.add_column(
        "detail", overflow="fold", ratio=1
    )  # the other columns fit their content
    nodes = (status or {}).get("nodes", {})
    order = {r: i for i, r in enumerate(ROLE_ORDER)}
    for name, item in sorted(
        nodes.items(), key=lambda kv: (order.get(kv[1].get("role"), 99), kv[0])
    ):
        role = item.get("role", "?")
        age_s = (now_ns - item.get("t_ns", 0)) / 1e9
        if age_s > STALE_S:
            table.add_row(
                name,
                role,
                Text(f"no status {age_s:.0f} s", style="bold red"),
                "node stopped or blocked?",
            )
            continue
        state, detail = RENDERERS.get(role, generic)(item.get("fields", {}))
        table.add_row(
            name,
            role,
            Text(state, style=LEVEL_STYLE.get(item.get("level", "ok"), "")),
            detail,
        )
    if not nodes:
        table.add_row("-", "-", Text("waiting for nodes", style="yellow"), "")
    return table


def render(
    status: dict | None,
    messages: Iterable[Text | str],
    prompt: Text | str,
    now_ns: int | None = None,
    title: str = "roboloom",
    log_path: Path | None = None,
    keys: str | Text | None = None,
) -> RenderableType:
    now = time.monotonic_ns() if now_ns is None else now_ns
    header = Text(title, style="bold")
    if status:
        experiment = Path(status.get("experiment", ""))
        header.append(
            f"  {experiment.parent.name}/{experiment.name}  mode={status.get('mode')}",
            style="dim",
        )
    if log_path is not None:
        header.append(f"  log: {log_path}", style="dim")
    lines = list(messages)[-8:]
    log = (
        Group(*(m if isinstance(m, Text) else Text(m) for m in lines))
        if lines
        else Text("")
    )
    if keys is None:
        help_line = command_line(home_available(status))
    else:
        help_line = keys if isinstance(keys, Text) else Text(keys, style="dim")
    return Group(
        header,
        Panel(node_table(status, now), title="nodes", border_style="blue"),
        Panel(log, title="messages", border_style="dim", height=10),
        help_line,
        prompt if isinstance(prompt, Text) else Text(prompt),
    )


def describe_report(report: dict) -> Text:
    """One message line for a recorder report, session warning or Session note."""
    if "note" in report:
        style = {"warn": "yellow", "error": "bold red"}.get(report.get("level", ""), "")
        return Text(str(report["note"]), style=style)
    if "warning" in report:
        return Text(
            f"{report.get('command', '')} not started: {report['warning']}",
            style="bold yellow",
        )
    if "error" in report:
        return Text(
            f"{report.get('command', '')} failed: {report['error']}", style="bold red"
        )
    if "saved_frames" in report:
        m = report.get("metrics", {})
        missing = {
            k: round(v * 100, 1) for k, v in m.get("missing_rate", {}).items() if v
        }
        tick = m.get("control_interval_ms", {})
        text = f"saved {report['saved_frames']} frames (episodes {report.get('episodes')})  tick p99 {tick.get('p99', 0):.1f} ms max {tick.get('max', 0):.1f} ms"
        if missing:
            text += f"  missing % {missing}"
        return Text(text, style="green")
    if report.get("ok"):
        command = report.get("command", "")
        if command == "start":
            return Text(f"recording '{report.get('task', '')}'", style="cyan")
        if command == "stop":
            rows = report.get("metrics", {}).get("rows")
            return Text(f"stopped ({rows} rows); save or discard", style="cyan")
        if command == "home":
            return Text("home: moving to the saved pose", style="magenta")
        return Text(f"{command} done", style="dim")
    if "robot_mode" in report:
        style = "bold red" if report["robot_mode"] in ("FAULT", "ESTOP") else "cyan"
        reason = f" ({report['reason']})" if report.get("reason") else ""
        return Text(f"robot -> {report['robot_mode']}{reason}", style=style)
    return Text(str(report))
