"""Demo policy for the mock: swings joint1 and joint4 of each arm and opens and closes
the grippers, whatever the task. Not for hardware."""

import math
import time

import numpy as np


class Wave:
    def __init__(self, amplitude: float = 0.4, period_s: float = 8.0, horizon: int = 2):
        self.amplitude, self.omega, self.horizon = (
            amplitude,
            2 * math.pi / period_s,
            horizon,
        )
        self.t0 = time.monotonic()

    def reset(self) -> None:
        self.t0 = time.monotonic()

    def infer(self, observation: dict) -> np.ndarray:
        state = np.asarray(observation["observation.state"], dtype=float)
        if state.shape != (14,):
            raise ValueError(
                f"expected 2 PiPER + 2 grippers (14 joints), got {state.shape}"
            )
        chunk = np.repeat(state[None, :], self.horizon, axis=0)
        t = time.monotonic() - self.t0
        for k in range(self.horizon):
            s = math.sin(self.omega * (t + 0.1 * (k + 1)))
            for arm in (0, 6):  # left, right: joint1 and joint4
                chunk[k, arm] = self.amplitude * s
                chunk[k, arm + 3] = -self.amplitude * s
            chunk[k, 12] = 0.7 + 0.5 * s  # left_gripper
            chunk[k, 13] = 0.7 - 0.5 * s  # right_gripper
        return chunk


def wave(**kwargs) -> Wave:
    return Wave(**kwargs)
