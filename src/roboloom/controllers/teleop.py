"""Which teleoperation a configuration supports, decided from its controllers alone.

- A policy with `teleop:` (`TeleopMode.policy` names it): the operator takes the
  followers over from the policy and hands them back, before or during an episode (an
  intervention, recorded as `action.intervention`).
- Every controller follows an operator input (`Controller.follows_operator()`: `joint`,
  `pose_ik`, `parts` of those, or a user's controller): `teleop` arms the followers
  outside an episode, so they follow the input as they do while recording, and nothing
  is recorded; `stop_teleop` holds them, `start` records from there.

Any other configuration has no teleoperation. The runtime, the operator screens and the
recording schema all ask `teleop_mode`, so the rule holds for every robot.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .base import Controller


@dataclass(frozen=True)
class TeleopMode:
    """The teleoperation a configuration supports (see the module docstring)."""

    policy: str | None  # policy with `teleop:`, or None for operator teleop

    @property
    def handback(self) -> bool:
        """The followers go back to the policy (`policy`), and teleop works during an
        episode too."""
        return self.policy is not None


def teleop_mode(controllers: Mapping[str, Controller]) -> TeleopMode | None:
    """The configuration's teleoperation, or None when it has none."""
    for name, c in controllers.items():
        if getattr(c, "teleop", None):
            return TeleopMode(policy=name)
    if controllers and all(c.follows_operator() for c in controllers.values()):
        return TeleopMode(policy=None)
    return None
