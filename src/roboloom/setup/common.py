"""Shared lookups for setup steps: the node a configuration names, and the hardware gate."""

from __future__ import annotations

from pathlib import Path

from ..config import RobotConfig, load_config
from ..errors import ConfigError


def load(config: str | Path | RobotConfig) -> RobotConfig:
    """A loaded configuration as is (the CLI loads it with the chosen options and mode),
    or a path or robot name loaded with its default options."""
    if isinstance(config, RobotConfig):
        return config
    return load_config(config)


def config_node(
    config: str | Path | RobotConfig, node: str
) -> tuple[RobotConfig, object]:
    cfg = load(config)
    owner = {**cfg.inputs, **cfg.followers}.get(node)
    if owner is None:
        raise ConfigError(f"{node}: no such input or robot in {cfg.path}")
    return cfg, owner


def require_hardware(cfg: RobotConfig, what: str) -> None:
    """Steps that only make sense on real motors refuse a mock configuration."""
    if cfg.mock:
        raise ConfigError(f"{what} needs real motors; {cfg.path} runs in mock mode")
