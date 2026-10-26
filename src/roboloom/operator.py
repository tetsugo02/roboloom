"""How setup steps talk to the person at the robot.

Library code never calls `input` or `print`; it asks an `Operator`. The CLI passes a
`TerminalOperator`; scripts and tests pass a `ScriptedOperator` with the answers.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol


class Operator(Protocol):
    def confirm(self, message: str) -> bool:
        """Ask before torquing a motor or writing EEPROM; False cancels."""
        ...

    def prompt(self, message: str) -> str:
        """Wait until the operator is ready (e.g. the arm is in a pose); returns what they typed."""
        ...

    def notify(self, message: str) -> None:
        """One line of information, e.g. "let go now"."""
        ...

    def progress(self, message: str) -> None:
        """A live line that replaces the previous one, e.g. spans while measuring travel."""
        ...

    def finished(self) -> bool:
        """Non-blocking: has the operator ended an open-ended step (Enter in a terminal)?"""
        ...


class TerminalOperator:
    def confirm(self, message: str) -> bool:
        return input(f"{message} Type yes to continue: ").strip() == "yes"

    def prompt(self, message: str) -> str:
        return input(message).strip()

    def notify(self, message: str) -> None:
        print(message, flush=True)

    def progress(self, message: str) -> None:
        print(f"\r{message}   ", end="", flush=True)

    def finished(self) -> bool:
        import select
        import sys

        if not select.select([sys.stdin], [], [], 0)[0]:
            return False
        sys.stdin.readline()
        print()
        return True


class ScriptedOperator:
    """Answers given up front. `prompts` are returned in order (then ""); `finish_after`
    is how many `finished` polls return False first. Every message is kept in `log`."""

    def __init__(
        self, confirm: bool = True, prompts: Iterable[str] = (), finish_after: int = 0
    ):
        self.answer = confirm
        self.prompts = list(prompts)
        self.polls_left = finish_after
        self.log: list[str] = []

    def confirm(self, message: str) -> bool:
        self.log.append(message)
        return self.answer

    def prompt(self, message: str) -> str:
        self.log.append(message)
        return self.prompts.pop(0) if self.prompts else ""

    def notify(self, message: str) -> None:
        self.log.append(message)

    def progress(self, message: str) -> None:
        pass

    def finished(self) -> bool:
        self.polls_left -= 1
        return self.polls_left < 0
