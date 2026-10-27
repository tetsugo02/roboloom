"""Shared operator application. Backends own operations; widgets only send requests."""

from __future__ import annotations

import asyncio
from collections import deque
from typing import ClassVar

from rich.table import Table
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Footer, OptionList, RichLog, Static, Tabs

from .command import CommandInput
from .models import Backend, Closed, LogEvent, Notice, Snapshot
from .presenters import present
from .render import BAD, LEVEL_STYLE, STALE_S, WATCH
from .splitter import Splitter


class Confirmation(ModalScreen[str | None]):
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", show=False)]
    DEFAULT_CSS = """
    Confirmation { align: center middle; background: $background 70%; }
    Confirmation > Vertical { width: 64; max-width: 95%; height: auto; max-height: 95%; border: thick $warning; padding: 1; }
    Confirmation Static { height: auto; margin-bottom: 1; }
    Confirmation OptionList { height: auto; max-height: 10; }
    """

    def __init__(self, prompt: str, choices: tuple[tuple[str, str], ...]):
        super().__init__()
        self.prompt, self.choices = prompt, (("cancel", "Cancel"), *choices)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.prompt, markup=False)
            yield OptionList(
                *(label for _, label in self.choices), id="choices", markup=False
            )

    def on_mount(self) -> None:
        self.query_one(OptionList).highlighted = 0
        self.query_one(OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        value = self.choices[event.option_index][0]
        self.dismiss(None if value == "cancel" else value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class BackendMessage(Message):
    def __init__(self, notice: Notice):
        super().__init__()
        self.notice = notice


class OperatorApp(App[str]):
    ENABLE_COMMAND_PALETTE = False
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+l", "command", "Command", priority=True),
        Binding("ctrl+n", "pane(1)", "Next pane", priority=True),
        Binding("ctrl+p", "pane(-1)", "Prev pane", priority=True),
        Binding("ctrl+g", "estop", "ESTOP", priority=True),
        Binding("f2", "command", show=False, priority=True),
        Binding("f6", "pane(1)", show=False, priority=True),
        Binding("shift+f6", "pane(-1)", show=False, priority=True),
        Binding("f12", "estop", show=False, priority=True),
        Binding("ctrl+c,ctrl+q", "request_quit", "Quit", priority=True),
        Binding("ctrl+o", "log_end", "Latest log", priority=True),
        Binding("ctrl+end", "log_end", show=False, priority=True),
    ]
    CSS = """
    Screen { layout: vertical; }
    #summary { height: 2; padding: 0 1; background: $boost; }
    #tabs { height: 3; }
    #panes { height: 1fr; layout: grid; grid-size: 3 3; grid-columns: 1fr 1 2fr; grid-rows: 1fr 1 1fr; }
    #nodes, #details, #menu, #logs { border: solid $primary; height: 1fr; }
    #menu, #logs, #row-splitter { column-span: 3; }
    #menu { min-height: 6; }
    #details { padding: 0 1; }
    #details.expanded { column-span: 3; }
    #detail { height: auto; }
    #command { height: 3; }
    #completion { height: auto; max-height: 2; padding: 0 1; }
    #panes.narrow { grid-size: 1 3; grid-columns: 1fr; grid-rows: 1fr 1 10; }
    #panes.narrow #nodes, #panes.narrow #details, #panes.narrow #logs { column-span: 1; row-span: 1; }
    #panes.narrow #menu, #panes.narrow #row-splitter { column-span: 1; }
    """

    def __init__(self, backend: Backend):
        super().__init__()
        self.backend = backend
        self.snapshot = Snapshot("roboloom", "", "launching")
        self._node_names: tuple[str, ...] = ()
        self._commands: tuple[str, ...] = ()
        self._selected = ""
        self._complete_prompted = False
        self._exit_requested = False
        self._log_end_requested = False
        self._nodes_ratio = 1 / 3
        self._operations_ratio: float | None = None
        self._pending_logs: deque[LogEvent] = deque(maxlen=10000)

    def compose(self) -> ComposeResult:
        yield Static("roboloom — launching", id="summary", markup=False)
        yield Tabs("Status", "Details", "Logs", id="tabs")
        with Container(id="panes"):
            yield OptionList(id="nodes", markup=False)
            yield Splitter("x", id="column-splitter")
            with VerticalScroll(id="details", can_focus=True):
                yield Static(id="detail", markup=False)
            yield RichLog(
                id="logs", wrap=True, min_width=1, max_lines=10000, auto_scroll=False
            )
            yield Splitter("y", id="row-splitter")
            yield OptionList(id="menu", markup=False)
        yield Static("", id="completion", markup=False)
        yield CommandInput()
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#nodes").border_title = "Nodes (display selection only)"
        self.query_one("#details").border_title = "Selected node"
        self.query_one("#menu").border_title = "Operations (entire experiment)"
        self.query_one("#logs").border_title = "Events / dora log · Ctrl-O: latest"
        self.query_one("#menu", OptionList).focus()
        self.query_one("#completion").display = False
        self._layout()

        def publish(notice: Notice) -> None:
            self.post_message(BackendMessage(notice))

        self.backend.start(publish)
        self.set_interval(0.1, self._flush_logs)

    async def on_unmount(self) -> None:
        await asyncio.to_thread(self.backend.shutdown)

    def on_resize(self, event: events.Resize) -> None:
        if self.query("#panes"):
            self._layout(event.size.width, event.size.height)

    def _layout(self, width: int | None = None, height: int | None = None) -> None:
        if not self.query("#panes"):
            return
        narrow = (width if width is not None else self.size.width) < 100
        panes = self.query_one("#panes")
        panes.set_class(narrow, "narrow")
        screen_width = width if width is not None else self.size.width
        screen_height = height if height is not None else self.size.height
        completion = self.query_one("#completion")
        completion_height = completion.size.height if completion.display else 0
        # Fixed chrome: summary (2), tabs (3), input (3), footer (1).
        available_rows = max(0, screen_height - 9 - completion_height - 1)
        operations_height = self._operations_height(available_rows)
        panes.styles.grid_rows = f"1fr 1 {operations_height}"
        available_columns = max(1, screen_width - 1)
        nodes_width = min(
            max(20, round(available_columns * self._nodes_ratio)),
            max(20, available_columns - 30),
        )
        panes.styles.grid_columns = "1fr" if narrow else f"{nodes_width} 1 1fr"
        active = self.query_one("#tabs", Tabs).active or "tab-1"
        self.query_one("#nodes").display = active == "tab-1"
        self.query_one("#column-splitter").display = active == "tab-1" and not narrow
        details = self.query_one("#details")
        details.display = active == "tab-2" or (active == "tab-1" and not narrow)
        details.set_class(active == "tab-2", "expanded")
        self.query_one("#logs").display = active == "tab-3"
        if active == "tab-3":
            self.call_after_refresh(self._flush_logs)

    def _operations_height(self, available: int) -> int:
        desired = (
            max(10, available // 2)
            if self._operations_ratio is None
            else round(available * self._operations_ratio)
        )
        maximum = max(0, available - 3)
        minimum = min(6, maximum)
        return min(max(minimum, desired), maximum)

    def on_splitter_moved(self, event: Splitter.Moved) -> None:
        panes = self.query_one("#panes")
        if event.splitter.axis == "x":
            available = max(1, panes.content_region.width - 1)
            current = round(available * self._nodes_ratio)
            width = min(max(20, current + event.delta), max(20, available - 30))
            self._nodes_ratio = width / available
        else:
            available = max(1, panes.content_region.height - 1)
            current = self._operations_height(available)
            minimum = min(6, max(0, available - 3))
            height = min(max(minimum, current - event.delta), max(0, available - 3))
            self._operations_ratio = height / available
        self._layout()

    def on_splitter_reset(self, event: Splitter.Reset) -> None:
        if event.splitter.axis == "x":
            self._nodes_ratio = 1 / 3
        else:
            self._operations_ratio = None
        self._layout()

    def _cancel_drag(self) -> None:
        for splitter in self.query(Splitter):
            splitter.action_cancel_drag()

    def on_tabs_tab_activated(self, _: Tabs.TabActivated) -> None:
        self._layout()

    def on_backend_message(self, message: BackendMessage) -> None:
        notice = message.notice
        if isinstance(notice, Closed):
            self.exit(notice.outcome)
        elif isinstance(notice, LogEvent):
            self._pending_logs.append(notice)
            self._flush_logs()
        else:
            self.snapshot = notice
            summary = Text(notice.title, style="bold").append(
                f"  |  {notice.mode}  |  {notice.phase}"
            )
            if notice.dirty:
                summary.append("  |  UNSAVED", style=WATCH)
            if notice.warning:
                summary.append(f"\n{notice.warning}", style=WATCH)
            self.query_one("#summary", Static).update(summary)
            nodes = self.query_one("#nodes", OptionList)
            names = tuple(n.name for n in notice.nodes)
            if names != self._node_names:
                nodes.clear_options().add_options(names)
                self._node_names = names
                if names:
                    nodes.highlighted = (
                        names.index(self._selected) if self._selected in names else 0
                    )
            for i, node in enumerate(notice.nodes):
                level = LEVEL_STYLE.get(node.level, "")
                stale = node.age_s > STALE_S
                nodes.replace_option_prompt_at_index(
                    i,
                    Text.assemble(
                        (node.name, "bold"),
                        " · ",
                        (node.level, level),
                        " · ",
                        (present(node).state, level),
                        (
                            (f"  STALE {node.age_s:.1f}s", BAD)
                            if stale
                            else (f"  {node.age_s:.1f}s", "dim")
                        ),
                    ),
                )
            menu = self.query_one("#menu", OptionList)
            commands = tuple(o.command for o in notice.operations)
            if commands != self._commands:
                menu.clear_options().add_options(commands)
                self._commands = commands
                menu.highlighted = 0 if commands else None
            for i, operation in enumerate(notice.operations):
                menu.replace_option_prompt_at_index(
                    i,
                    Text(operation.label, style=BAD)
                    if operation.command == "estop"
                    else Text(operation.label)
                    if operation.enabled
                    else Text(
                        f"{operation.label} — unavailable: {operation.reason}",
                        style="dim",
                    ),
                )
            self.query_one(CommandInput).commands = tuple(
                dict.fromkeys(c.split()[0] for c in commands)
            )
            if notice.selected in names:
                nodes.highlighted = names.index(notice.selected)
            if notice.phase == "save failed; retry or discard":
                self._exit_requested = False
            self._details()
            if (
                notice.phase == "complete"
                and not self._complete_prompted
                and len(self.screen_stack) == 1
            ):
                self._complete_prompted = True
                self.action_request_quit()

    def _flush_logs(self) -> None:
        if not self._pending_logs and not self._log_end_requested:
            return
        log = next(iter(self.query(RichLog)), None)
        if log is None:
            return
        if (
            not log.display
            or not log.content_region.width
            or not log.content_region.height
        ):
            return
        at_end = log.is_vertical_scroll_end or self._log_end_requested
        while self._pending_logs:
            notice = self._pending_logs.popleft()
            log.write(
                Text(
                    notice.text,
                    style=notice.style
                    or {"warn": WATCH, "error": BAD}.get(notice.level, ""),
                ),
                scroll_end=at_end,
                animate=False,
            )
        if self._log_end_requested:
            self._log_end_requested = False
            self.call_after_refresh(log.scroll_end, animate=False)

    def _details(self) -> None:
        node = next((n for n in self.snapshot.nodes if n.name == self._selected), None)
        if node is None and self.snapshot.nodes:
            node = self.snapshot.nodes[0]
        if node is None:
            return
        description = present(node)
        table = Table.grid(padding=(0, 2))
        table.add_column(overflow="fold")
        table.add_column(overflow="fold", ratio=1)
        table.add_row(Text(node.name, style="bold"), Text(f"{node.role} / {node.kind}"))
        explanation = description.explanation
        table.add_row(
            Text(description.state, style=LEVEL_STYLE.get(node.level, "")),
            explanation if isinstance(explanation, Text) else Text(explanation),
        )
        for key, value in description.values:
            table.add_row(Text(key), Text(value))
        self.query_one("#detail", Static).update(table)

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option_list.id == "nodes" and event.option_index < len(
            self._node_names
        ):
            self._selected = self._node_names[event.option_index]
            self._details()
            if (
                self.snapshot.capabilities.gravity
                and self._selected != self.snapshot.selected
            ):
                self.backend.submit("joint " + self._selected)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "menu" and event.option_index < len(
            self.snapshot.operations
        ):
            operation = self.snapshot.operations[event.option_index]
            if not operation.enabled:
                self._dispatch(operation.command)
            elif operation.command == "joint":
                self.action_command()
                self.query_one(CommandInput).value = "joint "
                self.query_one(CommandInput).cursor_position = 6
            elif operation.command == "start" and not self.snapshot.mode.startswith(
                ("record", "infer")
            ):
                self.action_command()
                self.query_one(CommandInput).value = "start "
                self.query_one(CommandInput).cursor_position = 6
            else:
                self._dispatch(operation.command)

    def on_command_input_candidates(self, event: CommandInput.Candidates) -> None:
        completion = self.query_one("#completion", Static)
        completion.update(event.text)
        completion.display = bool(event.text)
        self.call_after_refresh(self._layout)

    def on_input_submitted(self, event: CommandInput.Submitted) -> None:
        self._dispatch(event.value.strip())

    def _dispatch(self, line: str) -> None:
        name = line.partition(" ")[0]
        operation = next(
            (o for o in self.snapshot.operations if o.command == line), None
        ) or next((o for o in self.snapshot.operations if o.command == name), None)
        if operation is None or not operation.enabled:
            self.post_message(
                BackendMessage(
                    LogEvent(
                        operation.reason if operation else f"unknown command: {name}",
                        "warn",
                    )
                )
            )
            return
        if name == "estop":
            self.action_estop()
        elif name == "quit":
            self.action_request_quit()
        elif operation.confirmation == "release":
            self._cancel_drag()
            self.push_screen(
                Confirmation(
                    "Support every actuated input and follower before releasing torque.",
                    (("release", "Supported: release torque"),),
                ),
                lambda choice: self.backend.submit(line) if choice else None,
            )
        else:
            self.backend.submit(line)

    def action_command(self) -> None:
        if len(self.screen_stack) == 1:
            self.query_one(CommandInput).focus()

    def action_pane(self, direction: int) -> None:
        if len(self.screen_stack) > 1:
            return
        panes = [
            self.query_one("#" + name)
            for name in (
                "menu",
                "tabs",
                "nodes",
                "column-splitter",
                "details",
                "logs",
                "row-splitter",
                "command",
            )
            if self.query_one("#" + name).display
        ]
        index = panes.index(self.focused) if self.focused in panes else 0
        panes[(index + direction) % len(panes)].focus()

    def action_log_end(self) -> None:
        self._log_end_requested = True
        self.query_one("#tabs", Tabs).active = "tab-3"
        self._flush_logs()

    def action_estop(self) -> None:
        self.backend.emergency()

    def action_request_quit(self) -> None:
        if self._exit_requested or len(self.screen_stack) > 1:
            return
        tuning = self.snapshot.capabilities.gravity
        choices = (
            (("save", "Save and quit"), ("discard", "Discard changes and quit"))
            if tuning
            else (
                (
                    "hold",
                    "Quit with followers holding"
                    if self.snapshot.capabilities.hold
                    else "Quit",
                ),
                *(
                    ((("release", "Supported: release followers and quit"),))
                    if self.snapshot.capabilities.release
                    and self.snapshot.capabilities.hold
                    else ()
                ),
            )
        )
        prompt = (
            "Save tuning changes before quitting? The tuning device will release torque."
            if tuning
            else "Support actuated inputs before quitting: they go limp. Choose follower torque on exit."
        )

        def confirmed(choice: str | None) -> None:
            if choice is not None:
                self._exit_requested = True
                self.backend.request_close(choice)

        self._cancel_drag()
        self.push_screen(Confirmation(prompt, choices), confirmed)

    def on_key(self, event: events.Key) -> None:
        if isinstance(self.focused, CommandInput) or len(self.screen_stack) > 1:
            return
        shortcuts = {
            "e": "estop",
            "q": "quit",
            "h": "home",
            "s": "save",
            "d": "discard",
        }
        if self.snapshot.capabilities.gravity:
            shortcuts.update(
                {
                    "]": "gain +",
                    "[": "gain -",
                    "=": "hold +",
                    "-": "hold -",
                    "0": "compare",
                    "r": "resume",
                }
            )
        key = event.character or event.key
        if self.snapshot.capabilities.gravity and key in ("j", "k"):
            nodes = self.query_one("#nodes", OptionList)
            nodes.action_cursor_down() if key == "j" else nodes.action_cursor_up()
            event.stop()
            return
        command = shortcuts.get(key)
        if command:
            event.stop()
            self._dispatch(command)


def run_backend(backend: Backend) -> str:
    """Also join threads when Textual raises before or during its lifecycle."""
    try:
        return OperatorApp(backend).run() or "done"
    finally:
        backend.shutdown()
