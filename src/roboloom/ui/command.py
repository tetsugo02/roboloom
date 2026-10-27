"""Textual line editing with ephemeral history and command-name completion."""

from __future__ import annotations

from typing import ClassVar

from textual import events
from textual.binding import Binding, BindingType
from textual.message import Message
from textual.widgets import Input


class CommandInput(Input):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "history(-1)", show=False),
        Binding("down", "history(1)", show=False),
        Binding("tab", "complete(1)", show=False),
        Binding("shift+tab", "complete(-1)", show=False),
        Binding("escape", "cancel_completion", show=False),
    ]

    class Candidates(Message):
        def __init__(self, text: str):
            super().__init__()
            self.text = text

    def __init__(self) -> None:
        super().__init__(
            placeholder="roboloom> command", id="command", select_on_focus=False
        )
        self.commands: tuple[str, ...] = ()
        self.history: list[str] = []
        self._history_index = 0
        self._draft = ""
        self._candidates: list[str] = []
        self._candidate_index = -1
        self._completion_base = ""

    def action_history(self, direction: int) -> None:
        self.action_cancel_completion()
        if self._history_index == len(self.history):
            self._draft = self.value
        self._history_index = min(
            len(self.history), max(0, self._history_index + direction)
        )
        self.value = (
            self._draft
            if self._history_index == len(self.history)
            else self.history[self._history_index]
        )
        self.cursor_position = len(self.value)

    def action_complete(self, direction: int) -> None:
        if not self._candidates:
            if " " in self.value.strip():
                return
            self._completion_base = self.value
            self._candidates = [c for c in self.commands if c.startswith(self.value)]
            self._candidate_index = -1 if direction > 0 else 0
        if not self._candidates:
            return
        self._candidate_index = (self._candidate_index + direction) % len(
            self._candidates
        )
        self.value = self._candidates[self._candidate_index]
        self.cursor_position = len(self.value)
        self.post_message(
            self.Candidates(
                "  ".join(
                    ("> " if i == self._candidate_index else "") + c
                    for i, c in enumerate(self._candidates)
                )
            )
        )

    def action_cancel_completion(self) -> None:
        if self._candidates:
            self.value = self._completion_base
            self.cursor_position = len(self.value)
        self._clear_candidates()

    def _clear_candidates(self) -> None:
        self._candidates.clear()
        self.post_message(self.Candidates(""))

    async def action_submit(self) -> None:
        if self._candidates:
            self._clear_candidates()
            return
        line = self.value.strip()
        if line:
            if not self.history or self.history[-1] != line:
                self.history.append(line)
            self._history_index = len(self.history)
            self._draft = ""
            await super().action_submit()
            self.value = ""

    async def _on_key(self, event: events.Key) -> None:
        if event.key not in ("tab", "shift+tab", "enter", "escape"):
            self._clear_candidates()
        # Textual dispatches the base handler after this one.

    def _on_paste(self, event: events.Paste) -> None:
        event.prevent_default()
        self._clear_candidates()
        # Textual's default Input keeps only the first pasted line.
        line = " ".join(event.text.splitlines())
        self.replace(line, *self.selection)
        event.stop()
