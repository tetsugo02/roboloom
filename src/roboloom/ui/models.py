"""Terminal-independent contracts for operator backends and presenters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol

type Value = str | int | float | bool | None | list["Value"] | dict[str, "Value"]
Confirmation = Literal["release", "quit", "tuning-quit"]


@dataclass(frozen=True)
class Operation:
    command: str
    label: str
    enabled: bool = True
    reason: str = ""
    confirmation: Confirmation | None = None


@dataclass(frozen=True)
class Capabilities:
    home: bool = False
    release: bool = False
    hold: bool = False
    gravity: bool = False


@dataclass(frozen=True)
class NodeSnapshot:
    name: str
    role: str
    kind: str = ""
    level: str = "ok"
    age_s: float = 0.0
    fields: Mapping[str, Value] = field(default_factory=dict)
    t_ns: int = 0


@dataclass(frozen=True)
class Snapshot:
    title: str
    mode: str
    phase: str
    nodes: tuple[NodeSnapshot, ...] = ()
    operations: tuple[Operation, ...] = ()
    capabilities: Capabilities = Capabilities()
    warning: str = ""
    selected: str = ""
    dirty: bool = False


@dataclass(frozen=True)
class LogEvent:
    text: str
    level: str = "info"
    style: str = ""  # rich style; empty: from the level


@dataclass(frozen=True)
class Closed:
    outcome: str = "done"


Notice = Snapshot | LogEvent | Closed
Publish = Callable[[Notice], None]


class Backend(Protocol):
    """No Textual types and no device handles cross this boundary."""

    def start(self, publish: Publish) -> None: ...
    def submit(self, command: str) -> None: ...
    def emergency(self) -> None: ...
    def request_close(self, choice: str) -> None: ...
    def shutdown(self) -> None:
        """Cancel, join real threads and close resources; safe more than once."""
        ...
