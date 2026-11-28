"""Operator contracts exercised without real hardware or terminal input."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import mock_project
from rich.console import Console
from rich.text import Text
from textual import events
from textual.pilot import Pilot
from textual.widgets import Button, Footer, OptionList, RichLog, Static, Tabs

from roboloom import Session
from roboloom.ui.app import Confirmation, HomeModal, OperatorApp, run_backend
from roboloom.ui.backend import RecordingPlan, SessionBackend
from roboloom.ui.command import CommandInput
from roboloom.ui.models import (
    Capabilities,
    Closed,
    HomeOption,
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
from roboloom.ui.splitter import Splitter


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
async def test_viewer_links_are_shown_in_selected_node_details():
    backend = FakeBackend()
    target = "rerun+http://robot.example:9876/proxy"
    url = "http://robot.example:9090/?url=rerun%2Bhttp%3A%2F%2Frobot.example%3A9876%2Fproxy"
    local_url = (
        "http://localhost:9090/?url=rerun%2Bhttp%3A%2F%2Flocalhost%3A9876%2Fproxy"
    )
    viewer = NodeSnapshot(
        "viewer",
        "viewer",
        fields={
            "state": "viewing",
            "target": target,
            "url": url,
            "local_url": local_url,
        },
    )
    backend.snapshot = replace(
        backend.snapshot, nodes=(*backend.snapshot.nodes, viewer)
    )
    app = OperatorApp(backend)
    async with app.run_test(size=(80, 35)) as pilot:
        assert not app.query("#viewer-links")
        app.query_one("#nodes", OptionList).focus()
        await pilot.press("down", "down")
        app.query_one("#tabs", Tabs).active = "tab-2"
        await pilot.pause()
        assert app.query_one("#details").display
        detail = app.query_one("#detail", Static)
        console = Console(width=160)
        with console.capture() as capture:
            console.print(detail.content)
        assert f"target{target}url{url}local_url{local_url}" in "".join(
            capture.get().split()
        )

        for url_fields in ({}, {"url": None, "local_url": None}):
            node = replace(viewer, fields={"target": target, **url_fields})
            backend.publish(
                replace(backend.snapshot, nodes=(*backend.snapshot.nodes[:-1], node))
            )
            await pilot.pause()
            with console.capture() as capture:
                console.print(detail.content)
            rendered = capture.get()
            assert "target" in rendered and target in rendered
            assert "url" not in rendered


@pytest.mark.asyncio
async def test_edit_history_completion_paste_and_shortcut_isolation():
    backend = FakeBackend()
    app = OperatorApp(backend)
    async with app.run_test(size=(120, 35)) as pilot:
        assert app.focused is app.query_one("#act-start")
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
        assert app.focused is app.query_one("#act-start")
        await pilot.press("h")
        assert not backend.commands
        assert _status_text(app, "#action-hint") == "no home pose"
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
async def test_exit_cancel_is_default_and_estop_works_inside_dialog():
    backend = FakeBackend()
    app = OperatorApp(backend)
    async with app.run_test() as pilot:
        await pilot.press("ctrl+c")
        assert isinstance(app.screen, Confirmation)
        await pilot.press("escape")
        await pilot.press("ctrl+q", "enter")
        assert not backend.choices
        await pilot.press("ctrl+q")
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
        await pilot.press("ctrl+q", "down", "enter")
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


def test_presenters_keep_the_renderer_emphasis():
    node = NodeSnapshot(
        "follower",
        "follower",
        "rakuda2",
        level="error",
        fields={"mode": "HOLD", "home": "ready", "error": "overload"},
    )
    detail = present(node).explanation
    assert isinstance(detail, Text)
    styles = {str(span.style) for span in detail.spans}
    assert {"bold magenta", "bold red"} <= styles  # home pose name, last error


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
        assert app.focused is app.query_one("#tuning-menu", OptionList)
        assert not app.query_one("#session-actions").display
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


def _status_text(app: OperatorApp, selector: str) -> str:
    content = app.query_one(selector, Static).content
    assert isinstance(content, Text)
    return content.plain


@pytest.mark.asyncio
async def test_session_banner_displays_state_progress_and_driver():
    backend = FakeBackend()
    app = OperatorApp(backend)
    async with app.run_test(size=(80, 24)) as pilot:
        snapshot = backend.snapshot
        backend.publish(
            replace(snapshot, dirty=True, saved_episodes=3, pending_saves=2)
        )
        await pilot.pause()
        assert app.query_one("#summary").region.height == 3
        for y, selector in enumerate(
            ("#summary-head", "#summary-state", "#summary-detail")
        ):
            region = app.query_one(selector).region
            assert (region.y, region.height) == (y, 1)
        assert "unknown robot · run  UNSAVED" == _status_text(app, "#summary-head")
        assert "HOLD  saved 3 (2 queued)" == _status_text(app, "#summary-state")
        assert app.query_one("#summary").has_class("state-hold")
        assert "three-axis ●" in _status_text(app, "#summary-detail")

        for status, expected in (
            (
                replace(snapshot, state="teleop", saved_episodes=3),
                ("TELEOP (no recording)", "saved 3"),
            ),
            (
                replace(
                    snapshot,
                    state="recording",
                    mode="record / mock",
                    episode="2/3",
                    step=10,
                    steps=20,
                    elapsed_s=3,
                    duration_s=8,
                    task="pick",
                ),
                (
                    "● REC",
                    "2/3",
                    "10/20",
                    "00:03 / 00:08",
                    "[█████░░░░░] 50%",
                    "task: pick",
                ),
            ),
            (
                replace(
                    snapshot,
                    state="recording",
                    elapsed_s=85,
                    rows=240,
                    saved_episodes=2,
                ),
                ("● REC", "01:25", "240 rows", "saved 2"),
            ),
            (
                replace(snapshot, state="stopped", episode="2/3", rows=240),
                ("STOPPED — save or discard", "2/3", "240 rows"),
            ),
            (replace(snapshot, phase="ESTOP: latched"), ("ESTOP — restart required",)),
        ):
            backend.publish(status)
            await pilot.pause()
            assert all(part in _status_text(app, "#summary-state") for part in expected)

        assert app.query_one("#summary").has_class("state-estop")
        for owner, color in (("policy", "#653a99"), ("leader", "#ff9c4a")):
            backend.publish(
                replace(
                    snapshot, state="recording", control=owner, warning="real warning"
                )
            )
            await pilot.pause()
            detail = app.query_one("#summary-detail", Static).content
            assert isinstance(detail, Text)
            assert f"Driver: {owner.upper()}" in detail.plain
            assert "real warning" in detail.plain
            assert any(color in str(span.style) for span in detail.spans)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(80, 24), (120, 36), (200, 50)])
async def test_session_actions_fit_viewport(size):
    backend = FakeBackend()
    app = OperatorApp(backend)
    async with app.run_test(size=size) as pilot:
        for state, ids in (
            ("hold", ("act-start", "act-home")),
            (
                "stopped",
                ("act-save", "act-save-success", "act-save-failure", "act-discard"),
            ),
        ):
            backend.publish(replace(backend.snapshot, state=state))
            await pilot.pause()
            for selector in (
                "#btn-estop",
                "#primary-actions",
                "#secondary-actions",
                "#sec-release",
                "#sec-quit",
                "#command",
                Footer,
                *(f"#{button_id}" for button_id in ids),
            ):
                widget = app.query_one(selector)
                assert widget.display
                assert widget.region.width > 0 and widget.region.height > 0
                assert 0 <= widget.region.x < widget.region.right <= size[0]
                assert 0 <= widget.region.y < widget.region.bottom <= size[1]
            for button_id in ids:
                assert app.query_one(f"#{button_id}").region.height == 3
            assert (
                app.query_one("#secondary-actions").region.bottom
                <= app.query_one("#menu").content_region.bottom
            )

        estop = app.query_one("#btn-estop", Button)
        assert str(estop.label) == "[e] ESTOP"
        await pilot.click(estop)
        assert backend.stops == 1


@pytest.mark.asyncio
async def test_state_transitions_focus_primary_buttons_and_keep_command_focus():
    backend = FakeBackend()
    app = OperatorApp(backend)
    async with app.run_test() as pilot:
        assert app.focused is app.query_one("#act-start")
        for state, selector in (
            ("recording", "#act-stop"),
            ("stopped", "#act-save"),
            ("estop", "#act-quit"),
        ):
            backend.publish(replace(backend.snapshot, state=state))
            await pilot.pause()
            assert app.focused is app.query_one(selector)
        assert app.query_one("#estop-notice").display
        assert not any(
            button.display for button in app.query("#secondary-actions Button")
        )
        assert [
            button.id
            for button in app.query("#primary-actions Button")
            if button.display
        ] == ["act-quit"]

        await pilot.press("ctrl+l")
        backend.publish(replace(backend.snapshot, state="hold"))
        await pilot.pause()
        assert isinstance(app.focused, CommandInput)


@pytest.mark.asyncio
async def test_refusals_appear_without_opening_logs_and_flash_available_targets():
    backend = FakeBackend()
    backend.snapshot = replace(
        backend.snapshot,
        state="recording",
        capabilities=replace(backend.snapshot.capabilities, teleop=True, handback=True),
        operations=tuple(
            replace(op, enabled=False, reason="stop an episode first")
            if op.command == "save"
            else op
            for op in backend.snapshot.operations
        )
        + (Operation("teleop", "DRIVER: POLICY", False, "leader is unaligned"),),
    )
    app = OperatorApp(backend)
    async with app.run_test() as pilot:
        await pilot.press("s")
        assert "stop an episode first" == _status_text(app, "#action-hint")
        assert app.query_one("#act-stop").has_class("flash-reject")
        assert not app.query_one("#logs").display
        assert app.query_one("#action-hint").has_class("refused")
        await pilot.press("t")
        assert "leader is unaligned" == _status_text(app, "#action-hint")
        toggle = app.query_one("#act-teleop", Button)
        assert toggle.has_class("flash-reject", "unavailable") and not toggle.disabled
        await pilot.pause(0.3)
        assert not toggle.has_class("flash-reject")
        assert "leader is unaligned" == _status_text(app, "#action-hint")
        await pilot.click(toggle)
        assert toggle.has_class("flash-reject")
        assert not backend.commands
        assert not app.query_one("#logs").display

        await pilot.press("s")
        app.query_one("#act-stop", Button).focus()
        await pilot.press("space")
        assert backend.commands == ["stop"]
        assert app.query_one("#act-stop").has_class("flash-ok")
        assert _status_text(app, "#action-hint").startswith("NEXT: ")


@pytest.mark.asyncio
async def test_teleop_toggle_and_space_shortcuts_use_current_operations():
    backend = FakeBackend()
    app = OperatorApp(backend)
    async with app.run_test() as pilot:
        for state, command, label in (
            ("hold", "teleop", "TELEOP: OFF"),
            ("teleop", "stop_teleop", "TELEOP: ON"),
            ("recording", "policy", "DRIVER: LEADER"),
        ):
            backend.publish(
                replace(
                    backend.snapshot,
                    state=state,
                    mode="record",
                    capabilities=Capabilities(teleop=True, handback=True),
                    operations=(
                        *backend.snapshot.operations,
                        Operation(command, label),
                    ),
                )
            )
            await pilot.pause()
            assert str(app.query_one("#act-teleop", Button).label) == f"[t] {label}"
            await pilot.press("t")
        assert backend.commands == ["teleop", "stop_teleop", "policy"]
        await pilot.press("space")
        app.query_one("#nodes", OptionList).focus()
        await pilot.press("space")
        assert backend.commands[-2:] == ["stop", "stop"]

        backend.publish(replace(backend.snapshot, state="hold"))
        await pilot.pause()
        await pilot.press("space")
        assert app.focused is app.query_one(CommandInput)
        assert app.query_one(CommandInput).value == "start "


@pytest.mark.asyncio
async def test_home_modal_renders_poses_and_submits_only_selected_named_pose():
    backend = FakeBackend()
    backend.snapshot = replace(
        backend.snapshot,
        capabilities=replace(backend.snapshot.capabilities, home=True),
        operations=tuple(
            Operation("home", "Home") if op.command == "home" else op
            for op in backend.snapshot.operations
        ),
        home_options=(
            HomeOption(
                "park",
                default=True,
                worst_joint="wrist",
                dist=1.2,
                eta_s=5.6,
                over_timeout=True,
            ),
            HomeOption("invalid", valid=False, reason="missing joint"),
            HomeOption("ready", worst_joint="elbow", dist=0.3, eta_s=1.2),
        ),
        home_moves="followers and leaders",
    )
    app = OperatorApp(backend)
    async with app.run_test() as pilot:
        await pilot.click("#act-home")
        modal = app.screen
        assert isinstance(modal, HomeModal)
        assert "worst joint" in str(modal.query_one("#home-columns", Static).content)
        poses = modal.query_one(OptionList)
        assert poses.highlighted == 0
        assert all(
            part in str(poses.get_option_at_index(0).prompt)
            for part in ("park (default)", "wrist", "1.2", "5.6 s", "> timeout!")
        )
        invalid = poses.get_option_at_index(1)
        assert invalid.disabled and "unavailable: missing joint" in str(invalid.prompt)
        lines = [str(widget.content) for widget in modal.query(Static)]
        assert "Moves: followers and leaders" in lines
        assert "Enter: move   Esc: cancel   e: ESTOP" in lines
        await pilot.press("down", "enter")
        assert backend.commands == ["home ready"]

        await pilot.press("h", "escape")
        assert not isinstance(app.screen, HomeModal)
        assert backend.commands == ["home ready"]
        for i, key in enumerate(("e", "ctrl+g", "f12"), 1):
            await pilot.press("h")
            assert isinstance(app.screen, HomeModal)
            await pilot.press(key)
            assert not isinstance(app.screen, HomeModal)
            assert backend.stops == i and backend.commands == ["home ready"]

        await pilot.press("ctrl+l", "h", "o", "m", "e", "enter")
        assert not isinstance(app.screen, HomeModal)
        assert backend.commands == ["home ready", "home"]


@pytest.mark.asyncio
async def test_home_shortcut_falls_back_to_direct_dispatch_without_pose_options():
    backend = FakeBackend()
    backend.snapshot = replace(
        backend.snapshot,
        operations=tuple(
            Operation("home", "Home") if op.command == "home" else op
            for op in backend.snapshot.operations
        ),
    )
    app = OperatorApp(backend)
    async with app.run_test() as pilot:
        await pilot.press("h")
        assert backend.commands == ["home"] and not isinstance(app.screen, HomeModal)


# -- splitters -----------------------------------------------------------------------


async def drag(pilot: Pilot, selector: str, dx: int = 0, dy: int = 0) -> None:
    handle = pilot.app.query_one(selector, Splitter)
    offset = (0, 1) if handle.axis == "x" else (1, 0)
    start_x, start_y = handle.region.x + offset[0], handle.region.y + offset[1]
    end = (start_x + dx, start_y + dy)
    await pilot.mouse_down(selector, offset=offset)
    await pilot.hover(offset=end)
    await pilot.mouse_up(offset=end)
    await pilot.pause()
    assert not handle.has_class("dragging")


@pytest.mark.asyncio
async def test_drag_both_axes_and_keep_sizes_across_tabs_and_resize():
    backend = FakeBackend()
    app = OperatorApp(backend)
    async with app.run_test(size=(140, 40)) as pilot:
        nodes = app.query_one("#nodes", OptionList)
        command = app.query_one(CommandInput)
        initial_width = nodes.region.width
        initial_height = app.query_one("#menu").region.height
        await drag(pilot, "#column-splitter", dx=16)
        assert nodes.region.width == initial_width + 16
        await drag(pilot, "#row-splitter", dy=4)
        assert app.query_one("#menu").region.height == initial_height - 4
        resized_width = nodes.region.width
        resized_height = app.query_one("#menu").region.height
        app.query_one(Tabs).active = "tab-3"
        await pilot.pause()
        assert not app.query_one("#column-splitter").display
        assert app.query_one("#row-splitter").display
        assert app.query_one("#menu").region.height == resized_height
        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        assert not app.query_one("#column-splitter").display
        assert app.query_one(Tabs).active == "tab-3"
        assert app.query_one("#logs").region.height >= 3
        assert app.query_one("#menu").region.bottom <= command.region.y
        app.query_one(Tabs).active = "tab-1"
        await pilot.resize_terminal(140, 40)
        await pilot.pause()
        assert nodes.region.width == resized_width
        assert app.query_one("#menu").region.height == resized_height
        # Narrow layout vertical resize for logs and operations, plus double-click reset
        await pilot.double_click("#row-splitter", offset=(1, 0))
        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        await pilot.press("ctrl+o")
        narrow_before = app.query_one("#menu").region.height
        assert narrow_before >= 10
        await drag(pilot, "#row-splitter", dy=2)
        assert app.query_one("#menu").region.height == narrow_before - 2
        assert app.query_one("#menu").region.bottom <= command.region.y
        await pilot.double_click("#row-splitter", offset=(1, 0))
        assert app.query_one("#menu").region.height == narrow_before
        assert not backend.commands and backend.stops == 0


@pytest.mark.asyncio
async def test_mouse_capture_clamps_extreme_drags_and_double_click_resets():
    backend = FakeBackend()
    app = OperatorApp(backend)
    async with app.run_test(size=(140, 40)) as pilot:
        initial_width = app.query_one("#nodes").region.width
        initial_height = app.query_one("#menu").region.height
        handle_x = app.query_one("#column-splitter").region.x
        await drag(pilot, "#column-splitter", dx=138 - handle_x)
        assert app.query_one("#details").region.width >= 30
        handle_x = app.query_one("#column-splitter").region.x
        await drag(pilot, "#column-splitter", dx=-handle_x)
        assert app.query_one("#nodes").region.width == 20
        await pilot.double_click("#column-splitter", offset=(0, 1))
        assert app.query_one("#nodes").region.width == initial_width
        handle_y = app.query_one("#row-splitter").region.y
        await drag(pilot, "#row-splitter", dy=37 - handle_y)
        assert app.query_one("#menu").region.height == 8
        handle_y = app.query_one("#row-splitter").region.y
        await drag(pilot, "#row-splitter", dy=1 - handle_y)
        assert app.query_one("#nodes").region.height == 3
        await pilot.double_click("#row-splitter", offset=(1, 0))
        assert app.query_one("#menu").region.height == initial_height
        assert not backend.commands and backend.stops == 0


@pytest.mark.asyncio
async def test_keyboard_resize_and_emergency_stop_during_drag():
    backend = FakeBackend()
    app = OperatorApp(backend)
    async with app.run_test(size=(120, 35)) as pilot:
        app.query_one("#column-splitter").focus()
        before = app.query_one("#nodes").region.width
        await pilot.press("right", "right")
        assert app.query_one("#nodes").region.width == before + 2
        await pilot.press("ctrl+r")
        assert app.query_one("#nodes").region.width == before
        await pilot.mouse_down("#row-splitter", offset=(1, 0))
        await pilot.press("ctrl+g")
        assert backend.stops == 1
        await pilot.press("ctrl+q")
        assert isinstance(app.screen, Confirmation)
        assert not app.query_one("#row-splitter").has_class("dragging")
        await pilot.press("escape")
        assert not backend.choices
        await pilot.mouse_down("#column-splitter", offset=(0, 1))
        await pilot.press("escape")
        assert not app.query_one("#column-splitter").has_class("dragging")


# -- dora integration ----------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_textual_records_and_saves_a_mock_episode(tmp_path: Path):
    project = mock_project(tmp_path / ".roboloom")
    backend = SessionBackend(
        lambda: Session.launch(project / "config.yaml", screen=False, operator=None),
        mode="record",
        recording=RecordingPlan("Pilot collection", 0.6),
    )
    app = OperatorApp(backend)
    async with app.run_test(size=(80, 24)) as pilot:
        deadline = time.monotonic() + 40
        while not any(
            o.command == "start" and o.enabled for o in app.snapshot.operations
        ):
            assert time.monotonic() < deadline, app.snapshot
            await asyncio.sleep(0.1)
        await pilot.press("enter")
        deadline = time.monotonic() + 40
        while app.snapshot.phase != "complete":
            assert time.monotonic() < deadline, app.snapshot
            await asyncio.sleep(0.1)
        assert len(app.screen_stack) == 2
        assert backend.session is not None
        assert backend.session.screen is None and backend.session.operator is None
        assert app.query_one(CommandInput).history == []
        await pilot.press("down", "enter")
        deadline = time.monotonic() + 20
        while backend.session.alive:
            assert time.monotonic() < deadline
            await asyncio.sleep(0.1)
    assert backend.session.episodes == 1  # quit drains the accepted save
    assert not (project / "config.fifo").exists()
