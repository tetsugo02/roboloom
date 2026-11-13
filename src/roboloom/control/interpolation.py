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

`method="pchip"` replaces the straight line by a monotone cubic (Fritsch-Carlson): the
targets still pass through every action at its own time, so nothing lags behind the
line, and they never leave the range between two consecutive actions (no overshoot),
but the speed no longer jumps at each action. It needs the action after the one being
approached (`next`), which the caller takes from its queue; without it (the end of a
chunk) the segment ends at the line's slope.
"""

from __future__ import annotations

import math

import numpy as np


def whole_hz(hz: float) -> bool:
    """Whether `hz` is a whole number of Hz (dora timers take whole Hz)."""
    return abs(hz - round(hz)) < 1e-9


def auto_multiplier(rate_hz: float, control_hz: float) -> int:
    """The largest N with `rate_hz * N` whole Hz and at most `control_hz` (the slowest
    follower's control rate): the commands come as often as the followers can take
    them. 1 when no N fits (e.g. a policy rate that is not whole Hz)."""
    for n in range(max(1, math.floor(control_hz / rate_hz + 1e-9)), 1, -1):
        if whole_hz(rate_hz * n):
            return n
    return 1


METHODS = ("linear", "pchip")


def _end_slope(before: np.ndarray, after: np.ndarray) -> np.ndarray:
    """The slope at an action between the differences to its neighbours: their harmonic
    mean where both point the same way, zero at a turning point (Fritsch-Carlson)."""
    same = before * after > 0
    total = np.where(same, before + after, 1.0)
    return np.where(same, 2 * before * after / total, 0.0)


def _monotone(slope: np.ndarray, difference: np.ndarray) -> np.ndarray:
    """`slope` limited so the cubic over `difference` stays between its ends."""
    kept = np.where(slope * difference > 0, slope, 0.0)
    return np.sign(difference) * np.minimum(np.abs(kept), 3 * np.abs(difference))


class ActionInterpolator:
    def __init__(self, multiplier: int = 1, method: str = "linear"):
        if isinstance(multiplier, bool) or not isinstance(multiplier, int):
            raise TypeError(f"multiplier must be an integer, got {multiplier!r}")
        if multiplier < 1:
            raise ValueError(f"multiplier must be >= 1, got {multiplier}")
        if method not in METHODS:
            raise ValueError(f"method must be one of {METHODS}, got {method!r}")
        self.multiplier, self.method = multiplier, method
        self._slope: np.ndarray | None = None  # per action period, at the last action
        self._prev: np.ndarray | None = None
        self._buffer: list[np.ndarray] = []
        self._idx = 0

    def reset(self) -> None:
        """Forget the previous action (at every episode start)."""
        self._prev = None
        self._slope = None
        self._buffer = []
        self._idx = 0

    def needs_new_action(self) -> bool:
        return self._idx >= len(self._buffer)

    def add(
        self,
        action: np.ndarray,
        previous: np.ndarray | None = None,
        next: np.ndarray | None = None,  # the action after this one
    ) -> None:
        """Queue the steps toward `action`. `previous` stands in for the previous action
        when there is none yet (after `reset`); it is ignored otherwise. `next` is the
        action that will follow, when known (used by `pchip`)."""
        action = np.asarray(action, dtype=np.float64)
        start = self._prev
        if start is None and previous is not None:
            start = np.asarray(previous, dtype=np.float64)
            if start.shape != action.shape:
                raise ValueError(
                    f"previous has shape {start.shape}, the action {action.shape}"
                )
        if self.multiplier > 1 and start is not None and self.method == "pchip":
            difference = action - start
            # leaving: the slope the last segment arrived with (at rest after a reset)
            leaving = _monotone(
                np.zeros_like(action) if self._slope is None else self._slope,
                difference,
            )
            arriving = _monotone(
                difference
                if next is None
                else _end_slope(
                    difference, np.asarray(next, dtype=np.float64) - action
                ),
                difference,
            )
            self._buffer = []
            for i in range(1, self.multiplier + 1):
                t = i / self.multiplier
                self._buffer.append(
                    (2 * t**3 - 3 * t**2 + 1) * start
                    + (t**3 - 2 * t**2 + t) * leaving
                    + (-2 * t**3 + 3 * t**2) * action
                    + (t**3 - t**2) * arriving
                )
            self._buffer[-1] = action.copy()
            self._slope = arriving
        elif self.multiplier > 1 and start is not None:
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
