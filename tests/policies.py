"""Policies the dataflow tests load by reference ("policies:creep"); tests/ is on PYTHONPATH."""

import numpy as np


class Creep:
    """Moves the first joint up by `step` counts per action, in chunks of `horizon`."""

    def __init__(self, step: float = 5.0, horizon: int = 4):
        self.step, self.horizon = step, horizon
        self.seen: set[str] = set()

    def reset(self) -> None:
        pass

    def infer(self, observation: dict) -> np.ndarray:
        missing = {"observation.state", "observation.images.camera", "task"} - set(
            observation
        )
        if missing or observation["task"] != "creep":
            raise ValueError(f"unexpected observation: missing {missing}")
        state = np.asarray(observation["observation.state"], dtype=float)
        chunk = np.repeat(state[None, :], self.horizon, axis=0)
        chunk[:, 0] += self.step * np.arange(1, self.horizon + 1)
        return chunk


def creep(step: float = 5.0, horizon: int = 4) -> Creep:
    return Creep(step, horizon)


def broken() -> object:
    return object()
