"""Immutable, JSON-safe lifecycle events delivered in order to each hook."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

EndReason = Literal[
    "stopped", "discarded", "failed", "estop", "released", "interrupted", "shutdown"
]


@dataclass(frozen=True)
class EpisodeStarted:
    task: str
    episode_index: int | None
    dataset_root: str | None
    started_at: float
    kind: str = field(default="episode_started", init=False)


@dataclass(frozen=True)
class EpisodeEnded:
    task: str
    reason: EndReason
    error: str
    episode_index: int | None
    dataset_root: str | None
    steps: int
    commands: int
    interventions: int
    intervention_s: float
    filtered_steps: int
    started_at: float
    duration_s: float
    kind: str = field(default="episode_ended", init=False)


@dataclass(frozen=True)
class ControlChanged:
    previous: str
    current: str
    reason: Literal["takeover", "handback"]
    kind: str = field(default="control_changed", init=False)


@dataclass(frozen=True)
class PolicyRestarted:
    reason: Literal["handback", "stale_recovered"]
    kind: str = field(default="policy_restarted", init=False)


@dataclass(frozen=True)
class ObservationStale:
    sources: tuple[str, ...]
    kind: str = field(default="observation_stale", init=False)


Event = (
    EpisodeStarted | EpisodeEnded | ControlChanged | PolicyRestarted | ObservationStale
)
EVENTS: dict[str, type[Event]] = {
    "episode_started": EpisodeStarted,
    "episode_ended": EpisodeEnded,
    "control_changed": ControlChanged,
    "policy_restarted": PolicyRestarted,
    "observation_stale": ObservationStale,
}
BARRIERS = {"episode_started", "control_changed", "policy_restarted"}
