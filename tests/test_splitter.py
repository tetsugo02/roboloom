"""Exercise actual mouse capture and layout changes through Textual Pilot."""

from __future__ import annotations

import pytest
from test_textual_ui import FakeBackend
from textual.pilot import Pilot
from textual.widgets import OptionList, Tabs

from roboloom.ui.app import Confirmation, OperatorApp
from roboloom.ui.command import CommandInput
from roboloom.ui.splitter import Splitter


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
async def test_drag_both_axes_and_keep_sizes_selection_and_draft_across_tabs_and_resize():
    backend = FakeBackend()
    app = OperatorApp(backend)
    async with app.run_test(size=(140, 40)) as pilot:
        nodes = app.query_one("#nodes", OptionList)
        nodes.highlighted = 1
        command = app.query_one(CommandInput)
        command.value = "start 日本語 draft"
        await pilot.pause()
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
        assert app.query_one(Tabs).active == "tab-3"
        assert app.query_one("#menu").region.bottom <= command.region.y
        assert app.query_one("#logs").region.height >= 3
        app.query_one(Tabs).active = "tab-1"
        await pilot.resize_terminal(140, 40)
        await pilot.pause()
        assert nodes.region.width == resized_width
        assert app.query_one("#menu").region.height == resized_height
        assert nodes.highlighted == 1
        assert command.value == "start 日本語 draft"
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
        assert app.query_one("#menu").region.height == 6
        handle_y = app.query_one("#row-splitter").region.y
        await drag(pilot, "#row-splitter", dy=1 - handle_y)
        assert app.query_one("#nodes").region.height == 3
        await pilot.double_click("#row-splitter", offset=(1, 0))
        assert app.query_one("#menu").region.height == initial_height
        assert not backend.commands and backend.stops == 0


@pytest.mark.asyncio
async def test_keyboard_resize_and_emergency_stop_during_drag_and_dialog():
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
        await pilot.press("ctrl+g")
        assert backend.stops == 2
        await pilot.press("escape")
        assert not backend.choices
        await pilot.mouse_down("#column-splitter", offset=(0, 1))
        await pilot.press("escape")
        assert not app.query_one("#column-splitter").has_class("dragging")


@pytest.mark.asyncio
async def test_narrow_layout_has_vertical_resize_for_logs_and_operations():
    app = OperatorApp(FakeBackend())
    async with app.run_test(size=(80, 24)) as pilot:
        assert not app.query_one("#column-splitter").display
        assert app.query_one("#menu").region.height >= 10
        await pilot.press("ctrl+o")
        before = app.query_one("#menu").region.height
        await drag(pilot, "#row-splitter", dy=2)
        assert app.query_one("#menu").region.height == before - 2
        assert (
            app.query_one("#menu").region.bottom <= app.query_one("#command").region.y
        )
        await pilot.double_click("#row-splitter", offset=(1, 0))
        assert app.query_one("#menu").region.height == before
