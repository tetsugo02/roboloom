"""Terminal-independent contracts for operator backends and presenters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol

type Value = str | int | float | bool | None | list["Value"] | dict[str, "Value"]
Confirmation = Literal["release", "quit", "tuning-quit"]
OperatorState = Literal[
    "launching",
    "hold",
    "teleop",
    "recording",
    "stopped",
    "homing",
    "estop",
    "fault",
    "complete",
    "",
]


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
    hold: bool = False  # some follower keeps holding after quit
    # operator input can drive the followers outside an episode
    teleop: bool = False
    handback: bool = False  # take over from and hand back to a policy
    torqued: bool = False  # some follower has torque: quit may release it
    gravity: bool = False
    reselect: bool = False  # quit can come back to the launcher's option choice
    # what to do before release and quit, from the devices' safety traits (core.traits)
    release_note: str = ""
    quit_note: str = ""  # what goes limp when the session ends without release


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
class HomeOption:
    name: str
    default: bool = False
    valid: bool = True
    reason: str = ""
    worst_joint: str = ""
    dist: float | None = None
    eta_s: float | None = None
    over_timeout: bool = False


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
    state: OperatorState = ""
    control: str = ""
    episode: str = ""
    task: str = ""
    elapsed_s: float | None = None
    duration_s: float | None = None
    rows: int | None = None
    step: int | None = None
    steps: int | None = None
    saved_episodes: int = 0
    pending_saves: int = 0
    alignment: str = ""
    home_options: tuple[HomeOption, ...] = ()
    home_moves: str = ""


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
