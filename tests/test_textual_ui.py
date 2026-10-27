"""Operator contracts exercised without real hardware or terminal input."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import replace

import pytest
from rich.console import Console
from textual import events
from textual.widgets import OptionList, RichLog, Static, Tabs

from roboloom.ui.app import BackendMessage, Confirmation, OperatorApp, run_backend
from roboloom.ui.command import CommandInput
from roboloom.ui.models import (
    Capabilities,
    Closed,
    LogEvent,
    NodeSnapshot,
    Operation,
    Publish,
    Snapshot,
)
from roboloom.ui.presenters import (
    KINDS,
    ROLES,
    Presentation,
    present,
    register_presenter,
)


class FakeBackend:
    def __init__(self, *, gravity: bool = False):
        self.commands: list[str] = []
        self.stops = 0
        self.choices: list[str] = []
        self.closed = False
        self.publish: Publish = lambda _: None
        self.snapshot = Snapshot(
            "unknown robot",
            "run",
            "ready",
            nodes=(
                NodeSnapshot(
                    "three-axis",
                    "unregistered",
                    "alien",
                    fields={"q_rad": [0.1, 0.2, 0.3], "travel_mm": 9.0},
                ),
                NodeSnapshot(
                    "one-axis", "unregistered", "other", fields={"force_N": 2.0}
                ),
            ),
            operations=(
                Operation("start", "Start"),
                Operation("stop", "Stop"),
                Operation("save", "Save"),
                Operation("home", "Home", False, "no home pose"),
                Operation("release", "Release", confirmation="release"),
                Operation("estop", "Emergency stop"),
                Operation("quit", "Quit", confirmation="quit"),
            ),
            capabilities=Capabilities(release=True, hold=True, gravity=gravity),
        )
        if gravity:
            self.snapshot = replace(self.snapshot, selected="three-axis")

    def start(self, publish: Publish) -> None:
        self.publish = publish
        self.publish(self.snapshot)

    def submit(self, command: str) -> None:
        self.commands.append(command)

    def emergency(self) -> None:
        self.stops += 1

    def request_close(self, choice: str) -> None:
        self.choices.append(choice)
        self.publish(Closed())

    def shutdown(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_edit_history_completion_paste_and_shortcut_isolation():
    backend = FakeBackend()
    app = OperatorApp(backend)
    async with app.run_test(size=(120, 35)) as pilot:
        assert app.focused is app.query_one("#menu")
        await pilot.press("ctrl+l", "s", "tab")
        command = app.query_one(CommandInput)
        assert command.value == "start"
        await pilot.press("tab")
        assert command.value == "stop"
        await pilot.press("shift+tab")
        assert command.value == "start"
        await pilot.press("enter")
        assert not backend.commands and command.value == "start"
        await pilot.press("space", "e", "q", "h")
        assert not backend.stops and not backend.choices
        await pilot.press("left", "delete", "backspace", "enter")
        assert backend.commands == ["start e"]
        await pilot.press("up")
        assert command.value == "start e"
        await pilot.press("down")
        assert command.value == ""
        command.post_message(events.Paste("start 日本語\n複数行\r\ntask"))
        await pilot.pause()
        assert command.value == "start 日本語 複数行 task"
        assert backend.commands == ["start e"]
        await pilot.press("enter")
        assert backend.commands[-1] == "start 日本語 複数行 task"
        await pilot.press("s", "tab", "escape")
        assert command.value == "s"
        assert command.history == ["start e", "start 日本語 複数行 task"]


@pytest.mark.asyncio
async def test_resize_selection_focus_and_no_home():
    backend = FakeBackend()
    app = OperatorApp(backend)
    async with app.run_test(size=(120, 35)) as pilot:
        assert not app.query_one("#logs").display
        assert app.query_one("#menu").region.height >= 10
        assert (
            app.query_one("#menu").region.bottom <= app.query_one("#command").region.y
        )
        app.query_one("#nodes", OptionList).focus()
        await pilot.press("down")
        assert app._selected == "one-axis"
        await pilot.press("ctrl+l", "t", "a", "s", "k")
        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        assert app.query_one("#tabs").display
        assert not app.query_one("#logs").display
        assert app.query_one("#menu").region.height >= 10
        assert (
            app.query_one("#menu").region.bottom <= app.query_one("#command").region.y
        )
        assert app.query_one(CommandInput).value == "task"
        assert app._selected == "one-axis"
        app.query_one("#tabs", Tabs).active = "tab-2"
        await pilot.pause()
        assert app.query_one("#details").display and not app.query_one("#nodes").display
        console = Console(record=True)
        console.print(app.query_one("#detail", Static).content)
        assert "force_N" in console.export_text()
        await pilot.press("ctrl+p")
        assert app.focused is app.query_one("#row-splitter")
        await pilot.press("ctrl+l", "ctrl+n")
        assert app.focused is app.query_one("#menu")
        await pilot.press("h")
        assert not backend.commands
        await pilot.resize_terminal(140, 40)
        await pilot.pause()
        assert not app.query_one("#nodes").display and app.query_one("#details").display
        app.query_one("#tabs", Tabs).active = "tab-1"
        await pilot.pause()
        assert app.query_one("#nodes").display and app.query_one("#details").display
        assert not app.query_one("#logs").display
        assert app.query_one(CommandInput).value == "task"
        assert not backend.commands


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["ctrl+c", "ctrl+q"])
async def test_exit_cancel_is_default_and_estop_works_inside_dialog(key: str):
    backend = FakeBackend()
    app = OperatorApp(backend)
    async with app.run_test() as pilot:
        await pilot.press(key, "enter")
        assert not backend.choices
        await pilot.press(key)
        assert isinstance(app.screen, Confirmation)
        backend.publish(
            replace(
                backend.snapshot, phase="saving", warning="new status during dialog"
            )
        )
        await pilot.pause()
        assert app.snapshot.phase == "saving"
        await pilot.press("ctrl+g")
        assert backend.stops == 1
        await pilot.press("e", "s")
        assert backend.stops == 1 and not backend.commands
        await pilot.press("escape")
        assert not backend.choices
        await pilot.press(key, "down", "enter")
    assert backend.choices == ["hold"] and backend.closed


@pytest.mark.asyncio
async def test_release_requires_confirmation_and_tuning_exit_choices():
    backend = FakeBackend(gravity=True)
    app = OperatorApp(backend)
    async with app.run_test() as pilot:
        app._dispatch("release")
        await pilot.pause()
        await pilot.press("enter")
        assert backend.commands == []
        app._dispatch("release")
        await pilot.pause()
        await pilot.press("down", "enter")
        assert backend.commands == ["release"]
        await pilot.press("ctrl+q", "down", "enter")
    assert backend.choices == ["save"]


@pytest.mark.asyncio
async def test_log_scroll_is_preserved_and_latest_is_explicit():
    backend = FakeBackend()
    app = OperatorApp(backend)
    async with app.run_test(size=(120, 40)) as pilot:
        for k in range(100):
            backend.publish(LogEvent(f"event {k}"))
        await pilot.pause()
        assert not app.query_one("#logs").display
        app.query_one("#tabs", Tabs).active = "tab-3"
        await pilot.pause(0.15)
        log = app.query_one(RichLog)
        assert len(log.lines) == 100
        assert app.query_one("#menu").display
        log.scroll_home(animate=False)
        await pilot.pause()
        old = log.scroll_y
        app.query_one("#tabs", Tabs).active = "tab-1"
        await pilot.pause()
        backend.publish(LogEvent("new event"))
        await pilot.pause()
        app.query_one("#tabs", Tabs).active = "tab-3"
        await pilot.pause(0.15)
        assert len(log.lines) == 101
        assert log.scroll_y == old
        app.query_one("#tabs", Tabs).active = "tab-1"
        await pilot.pause()
        await pilot.press("ctrl+o")
        assert app.query_one("#logs").display
        assert log.is_vertical_scroll_end
        backend.publish(LogEvent("followed event"))
        await pilot.pause()
        assert log.is_vertical_scroll_end


def test_presenters_are_optional_and_kind_precedes_role():
    node = NodeSnapshot(
        "stage", "strange-role", "alien", fields={"angle_deg": [1, 2], "stroke_mm": 0.5}
    )
    assert present(node).values == (("angle_deg", "[1, 2]"), ("stroke_mm", "0.5"))
    try:
        register_presenter(role="strange-role")(lambda _: Presentation("role", "", ()))
        assert present(node).state == "role"
        register_presenter(kind="alien")(lambda _: Presentation("kind", "", ()))
        assert present(node).state == "kind"
    finally:
        KINDS.pop("alien", None)
        ROLES.pop("strange-role", None)


def test_run_backend_cleans_up_even_when_textual_crashes(monkeypatch):
    backend = FakeBackend()

    def crash(self: OperatorApp) -> str:
        raise RuntimeError("UI failure")

    monkeypatch.setattr(OperatorApp, "run", crash)
    with pytest.raises(RuntimeError, match="UI failure"):
        run_backend(backend)
    assert backend.closed


@pytest.mark.asyncio
async def test_background_notifications_use_messages():
    backend = FakeBackend()
    app = OperatorApp(backend)
    async with app.run_test() as pilot:

        def notify() -> None:
            backend.publish(replace(backend.snapshot, warning="thread update"))

        thread = threading.Thread(target=notify)
        thread.start()
        await asyncio.to_thread(thread.join)
        await pilot.pause()
        assert app.snapshot.warning == "thread update"
        assert isinstance(BackendMessage(LogEvent("x")).notice, LogEvent)


@pytest.mark.asyncio
async def test_gravity_character_keys_share_commands_and_are_suppressed_in_input():
    backend = FakeBackend(gravity=True)
    backend.snapshot = replace(
        backend.snapshot,
        operations=(
            *backend.snapshot.operations,
            Operation("gain +", "Gain +"),
            Operation("gain -", "Gain -"),
            Operation("hold +", "Hold +"),
            Operation("hold -", "Hold -"),
            Operation("compare", "Compare"),
            Operation("resume", "Resume"),
        ),
    )
    app = OperatorApp(backend)
    async with app.run_test() as pilot:
        await pilot.press("]", "[", "=", "-", "0", "r")
        assert backend.commands == [
            "gain +",
            "gain -",
            "hold +",
            "hold -",
            "compare",
            "resume",
        ]
        await pilot.press("ctrl+l", "]", "[", "=", "-", "0", "r", "j", "k", "e")
        assert len(backend.commands) == 6 and backend.stops == 0
        await pilot.press("ctrl+g")
        assert backend.stops == 1
        assert app.query_one(CommandInput).value == "][=-0rjke"
