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

Renderer = Callable[[dict], tuple[str, str]]  # fields -> (state, detail)
RENDERERS: dict[str, Renderer] = {}


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


GC_SHOWN_MS = 5.0  # shorter collections are routine


@register("robot")
def robot(f: dict) -> tuple[str, str]:
    parts = []
    if f.get("reason"):
        parts.append(f"reason: {f['reason']}")
    parts.append("armed" if f.get("armed") else "not armed")
    if f.get("tick_ms") is not None:
        parts.append(f"tick {f['tick_ms']} ms (max {f.get('tick_max_ms')})")
    if f.get("work_ms") is not None:
        parts.append(f"work {f['work_ms']} ms (max {f.get('work_max_ms')})")
    if f.get("clamped_2s"):
        parts.append(f"clamped {f['clamped_2s']}/2s")
    if f.get("rejected_2s"):
        parts.append(f"REJECTED {f['rejected_2s']}/2s: {f.get('last_reject')}")
    if (f.get("gc_max_ms") or 0) >= GC_SHOWN_MS:
        parts.append(f"gc pause {f['gc_max_ms']} ms")
    if f.get("error"):
        parts.append(f"last error: {f['error']}")
    return str(f.get("mode", "")), "  ".join(parts)


@register("controller")
def controller(f: dict) -> tuple[str, str]:
    state = str(f.get("state", ""))
    if state == "aligning":
        detail = f"move the leader: {f.get('worst_joint')} differs by {f.get('worst_diff')} (tolerance {f.get('tolerance')})"
    elif state == "input_stale":
        detail = "no recent leader input"
    elif state == "robot_fault":
        detail = "robot latched FAULT/ESTOP; re-align after recovery"
    else:
        detail = key_values(f, ("state", "tolerance", "worst_joint", "worst_diff"))
    return state, detail


def _source(f: dict, work: bool = False) -> tuple[str, str]:
    age = f.get("age_ms")
    state = "no samples" if age is None else "stale" if age >= 500 else "streaming"
    detail = f"{f.get('rate_hz', 0)} Hz  age {age} ms"
    if work and f.get("work_ms") is not None:
        detail += f"  work {f['work_ms']} ms (max {f.get('work_max_ms')})"
    if f.get("misses"):
        detail += f"  misses {f['misses']}"
    if (f.get("gc_max_ms") or 0) >= GC_SHOWN_MS:
        detail += f"  gc pause {f['gc_max_ms']} ms"
    if f.get("current_mA"):  # actuated leader: sent/measured mA of the pushed joints
        detail += "\nmA sent/measured: " + "  ".join(
            f"{j} {c[0]}/{c[1]}" for j, c in f["current_mA"].items()
        )
    return state, detail


RENDERERS["sensor"] = _source  # a camera's read waits for its next frame: no work time
RENDERERS["input"] = partial(_source, work=True)


@register("recorder")
def recorder(f: dict) -> tuple[str, str]:
    parts = [f"episodes {f.get('episodes')}"]
    if f.get("task"):
        parts.append(f"task '{f['task']}'")
    if f.get("state") == "recording":
        parts.append(f"{f.get('rows')} rows  {f.get('elapsed_s')} s")
    if f.get("missing"):
        parts.append(
            "missing " + ", ".join(f"{k}:{v}" for k, v in f["missing"].items())
        )
    return str(f.get("state", "")), "  ".join(parts)


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
    keys: str = "start <task> | stop | save | discard | estop | release | quit",
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
    help_line = Text(keys, style="dim")
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
        return Text(f"{command} done", style="dim")
    if "robot_mode" in report:
        style = "bold red" if report["robot_mode"] in ("FAULT", "ESTOP") else "cyan"
        reason = f" ({report['reason']})" if report.get("reason") else ""
        return Text(f"robot -> {report['robot_mode']}{reason}", style=style)
    return Text(str(report))
