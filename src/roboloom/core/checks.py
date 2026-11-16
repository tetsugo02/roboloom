"""Value checks shared by configuration parsing and the robot safety boundary."""

from __future__ import annotations

import difflib
import math
from collections.abc import Iterable, Mapping

from ..errors import ConfigError


def finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def unknown_keys(cfg: object, allowed: Iterable[str], where: str) -> None:
    """Refuse the keys of a mapping that nothing reads: a misspelled key (`torqe: false`)
    would otherwise be ignored in silence and the default used. Keys starting `__` are
    added while loading and pass."""
    if not isinstance(cfg, Mapping):
        return
    known = tuple(allowed)
    unknown = [str(k) for k in cfg if not str(k).startswith("__") and k not in known]
    if not unknown:
        return

    def hint(key: str) -> str:
        close = difflib.get_close_matches(key, known, n=1)
        return f"{key} (did you mean {close[0]}?)" if close else key

    raise ConfigError(
        f"{where}: unknown keys {', '.join(map(hint, unknown))}; it reads "
        f"{', '.join(sorted(known))}"
    )


def positive(value: object, name: str) -> float:
    if not isinstance(value, (int, float)) or not finite(value) or value <= 0:
        raise ValueError(f"{name}: expected positive finite number")
    return value


def identity(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("SET_"):
        raise ValueError(f"{name}: explicit device identity required")
    return value


def names(value: object, name: str) -> tuple[str, ...]:
    if (
        not isinstance(value, (list, tuple))
        or not value
        or not all(isinstance(x, str) and x for x in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError(f"{name}: expected unique, non-empty joint names")
    return tuple(value)


def positions(value: object, dimension: int) -> list[float]:
    if not isinstance(value, (tuple, list)) or len(value) != dimension:
        raise ValueError(f"expected {dimension} joint positions")
    out = [float(x) for x in value]
    if not all(math.isfinite(x) for x in out):
        raise ValueError("joint positions must be finite")
    return out
