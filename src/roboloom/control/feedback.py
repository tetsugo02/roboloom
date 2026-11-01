"""Force feedback a leader receives from its controller (see `roboloom.controllers.feedback`)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FeedbackCommand:
    effort_mA: dict[int, float] = field(
        default_factory=dict
    )  # device joint index -> mA
    gate: bool = False  # the controller wants the feedback applied
    deadline_ns: int = 0  # applied only until then
