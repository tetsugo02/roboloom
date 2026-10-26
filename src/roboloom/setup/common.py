"""Shared lookups for setup steps: the node an experiment names, and the hardware gate."""

from __future__ import annotations

from pathlib import Path

from ..config import ExperimentConfig, load_experiment
from ..errors import ConfigError, HardwareError


def experiment_node(
    experiment: str | Path, node: str
) -> tuple[ExperimentConfig, object]:
    cfg = load_experiment(experiment)
    owner = {**cfg.inputs, **cfg.robots}.get(node)
    if owner is None:
        raise ConfigError(f"{node}: no such input or robot in {cfg.path}")
    return cfg, owner


def require_hardware(cfg: ExperimentConfig, hardware: bool, what: str) -> None:
    """Moving or writing real motors needs an explicit `hardware=True` (CLI: --hardware)."""
    if cfg.mock:
        raise ConfigError(f"{what} needs a hardware experiment; {cfg.path} is mock")
    if not hardware:
        raise HardwareError(
            f"{what} acts on real motors; pass hardware=True (--hardware)"
        )
