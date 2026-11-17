"""Public hook declarations and the lazily read per-call context."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from functools import cached_property
from typing import Any, Literal

import numpy as np

from .events import Event

HOOKS_API = 1
Source = Literal["policy", "teleop"]
Scalar = str | int | float | bool | None


@dataclass(frozen=True)
class Requirements:
    """Resources a hook needs. Future API additions have defaults."""

    observe: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    sources: tuple[str, ...] = ("policy",)
    on_error: str | None = None
    budget_ms: float | None = None
    api: int = HOOKS_API


@dataclass(frozen=True)
class HookSpec:
    """The node's action layout and features of its observed sources only."""

    names: tuple[str, ...]
    units: tuple[str, ...]
    hold: tuple[str, ...]
    observation: Mapping[str, Mapping[str, Any]]
    rate_hz: float
    command_hz: float
    dataset_fps: float
    sources: tuple[str, ...]
    api: int = HOOKS_API


class Hook:
    """Optional methods: requirements, bind, step, on_event and close.

    A step implementation accepts ``(action: np.ndarray, ctx: StepContext)`` and
    returns an array or None (unchanged). Event handlers run on a per-hook worker.
    """

    def requirements(self) -> Requirements:
        return Requirements()

    def bind(self, spec: HookSpec) -> None:
        """Raise ConfigError to refuse the node's configuration."""

    def on_event(self, event: Event) -> None:
        """Route an event to the optional ``on_<kind>(event)`` method."""
        handler = getattr(self, f"on_{event.kind}", None)
        if callable(handler):
            handler(event)

    def close(self) -> None:
        """Release hook-owned resources after draining the event queue."""


def readonly(array: np.ndarray) -> np.ndarray:
    """An isolated read-only snapshot, without freezing the producer's array."""
    out = array.copy()
    out.flags.writeable = False
    return out


class _Observation(Mapping[str, Any]):
    def __init__(self, keys: tuple[str, ...], load: Callable[[], Mapping[str, Any]]):
        self.allowed = keys
        self.load = load

    def __getitem__(self, key: str) -> Any:
        if key not in self.allowed:
            raise KeyError(f"{key!r} was not declared in hook requirements.observe")
        value = self.load()[key]
        return readonly(value) if isinstance(value, np.ndarray) else value

    def __iter__(self) -> Iterator[str]:
        return iter(self.allowed)

    def __len__(self) -> int:
        return len(self.allowed)


@dataclass
class StepContext:
    """One step invocation; snapshots and observations are built only when read.

    ``previous`` is the last command sent, ``held`` the follower's current target,
    and ``state`` its measured position. Arrays and observations are read-only.
    ``note`` accepts up to 16 small scalar fields, retained in this hook's stats.
    """

    source: Source
    step: int
    t_ns: int
    rate_hz: float
    task: str
    episode_index: int | None
    names: tuple[str, ...]
    chunk: ChunkPosition | None = None
    _held: Callable[[], np.ndarray] = field(default=lambda: np.empty(0), repr=False)
    _previous: Callable[[], np.ndarray] = field(default=lambda: np.empty(0), repr=False)
    _state: Callable[[], np.ndarray] = field(default=lambda: np.empty(0), repr=False)
    _observation: Callable[[], Mapping[str, Any]] = field(default=dict, repr=False)
    _observe: tuple[str, ...] = field(default=(), repr=False)
    _hold: tuple[str, ...] = field(default=(), repr=False)
    _writes: tuple[str, ...] = field(default=(), repr=False)
    _notes: dict[str, Scalar] = field(default_factory=dict, repr=False)

    def index(self, name: str) -> int:
        return self.names.index(name)

    @cached_property
    def held(self) -> np.ndarray:
        return readonly(self._held())

    @cached_property
    def previous(self) -> np.ndarray:
        return readonly(self._previous())

    @cached_property
    def state(self) -> np.ndarray:
        return readonly(self._state())

    @cached_property
    def hold_mask(self) -> np.ndarray:
        return readonly(np.asarray([n in self._hold for n in self.names], dtype=bool))

    @cached_property
    def writable_mask(self) -> np.ndarray:
        return readonly(np.asarray([n in self._writes for n in self.names], dtype=bool))

    @cached_property
    def observation(self) -> Mapping[str, Any]:
        return _Observation(self._observe, self._observation)

    def note(self, **fields: Scalar) -> None:
        if len(self._notes.keys() | fields.keys()) > 16 or any(
            not isinstance(v, (str, int, float, bool, type(None)))
            or (isinstance(v, str) and len(v) > 256)
            or (isinstance(v, float) and not np.isfinite(v))
            or len(k) > 64
            for k, v in fields.items()
        ):
            raise ValueError("hook notes must be at most 16 small finite scalar fields")
        self._notes.update(fields)

    def for_hook(
        self, requirements: Requirements, notes: dict[str, Scalar]
    ) -> StepContext:
        return replace(
            self,
            _observe=requirements.observe,
            _writes=requirements.writes,
            _notes=notes,
        )


@dataclass(frozen=True)
class ChunkPosition:
    id: int
    position: int
    length: int
