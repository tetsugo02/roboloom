"""Force feedback a leader receives from its controller (see `roboloom.controllers.feedback`).

`FeedbackTerm` is the part of a current-mode law (`feedback:` in its group) that adds
the received current. Each tick the gate moves toward 1 while the controller asks for
it and the message is within its deadline, else toward 0, at `dt / ramp_s`; it never
jumps. The added current is `gate * (clip(effort, +-max_mA) - kd * velocity)`, before
the law's own `max_current_mA` clip.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass
class FeedbackCommand:
    effort_mA: dict[int, float] = field(
        default_factory=dict
    )  # device joint index -> mA
    gate: bool = False  # the controller wants the feedback applied
    deadline_ns: int = 0  # applied only until then


class FeedbackTerm:
    def __init__(
        self,
        joints: Sequence[int],
        max_mA: Sequence[float],
        ramp_s: float,
        kd: Sequence[float],
    ):
        self.joints = list(joints)
        self.max_mA, self.kd = list(max_mA), list(kd)  # per joint of the law
        self.ramp_s = ramp_s
        self.reset()

    def reset(self) -> None:
        """Closed and empty (torque off, estop, a failure)."""
        self.gate = 0.0
        self.command = FeedbackCommand()
        self.last_mA: dict[int, float] = {}

    def set(self, command: FeedbackCommand) -> None:
        self.command = FeedbackCommand(
            {i: v for i, v in command.effort_mA.items() if i in self.joints},
            command.gate,
            command.deadline_ns,
        )

    def advance(self, now_ns: int, dt: float) -> None:
        """Move the gate one tick toward open (wanted and in time) or closed."""
        want = self.command.gate and now_ns <= self.command.deadline_ns
        step = max(0.0, dt) / self.ramp_s
        self.gate = min(1.0, self.gate + step) if want else max(0.0, self.gate - step)

    def mA(self, k: int, velocity: float) -> float:
        """Current added to the law's joint `k` (position in the law's joints)."""
        i = self.joints[k]
        effort = self.command.effort_mA.get(i, 0.0)
        limit = self.max_mA[k]
        value = self.gate * (max(-limit, min(limit, effort)) - self.kd[k] * velocity)
        self.last_mA[i] = value
        return value
