"""Mouse and keyboard splitter handles; no experiment operations live here."""

from __future__ import annotations

from typing import ClassVar, Literal

from textual import events
from textual.binding import Binding, BindingType
from textual.message import Message
from textual.widget import Widget


class Splitter(Widget, can_focus=True):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+r", "reset", show=False),
        Binding("home", "reset", show=False),
        Binding("escape", "cancel_drag", show=False),
    ]
    DEFAULT_CSS = """
    Splitter { color: $primary; background: $boost; }
    Splitter.vertical { width: 1; height: 1fr; }
    Splitter.horizontal { width: 1fr; height: 1; }
    Splitter:hover, Splitter:focus, Splitter.dragging { background: $primary; color: $text; }
    """

    class Moved(Message):
        def __init__(self, splitter: Splitter, delta: int) -> None:
            super().__init__()
            self.splitter, self.delta = splitter, delta

    class Reset(Message):
        def __init__(self, splitter: Splitter) -> None:
            super().__init__()
            self.splitter = splitter

    def __init__(self, axis: Literal["x", "y"], *, id: str) -> None:
        super().__init__(id=id, classes="vertical" if axis == "x" else "horizontal")
        self.axis = axis
        self._pointer: int | None = None
        self.tooltip = "Drag to resize · double-click / Ctrl-R to reset · arrows adjust when focused"

    def render(self) -> str:
        if self.axis == "x":
            return "\n".join("│" for _ in range(max(1, self.size.height)))
        return "─" * max(1, self.size.width)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button != 1:
            return
        self._pointer = event.screen_x if self.axis == "x" else event.screen_y
        self.capture_mouse()
        self.add_class("dragging")
        self.focus()
        event.stop()
        event.prevent_default()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._pointer is None:
            return
        position = event.screen_x if self.axis == "x" else event.screen_y
        delta = position - self._pointer
        self._pointer = position
        if delta:
            self.post_message(self.Moved(self, delta))
        event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._pointer is not None:
            self.action_cancel_drag()
            event.stop()

    def on_mouse_release(self, event: events.MouseRelease) -> None:
        self._pointer = None
        self.remove_class("dragging")

    def on_hide(self) -> None:
        self.action_cancel_drag()

    def on_unmount(self) -> None:
        self.action_cancel_drag()

    def on_click(self, event: events.Click) -> None:
        if event.chain == 2:
            self.action_reset()
        event.stop()

    def action_cancel_drag(self) -> None:
        if self._pointer is not None:
            self._pointer = None
            self.release_mouse()
        self.remove_class("dragging")

    def action_reset(self) -> None:
        self.action_cancel_drag()
        self.post_message(self.Reset(self))

    def on_key(self, event: events.Key) -> None:
        keys = {"left": -1, "right": 1} if self.axis == "x" else {"up": -1, "down": 1}
        delta = keys.get(event.key)
        if delta is not None:
            self.post_message(self.Moved(self, delta))
            event.stop()
