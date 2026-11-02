"""Shared lookups for setup steps: the node a configuration names, and the hardware gate."""

from __future__ import annotations

from pathlib import Path

from ..config import ExperimentConfig, load_experiment
from ..errors import ConfigError


def load(experiment: str | Path | ExperimentConfig) -> ExperimentConfig:
    """A loaded configuration as is (the CLI loads it with the chosen options and mode),
    or a path or robot name loaded with its default options."""
    if isinstance(experiment, ExperimentConfig):
        return experiment
    return load_experiment(experiment)


def experiment_node(
    experiment: str | Path | ExperimentConfig, node: str
) -> tuple[ExperimentConfig, object]:
    cfg = load(experiment)
    owner = {**cfg.inputs, **cfg.robots}.get(node)
    if owner is None:
        raise ConfigError(f"{node}: no such input or robot in {cfg.path}")
    return cfg, owner


def require_hardware(cfg: ExperimentConfig, what: str) -> None:
    """Steps that only make sense on real motors refuse a mock configuration."""
    if cfg.mock:
        raise ConfigError(f"{what} needs real motors; {cfg.path} runs in mock mode")
