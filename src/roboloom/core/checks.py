"""Value checks shared by configuration parsing and the robot safety boundary."""

from __future__ import annotations

import math


def finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def positive(value: object, name: str) -> float:
    if not isinstance(value, (int, float)) or not finite(value) or value <= 0:
        raise ValueError(f"{name}: expected positive finite number")
    return value


def identity(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("SET_"):
        raise ValueError(f"{name}: explicit device identity required")
    return value


def names(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value or not all(isinstance(x, str) and x for x in value) or len(set(value)) != len(value):
        raise ValueError(f"{name}: expected unique, non-empty joint names")
    return tuple(value)


def positions(value: object, dimension: int) -> list[float]:
    if not isinstance(value, (tuple, list)) or len(value) != dimension:
        raise ValueError(f"expected {dimension} joint positions")
    out = [float(x) for x in value]
    if not all(math.isfinite(x) for x in out):
        raise ValueError("joint positions must be finite")
    return out
