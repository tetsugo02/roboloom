"""Taking a follower over from where it is held, joint by joint (`JointPickup`).

When an operator takes over a follower that something else moved (a policy), the leader
is usually elsewhere. Rather than waiting until every joint is aligned, each joint stays
held until the leader's mapped value for it comes within `tolerance` of the held value or
crosses it; from then on that joint follows the leader. A gripper therefore stays closed
until the operator squeezes the trigger to where the gripper is.
"""

from __future__ import annotations

from collections.abc import Sequence


class JointPickup:
    def __init__(self, held: Sequence[float], tolerance: float):
        self.held = [float(x) for x in held]
        self.tolerance = float(tolerance)
        self.caught = [False] * len(self.held)
        self.previous: list[float] | None = None
        # signed target - held of the joints not caught yet (0 once caught)
        self.remaining = [0.0] * len(self.held)

    @property
    def done(self) -> bool:
        return all(self.caught)

    def apply(self, target: Sequence[float]) -> list[float]:
        """`target` (the leader mapped onto the follower) with every joint not caught yet
        replaced by its held value."""
        if len(target) != len(self.held):
            raise ValueError(
                f"pickup: {len(target)} joints, {len(self.held)} held values"
            )
        out = []
        for i, (t, h) in enumerate(zip(target, self.held, strict=True)):
            if not self.caught[i]:
                crossed = (
                    self.previous is not None and (self.previous[i] - h) * (t - h) <= 0
                )
                self.caught[i] = abs(t - h) <= self.tolerance or crossed
            self.remaining[i] = 0.0 if self.caught[i] else float(t) - h
            out.append(float(t) if self.caught[i] else h)
        self.previous = [float(x) for x in target]
        return out
