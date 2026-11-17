"""The policy contract for inference in the dataflow (see `controllers.policy`).

A policy is any object with `reset()` and `infer(observation)`. The observation uses the
dataset's feature names, so a policy sees what it was trained on:

    {"observation.state": float32[n], "observation.images.camera": uint8[h, w, 3],
     ..., "task": "pick up the cup"}

`infer` returns the next joint targets in the robot's unit: one step `[n]` or a chunk
`[H, n]`. The node runs it in its own process and loads it from a "module:callable"
reference that returns the policy, e.g. `my_lab.policies:load_act` with `kwargs`.
Modules are looked up in the installed packages first, then in the robot's directory
(`.roboloom/<robot>/`), so a policy kept next to the configuration needs no PYTHONPATH.

A policy may also have `bind(spec: PolicySpec)`. The node calls it once after loading,
before any episode, with the observation's names, dtypes and shapes and the action's
names. A policy checks there that it gets what it was trained on and raises otherwise,
so a mismatch refuses the start instead of failing mid-episode. Policies without `bind`
work as before. `roboloom.policy.lerobot:load` is such a policy for LeRobot checkpoints.

What a model needs beyond the latest frame is asked from the controller, not rebuilt in
every policy: `observation_history: N` adds `observation["history"]` (each observation
stacked `[N, ...]`, oldest first, the current frame last, plus `"action"`: the actions
executed so far) and `hold:` names joints the policy leaves where they are. A policy may
state these itself with `options()` (a dict with `observation_history`, `hold`,
`action_horizon`), which wins over the YAML, so swapping the model needs no edited
configuration. Optional `hooks() -> Sequence[Hook]` (roboloom.hooks) is called after
bind. Writing contributions require an explicit `from: policy` slot and write limit.
Normalization, resizing and decoding the model's own action form into
joint targets stay in the policy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from ..core.registry import load_reference
from ..errors import ConfigError


@dataclass(frozen=True)
class PolicySpec:
    """What the configuration gives a policy (`bind`).

    `observation`: dataset feature name -> {"dtype", "shape", "names"}, the keys and
    shapes of the observation `infer` receives (besides `task`); images are [h, w, 3].
    `action`: the names of the action's entries, `<follower>.<joint>` in order; `units`
    their units. `history` and `hold` are the controller's `observation_history` and
    `hold`, `inference` its `inference` (see `controllers.policy`)."""

    observation: Mapping[str, Mapping[str, Any]]
    action: tuple[str, ...]
    rate_hz: float
    dataset_fps: float
    history: int = 1  # frames in observation["history"] (1: no history)
    hold: tuple[str, ...] = ()  # action entries the policy does not drive
    units: tuple[str, ...] = ()  # the unit of each action entry (its follower's)
    # "async": a chunk replaces the queued one, without the actions whose time passed
    inference: str = "sync"


class Policy(Protocol):
    """What the policy node runs: any object with `reset()` and `infer(observation)`.

    `observation` maps the dataset's feature names (`observation.state`,
    `observation.images.<camera>`, ...) to the latest values, plus `task` (and
    `history` with `observation_history`). `infer` returns joint targets in the
    order of `action` and the followers' units: one step `[n]` or a chunk `[H, n]`.
    Optional methods: `hooks() -> Sequence[Hook]` (from roboloom.hooks),
    called after bind to contribute local steps or lifecycle handlers;
    `bind(spec: PolicySpec)`, called once after loading to refuse a
    configuration the policy was not trained for, and `options()`, returning
    `observation_history`, `hold` or `action_horizon` to use instead of the YAML's.
    """

    def reset(self) -> None:
        """Forget the previous episode (called when an episode starts)."""
        ...

    def infer(self, observation: dict[str, Any]) -> np.ndarray:
        """Joint targets: shape [n] or [H, n]."""
        ...


def load_policy(
    reference: str, kwargs: dict | None = None, search: Sequence[str] = ()
) -> Policy:
    """Call the factory `module:callable` with `kwargs`; the result must be a Policy.

    `search`: directories to import from after the installed packages (appended to
    `sys.path`, so a local file never shadows an installed module)."""
    module, _, attribute = reference.partition(":")
    if not module or not attribute:
        raise ConfigError(f"policy {reference!r}: expected 'module:callable'")
    factory = load_reference(reference, search, "policy")
    policy = factory(**(kwargs or {}))
    if not callable(getattr(policy, "infer", None)) or not callable(
        getattr(policy, "reset", None)
    ):
        raise ConfigError(
            f"policy {reference!r} must return an object with reset() and infer()"
        )
    return policy


class Hold:
    """Stays where the robot is: a policy for checking the inference path safely."""

    def __init__(self, horizon: int = 1):
        self.horizon = horizon

    def reset(self) -> None:
        """Nothing to forget."""

    def infer(self, observation: dict[str, Any]) -> np.ndarray:
        """`horizon` copies of the current `observation.state`."""
        state = np.asarray(observation["observation.state"], dtype=np.float64)
        return np.repeat(state[None, :], self.horizon, axis=0)


def hold(horizon: int = 1) -> Hold:
    """`roboloom.policy:hold`, the template's default policy: keep the arms where they
    are, `horizon` steps per call."""
    return Hold(horizon)
