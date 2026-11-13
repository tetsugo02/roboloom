"""Policy actions at the control rate: `interpolation_multiplier` of `type: policy`.

The same scheme as LeRobot's rollout (`lerobot.utils.action_interpolator`): the control
loop runs `multiplier` times faster than the policy's action rate, asks for a new action
once every `multiplier` ticks and sends the straight line from the previous action to
it in `multiplier` equal steps, so the follower reaches each action one action period
after it was produced.

One difference: LeRobot sends the very first action of an episode unchanged (it has no
previous action). Here the caller may give the pose the follower holds as the previous
action, so the first step is a ramp too. Without it the result is LeRobot's.

The action queue (the chunk a policy returned) stays outside this class, so a different
queue (e.g. real-time chunking) can feed the same interpolation.
"""

from __future__ import annotations

import numpy as np


class ActionInterpolator:
    def __init__(self, multiplier: int = 1):
        if isinstance(multiplier, bool) or not isinstance(multiplier, int):
            raise TypeError(f"multiplier must be an integer, got {multiplier!r}")
        if multiplier < 1:
            raise ValueError(f"multiplier must be >= 1, got {multiplier}")
        self.multiplier = multiplier
        self._prev: np.ndarray | None = None
        self._buffer: list[np.ndarray] = []
        self._idx = 0

    def reset(self) -> None:
        """Forget the previous action (at every episode start)."""
        self._prev = None
        self._buffer = []
        self._idx = 0

    def needs_new_action(self) -> bool:
        return self._idx >= len(self._buffer)

    def add(self, action: np.ndarray, previous: np.ndarray | None = None) -> None:
        """Queue the steps toward `action`. `previous` stands in for the previous action
        when there is none yet (after `reset`); it is ignored otherwise."""
        action = np.asarray(action, dtype=np.float64)
        start = self._prev
        if start is None and previous is not None:
            start = np.asarray(previous, dtype=np.float64)
            if start.shape != action.shape:
                raise ValueError(
                    f"previous has shape {start.shape}, the action {action.shape}"
                )
        if self.multiplier > 1 and start is not None:
            self._buffer = [
                start + (i / self.multiplier) * (action - start)
                for i in range(1, self.multiplier + 1)
            ]
        else:
            self._buffer = [action.copy()]
        self._prev = action.copy()
        self._idx = 0

    def get(self) -> np.ndarray | None:
        """The next step, or None when a new action is needed."""
        if self._idx >= len(self._buffer):
            return None
        out = self._buffer[self._idx]
        self._idx += 1
        return out
