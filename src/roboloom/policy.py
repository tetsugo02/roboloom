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
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from importlib import import_module, invalidate_caches
from typing import Any, Protocol

import numpy as np

from .errors import ConfigError


class Policy(Protocol):
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
    added = [d for d in search if d and d not in sys.path]
    if added:
        sys.path.extend(added)
        invalidate_caches()
    try:
        factory = getattr(import_module(module), attribute)
    except (ImportError, AttributeError) as exc:
        raise ConfigError(f"policy {reference!r}: {exc}") from exc
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
        pass

    def infer(self, observation: dict[str, Any]) -> np.ndarray:
        state = np.asarray(observation["observation.state"], dtype=np.float64)
        return np.repeat(state[None, :], self.horizon, axis=0)


def hold(horizon: int = 1) -> Hold:
    return Hold(horizon)
