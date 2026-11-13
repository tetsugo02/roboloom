"""Replay recorded actions as a policy (`roboloom.policy.replay:load`).

    factory: roboloom.policy.replay:load
    kwargs:
      path: datasets/rakuda2     # a recorded LeRobotDataset, or a .npy file [T, n]
      episode: 0                 # which episode of the dataset
      stride: 1                  # every stride-th row: rate_hz = dataset fps / stride
    action_horizon: 8

The recorded `action` rows go to the followers in order, whatever is observed (open
loop). It checks the path from a recording to the robot without a model: the same
controller, speed limit, interpolation and safety checks as a learned policy, so the
recorded `observation.state` of the replay can be compared with the original. A `.npy`
file replays actions from elsewhere, e.g. to check the joint order and units of data
recorded with another tool: move the robot to the episode's first pose first (`home`)
and keep `max_speed` low.

After the last action the policy keeps returning it (the followers stay there).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ..errors import ConfigError
from . import PolicySpec


class Replay:
    def __init__(
        self,
        actions: np.ndarray,
        horizon: int = 8,
        names: tuple[str, ...] | None = None,
        rate_hz: float | None = None,
        source: str = "replay",
    ):
        actions = np.asarray(actions, dtype=np.float64)
        if actions.ndim != 2 or not len(actions) or not np.isfinite(actions).all():
            raise ConfigError(
                f"{source}: expected finite actions [T, n], got shape {actions.shape}"
            )
        if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
            raise ConfigError(f"{source}: horizon must be an integer >= 1")
        self.actions, self.horizon = actions, horizon
        self.names, self.rate_hz, self.source = names, rate_hz, source
        self.at = 0

    def options(self) -> dict:
        return {"action_horizon": self.horizon}

    def bind(self, spec: PolicySpec) -> None:
        problems = []
        if self.actions.shape[1] != len(spec.action):
            problems.append(
                f"it has {self.actions.shape[1]} values per action, the "
                f"configuration {len(spec.action)} ({', '.join(spec.action)})"
            )
        elif self.names and tuple(self.names) != tuple(spec.action):
            problems.append(
                f"its action is ({', '.join(self.names)}), the configuration's "
                f"({', '.join(spec.action)})"
            )
        if self.rate_hz is not None and abs(self.rate_hz - spec.rate_hz) > 1e-6:
            problems.append(
                f"its actions are {self.rate_hz:g} Hz apart, rate_hz is "
                f"{spec.rate_hz:g} (set rate_hz, or stride)"
            )
        if problems:
            raise ConfigError(
                f"{self.source} does not fit this configuration: " + "; ".join(problems)
            )

    def reset(self) -> None:
        self.at = 0

    def infer(self, observation: dict[str, Any]) -> np.ndarray:
        chunk = self.actions[self.at : self.at + self.horizon]
        self.at += self.horizon
        return chunk if len(chunk) else self.actions[-1:]


def episode_rows(dataset: Any, episode: int) -> np.ndarray:
    """Row numbers of `episode` in a LeRobotDataset's table, in recorded order."""
    index = np.asarray(dataset.hf_dataset["index"]).ravel()
    episodes = np.asarray(dataset.hf_dataset["episode_index"]).ravel()
    order = np.argsort(index, kind="stable")
    rows = order[episodes[order] == episode]
    if not len(rows):
        raise ConfigError(
            f"no episode {episode}; the dataset has episodes "
            f"{sorted(set(episodes.tolist()))}"
        )
    return rows


def load(path: str, episode: int = 0, horizon: int = 8, stride: int = 1) -> Replay:
    """`roboloom.policy.replay:load`: the actions of one recorded episode, or of a
    `.npy` file `[T, n]` (then `stride` only thins the rows and nothing is checked
    against the configuration but the action's size)."""
    if isinstance(stride, bool) or not isinstance(stride, int) or stride < 1:
        raise ConfigError("replay: stride must be an integer >= 1")
    source = Path(path)
    if source.suffix == ".npy":
        if not source.is_file():
            raise ConfigError(f"{source}: no such file")
        return Replay(np.load(source)[::stride], horizon, source=str(source))
    if not (source / "meta" / "info.json").exists():
        raise ConfigError(
            f"{source}: not a LeRobot dataset (no meta/info.json) nor a .npy file"
        )
    try:
        from lerobot.datasets import LeRobotDataset
    except ImportError as exc:
        raise ConfigError(
            f"replaying a dataset needs lerobot ({exc}); install roboloom with the "
            "record extra"
        ) from exc
    dataset = LeRobotDataset(f"local/{source.name}", root=source)
    feature = dataset.meta.features.get("action")
    if feature is None:
        raise ConfigError(f"{source}: the dataset records no action")
    rows = episode_rows(dataset, episode)[::stride]
    actions = np.stack(dataset.hf_dataset.select(rows.tolist())["action"])
    names = tuple(feature.get("names") or ()) or None
    return Replay(
        actions,
        horizon,
        names,
        dataset.meta.fps / stride,
        f"{source} episode {episode}",
    )
