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
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.message import Message
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Button, Footer, OptionList, RichLog, Static, Tabs
from textual.widgets.option_list import Option

from .command import CommandInput
from .models import (
    Backend,
    Closed,
    HomeOption,
    LogEvent,
    Notice,
    Operation,
    OperatorState,
    Snapshot,
)
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


class HomeModal(ModalScreen[str | None]):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", show=False),
        Binding("e,ctrl+g,f12", "app.estop", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    HomeModal { align: center middle; background: $background 70%; }
    HomeModal > Vertical { width: 76; max-width: 95%; height: auto; max-height: 95%; border: thick $accent; padding: 0 1; }
    HomeModal Static { height: auto; }
    HomeModal OptionList { height: auto; max-height: 10; border: none; }
    #home-columns { padding: 0 1; }
    """

    def __init__(self, options: tuple[HomeOption, ...], moves: str):
        super().__init__()
        self.options = options
        self.moves = moves

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(Text("Move home", style="bold"))
            yield Static(
                Text(
                    f"{'Pose':20} | {'worst joint':18} | {'dist':>7} | time",
                    style="bold",
                ),
                id="home-columns",
            )
            yield OptionList(
                *(
                    Option(self._row(option), disabled=not option.valid)
                    for option in self.options
                ),
                id="home-poses",
            )
            if self.moves:
                yield Static(f"Moves: {self.moves}", markup=False)
            yield Static("Enter: move   Esc: cancel   e: ESTOP")

    @staticmethod
    def _row(option: HomeOption) -> Text:
        if not option.valid:
            return Text(f"{option.name} — unavailable: {option.reason}")
        name = option.name + (" (default)" if option.default else "")
        dist = f"{option.dist:.3g}" if option.dist is not None else "—"
        eta = f"{option.eta_s:.1f} s" if option.eta_s is not None else "—"
        row = Text(f"{name:20} | {option.worst_joint or '—':18} | {dist:>7} | {eta}")
        if option.over_timeout:
            row.append(" > timeout!", style=WATCH)
        return row

    def on_mount(self) -> None:
        poses = self.query_one(OptionList)
        valid = [index for index, option in enumerate(self.options) if option.valid]
        poses.highlighted = next(
            (index for index in valid if self.options[index].default),
            valid[0] if valid else None,
        )
        poses.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self.options[event.option_index].name)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ActionButton(Button):
    # Textual's Button binds Enter. Handle Space through the same action.
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("space", "press", show=False),
    ]


_DEFAULT_ACTION: dict[OperatorState, str] = {
    "recording": "act-stop",
    "stopped": "act-save",
    "estop": "act-quit",
    "fault": "act-quit",
    "homing": "act-quit",
}

_NEXT_ACTION: dict[OperatorState, str] = {
    "launching": "Wait for the session to become ready",
    "hold": "Start recording, teleoperate, or move home",
    "teleop": "Start recording from here or stop teleoperating",
    "recording": "Stop recording when the task is done",
    "stopped": "Save or discard the episode",
    "homing": "Wait for the home move to finish",
    "estop": "Quit and restart the session",
    "fault": "Review the fault and quit",
    "complete": "Start another episode or quit",
}

_ACTIONS = {
    "act-start": ("start", "[Space] ▶ START"),
    "act-teleop": ("teleop", "[t] TELEOP"),
    "act-home": ("home", "[h] Home…"),
    "act-stop": ("stop", "[Space] ■ STOP"),
    "act-save": ("save", "[s] ✓ SAVE"),
    "act-save-success": ("save success", "Save success"),
    "act-save-failure": ("save failure", "Save failure"),
    "act-discard": ("discard", "[d] Discard…"),
    "act-quit": ("quit", "[q] Quit…"),
    "sec-home": ("home", "[h] Home…"),
    "sec-release": ("release", "[r] Release…"),
    "sec-quit": ("quit", "[q] Quit…"),
}

_TOGGLE_COMMANDS = ("teleop", "stop_teleop", "policy")


def _line(text: str = "", style: str = "") -> Text:
    return Text(text, style=style, no_wrap=True, overflow="ellipsis")


def _clock(seconds: float) -> str:
    minutes, seconds_int = divmod(max(0, int(seconds)), 60)
    return f"{minutes:02}:{seconds_int:02}"


def _recording_progress(notice: Snapshot) -> list[str]:
    if notice.mode.startswith("run"):
        return [
            _clock(notice.elapsed_s or 0),
            f"{notice.rows or 0} rows",
            f"saved {notice.saved_episodes}",
        ]

    progress = [notice.episode] if notice.episode else []
    if notice.steps:
        progress.append(f"{notice.step or 0}/{notice.steps}")
    if notice.duration_s or notice.elapsed_s is not None:
        clock = _clock(notice.elapsed_s or 0)
        progress.append(
            f"{clock} / {_clock(notice.duration_s)}" if notice.duration_s else clock
        )
    if notice.steps or notice.duration_s:
        ratio = (
            (notice.step or 0) / notice.steps
            if notice.steps
            else (notice.elapsed_s or 0) / notice.duration_s
            if notice.duration_s
            else 0
        )
        ratio = min(1, max(0, ratio))
        full = int(ratio * 10)
        progress.append(f"[{'█' * full}{'░' * (10 - full)}] {ratio:.0%}")
    return progress


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
    #summary { height: 3; padding: 0 1; background: $boost; }
    #summary-top, #summary-head, #summary-state, #summary-detail { height: 1; }
    #summary-head { width: 1fr; }
    #btn-estop { height: 1; width: 12; min-width: 12; }
    #summary.state-hold #summary-state { color: $success; }
    #summary.state-teleop #summary-state { color: $accent; }
    #summary.state-recording #summary-state { color: $error; }
    #summary.state-stopped #summary-state, #summary.state-homing #summary-state { color: $warning; }
    #summary.state-fault #summary-state { color: $error; }
    #summary.state-estop, #estop-notice { background: #ad1515; color: #ffffff; text-style: bold; }
    #tabs { height: 3; }
    #panes { height: 1fr; layout: grid; grid-size: 3 3; grid-columns: 1fr 1 2fr; grid-rows: 1fr 1 1fr; }
    #nodes, #details, #menu, #logs { border: solid $primary; height: 1fr; }
    #menu, #logs, #row-splitter { column-span: 3; }
    #session-actions, #tuning-menu { height: 1fr; }
    #tuning-menu { border: none; }
    #action-hint, #action-reason, #secondary-actions { height: 1; }
    #action-hint.refused { color: $warning; text-style: bold; }
    #action-reason { color: $text-muted; }
    #primary-actions { height: 3; }
    #primary-actions Button { height: 3; width: 1fr; min-width: 0; margin-right: 1; }
    #primary-actions Button:last-of-type { margin-right: 0; }
    #estop-notice { height: 3; width: 2fr; content-align: center middle; }
    #secondary-actions Button { height: 1; min-width: 0; margin-right: 1; }
    ActionButton.unavailable { text-opacity: 55%; }
    ActionButton.flash-reject { background: $warning !important; color: $text; text-opacity: 100%; }
    ActionButton.flash-ok { background: $success !important; color: $text; }
    #btn-estop.flash-ok { background: #ad1515 !important; color: #ffffff; }
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
        self.snapshot = Snapshot("roboloom", "", "launching", state="launching")
        self._last_ui_state: OperatorState = ""
        self._refusal = ""
        self._action_commands: dict[str, str] = {}
        self._flash_timers: dict[str, Timer] = {}
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
        with Vertical(id="summary"):
            with Horizontal(id="summary-top"):
                yield Static(id="summary-head")
                yield ActionButton(
                    Content("[e] ESTOP"), id="btn-estop", variant="error", compact=True
                )
            yield Static(id="summary-state")
            yield Static(id="summary-detail")
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
            with Container(id="menu"):
                with Vertical(id="session-actions"):
                    yield Static(id="action-hint")
                    with Horizontal(id="primary-actions"):
                        yield Static(
                            "ESTOP — restart required", id="estop-notice", markup=False
                        )
                        for button_id, (_, label) in _ACTIONS.items():
                            if button_id.startswith("act-"):
                                yield ActionButton(
                                    label, id=button_id, variant="primary"
                                )
                    yield Static(id="action-reason")
                    with Horizontal(id="secondary-actions"):
                        for button_id, (_, label) in _ACTIONS.items():
                            if button_id.startswith("sec-"):
                                yield ActionButton(
                                    Content(label), id=button_id, compact=True
                                )
                yield OptionList(id="tuning-menu", markup=False)
        yield Static("", id="completion", markup=False)
        yield CommandInput()
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#nodes").border_title = "Nodes (display selection only)"
        self.query_one("#details").border_title = "Selected node"
        self.query_one("#menu").border_title = "Operations (whole robot)"
        self.query_one("#logs").border_title = "Events / dora log · Ctrl-O: latest"
        self._update_summary()
        self._update_session_actions()
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
        # Fixed chrome: summary (3), tabs (3), input (3), footer (1).
        available_rows = max(0, screen_height - 10 - completion_height - 1)
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

    @property
    def _minimum_operations_height(self) -> int:
        return 6 if self.snapshot.capabilities.gravity else 8

    def _operations_height(self, available: int) -> int:
        desired = (
            max(10, available // 2)
            if self._operations_ratio is None
            else round(available * self._operations_ratio)
        )
        maximum = max(0, available - 3)
        minimum = min(self._minimum_operations_height, maximum)
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
            minimum = min(self._minimum_operations_height, max(0, available - 3))
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
            gravity_changed = (
                self.query_one("#tuning-menu").display != notice.capabilities.gravity
            )
            self._update_summary()
            self._update_session_actions()
            if gravity_changed:
                self._layout()
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
            commands = tuple(o.command for o in notice.operations)
            if notice.capabilities.gravity:
                self._update_tuning_menu(commands)
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

    @property
    def _effective_state(self) -> OperatorState:
        notice = self.snapshot
        return notice.state or ("estop" if "ESTOP" in notice.phase.upper() else "hold")

    @property
    def _teleop_operation(self) -> Operation | None:
        return next(
            (op for op in self.snapshot.operations if op.command in _TOGGLE_COMMANDS),
            None,
        )

    def _operation(self, line: str) -> Operation | None:
        return next(
            (op for op in self.snapshot.operations if op.command == line), None
        ) or next(
            (
                op
                for op in self.snapshot.operations
                if op.command == line.partition(" ")[0]
            ),
            None,
        )

    def _update_summary(self) -> None:
        notice = self.snapshot
        state = self._effective_state
        summary = self.query_one("#summary")
        for name in _NEXT_ACTION:
            summary.set_class(
                name == state and not notice.capabilities.gravity, f"state-{name}"
            )

        head = _line()
        head.append(notice.title, style="bold")
        head.append(f" · {notice.mode}" if notice.mode else "")
        if notice.dirty:
            head.append("  UNSAVED", style="bold yellow")
        self.query_one("#summary-head", Static).update(head)

        label, parts = state.upper(), []
        if notice.capabilities.gravity:
            label = notice.phase
        elif state == "recording":
            label, parts = "● REC", _recording_progress(notice)
            if notice.task:
                parts.append(f"task: {notice.task}")
        elif state in ("teleop", "hold"):
            label = "TELEOP (no recording)" if state == "teleop" else "HOLD"
            saved = f"saved {notice.saved_episodes}"
            if state == "hold" and notice.pending_saves:
                saved += f" ({notice.pending_saves} queued)"
            parts = [saved]
        elif state == "stopped":
            label = "STOPPED — save or discard"
            parts = [notice.episode] if notice.episode else []
            if notice.rows is not None:
                parts.append(f"{notice.rows} rows")
        elif state == "estop":
            label = "ESTOP — restart required"
        elif state == "fault":
            parts = [notice.warning] if notice.warning else []
        elif state in ("homing", "launching", "complete"):
            parts = [notice.phase] if notice.phase.upper() != label else []
        state_line = _line()
        state_line.append(label, style="bold")
        if parts:
            state_line.append("  " + "  ".join(parts))
        self.query_one("#summary-state", Static).update(state_line)

        detail = _line()
        if notice.control == "policy":
            detail.append(" Driver: POLICY ", style="bold white on #653a99")
        elif notice.control == "leader":
            detail.append(" Driver: LEADER ", style="bold black on #ff9c4a")
        if notice.warning:
            if detail:
                detail.append("  ")
            detail.append(
                notice.warning, style=BAD if state in ("fault", "estop") else WATCH
            )
        for node in notice.nodes:
            if detail:
                detail.append("  ")
            detail.append(f"{node.name} ")
            detail.append(
                "●",
                style=WATCH
                if node.age_s > STALE_S and node.level != "error"
                else LEVEL_STYLE.get(node.level, WATCH),
            )
        self.query_one("#summary-detail", Static).update(detail)

    def _update_session_actions(self) -> None:
        notice = self.snapshot
        caps = notice.capabilities
        tuning = self.query_one("#tuning-menu", OptionList)
        focus_tuning = caps.gravity and not tuning.display
        tuning.display = caps.gravity
        self.query_one("#session-actions").display = not caps.gravity
        if caps.gravity:
            if (
                focus_tuning
                and len(self.screen_stack) == 1
                and not isinstance(self.focused, CommandInput)
            ):
                tuning.focus()
            return

        state = self._effective_state
        default_id = _DEFAULT_ACTION.get(state, "act-start")
        teleop = self._teleop_operation
        visible = {default_id}
        if state in ("hold", "complete", "launching") and (
            caps.home or self._operation("home") is not None
        ):
            visible.add("act-home")
        if teleop is not None and (
            state == "teleop"
            or (caps.teleop and state in ("hold", "complete", "launching"))
            or (caps.handback and state == "recording")
        ):
            visible.add("act-teleop")
        if state == "stopped":
            visible.update(("act-save-success", "act-save-failure", "act-discard"))
        if state == "recording" and self._operation("discard") is not None:
            visible.add("act-discard")
        if state != "estop":
            if caps.home and "act-home" not in visible:
                visible.add("sec-home")
            if caps.release:
                visible.add("sec-release")
            if "act-quit" not in visible:
                visible.add("sec-quit")

        self._action_commands.clear()
        for button_id, (command, label) in _ACTIONS.items():
            button = self.query_one(f"#{button_id}", Button)
            button.display = button_id in visible
            if not button.display:
                continue
            if button_id == "act-teleop" and teleop is not None:
                command, label = teleop.command, f"[t] {teleop.label}"
            elif button_id == "act-start" and state == "teleop":
                label += " (from here)"
            self._action_commands[button_id] = command
            button.label = Content(label)
            operation = self._operation(command)
            button.set_class(operation is None or not operation.enabled, "unavailable")

        self.query_one("#estop-notice").display = state == "estop"
        operation = self._operation(_ACTIONS[default_id][0])
        reason = (
            f"Alignment: {notice.alignment}"
            if notice.alignment
            else operation.reason
            if operation is not None and not operation.enabled
            else ""
        )
        self.query_one("#action-reason", Static).update(_line(reason))
        changed = state != self._last_ui_state
        if changed:
            self._refusal = ""
        self._update_action_hint()
        if len(self.screen_stack) == 1:
            self._last_ui_state = state
            if not isinstance(self.focused, CommandInput) and (
                changed or self.focused is self.query_one("#menu")
            ):
                self.query_one(f"#{default_id}", Button).focus()

    def _update_action_hint(self) -> None:
        hint = self.query_one("#action-hint", Static)
        hint.set_class(bool(self._refusal), "refused")
        hint.update(
            _line(self._refusal or f"NEXT: {_NEXT_ACTION[self._effective_state]}")
        )

    def _update_tuning_menu(self, commands: tuple[str, ...]) -> None:
        menu = self.query_one("#tuning-menu", OptionList)
        if commands != self._commands:
            menu.clear_options().add_options(commands)
            self._commands = commands
            menu.highlighted = 0 if commands else None
        for i, operation in enumerate(self.snapshot.operations):
            menu.replace_option_prompt_at_index(
                i,
                Text(operation.label, style=BAD)
                if operation.command == "estop"
                else Text(operation.label)
                if operation.enabled
                else Text(
                    f"{operation.label} — unavailable: {operation.reason}", style="dim"
                ),
            )

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
        if event.option_list.id == "tuning-menu" and event.option_index < len(
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

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "btn-estop":
            self.action_estop()
        elif button_id is not None and button_id in self._action_commands:
            self._activate(self._action_commands[button_id], button_id)

    def _activate(self, command: str, button_id: str | None = None) -> None:
        if command == "estop":
            self.action_estop()
            return
        if button_id is None:
            button_id = next(
                (
                    key
                    for key, value in self._action_commands.items()
                    if value == command
                ),
                None,
            )
        self._dispatch(command, button_id, interactive=True)

    def _flash(self, button_id: str | None, css_class: str) -> None:
        if button_id is None:
            return
        button = self.query_one(f"#{button_id}", Button)
        timer = self._flash_timers.pop(button_id, None)
        if timer is not None:
            timer.stop()
        button.remove_class("flash-reject", "flash-ok")
        button.add_class(css_class)

        def clear_flash() -> None:
            button.remove_class(css_class)
            self._flash_timers.pop(button_id, None)

        self._flash_timers[button_id] = self.set_timer(0.25, clear_flash)

    def _reject(self, reason: str, button_id: str | None = None) -> None:
        if not self.snapshot.capabilities.gravity:
            self._refusal = reason
            self._update_action_hint()
            self.notify(reason, severity="warning", timeout=4)
            self._flash(
                button_id or _DEFAULT_ACTION.get(self._effective_state, "act-start"),
                "flash-reject",
            )
        self.post_message(BackendMessage(LogEvent(reason, "warn")))

    def _dispatch(
        self, line: str, button_id: str | None = None, *, interactive: bool = False
    ) -> None:
        name = line.partition(" ")[0]
        operation = self._operation(line)
        if operation is None or not operation.enabled:
            reason = operation.reason if operation else f"unknown command: {name}"
            self._reject(reason or f"{name} is unavailable", button_id)
            return
        if not self.snapshot.capabilities.gravity:
            self._refusal = ""
            self._update_action_hint()
        self._flash(button_id, "flash-ok")
        if name == "estop":
            self.action_estop()
        elif name == "quit":
            self.action_request_quit()
        elif interactive and name == "home" and self.snapshot.home_options:
            self._cancel_drag()
            self.push_screen(
                HomeModal(self.snapshot.home_options, self.snapshot.home_moves),
                lambda choice: (
                    self._dispatch(f"home {choice}") if choice is not None else None
                ),
            )
        elif (
            interactive
            and name == "start"
            and not self.snapshot.mode.startswith(("record", "infer"))
        ):
            self.action_command()
            command = self.query_one(CommandInput)
            command.value = "start "
            command.cursor_position = len(command.value)
        elif operation.confirmation == "release":
            self._cancel_drag()
            self.push_screen(
                Confirmation(
                    "Before releasing torque: "
                    f"{self.snapshot.capabilities.release_note}.",
                    (("release", "Done: release torque"),),
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
        menu_id = (
            "tuning-menu"
            if self.snapshot.capabilities.gravity
            else _DEFAULT_ACTION.get(self._effective_state, "act-start")
        )
        panes = [
            self.query_one("#" + name)
            for name in (
                menu_id,
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
        focused = self.focused
        menu = self.query_one("#menu")
        if focused is menu or (focused is not None and menu in focused.ancestors):
            focused = panes[0]
        index = panes.index(focused) if focused in panes else 0
        panes[(index + direction) % len(panes)].focus()

    def action_log_end(self) -> None:
        self._log_end_requested = True
        self.query_one("#tabs", Tabs).active = "tab-3"
        self._flush_logs()

    def action_estop(self) -> None:
        # App-level priority bindings also reach here while the modal is open.
        if isinstance(self.screen, HomeModal):
            self.screen.dismiss(None)
        self.backend.emergency()
        self._flash("btn-estop", "flash-ok")

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
                    else "Quit without releasing"
                    if self.snapshot.capabilities.torqued
                    else "Quit",
                ),
                *(
                    ((("release", "Done: release torque and quit"),))
                    if self.snapshot.capabilities.torqued
                    else ()
                ),
                *(
                    (
                        (
                            (
                                "reselect",
                                "Quit and choose options again"
                                + (
                                    " (followers hold)"
                                    if self.snapshot.capabilities.hold
                                    else ""
                                ),
                            ),
                        )
                    )
                    if self.snapshot.capabilities.reselect
                    else ()
                ),
            )
        )
        caps = self.snapshot.capabilities
        notes = [
            f"When the session ends, {caps.quit_note}." if caps.quit_note else "",
            f"Releasing torque: {caps.release_note}." if caps.torqued else "",
        ]
        prompt = (
            "Save tuning changes before quitting? The tuning device will release torque."
            if tuning
            else " ".join(n for n in notes if n) or "Quit?"
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
        caps = self.snapshot.capabilities
        shortcuts = {
            "e": "estop",
            "q": "quit",
            "h": "home",
            "s": "save",
            "d": "discard",
            "r": "resume" if caps.gravity else "release",
        }
        if caps.teleop:
            toggle = self._teleop_operation
            shortcuts["t"] = toggle.command if toggle is not None else "teleop"
        if caps.handback:
            shortcuts["p"] = "policy"
        if caps.gravity:
            shortcuts.update(
                {
                    "]": "gain +",
                    "[": "gain -",
                    "=": "hold +",
                    "-": "hold -",
                    "0": "compare",
                }
            )
        elif not isinstance(self.focused, Button):
            state = self._effective_state
            if state in ("hold", "teleop", "complete"):
                shortcuts[" "] = "start"
            elif state == "recording":
                shortcuts[" "] = "stop"

        key = event.character or event.key
        if caps.gravity and key in ("j", "k"):
            nodes = self.query_one("#nodes", OptionList)
            nodes.action_cursor_down() if key == "j" else nodes.action_cursor_up()
            event.stop()
            return
        command = shortcuts.get(key)
        if command:
            event.stop()
            event.prevent_default()
            if caps.gravity:
                self._dispatch(command)
            else:
                self._activate(command)


def run_backend(backend: Backend) -> str:
    """Also join threads when Textual raises before or during its lifecycle."""
    try:
        return OperatorApp(backend).run() or "done"
    finally:
        backend.shutdown()
