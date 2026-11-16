"""Config `type` -> class lookup. Modules load on first use, so device SDKs stay optional.

A `type` is a built-in name (`rakuda2_follower`) or a reference `module:Class` to a
class of your own: of an installed package, or of a module next to the configuration
(`.roboloom/<robot>/my_robot.py` -> `type: my_robot:MyFollower`). Every node is a
process of its own that loads the configuration again, so a class is found by its
reference, never by registering it in one process.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from importlib import import_module, invalidate_caches
from typing import Any

from ..errors import ConfigError


def load_reference(reference: str, search: Sequence[str] = (), what: str = "") -> Any:
    """The object `module:attribute` names. `search`: directories to import from after
    the installed packages (appended to `sys.path`, so a local file never shadows an
    installed module)."""
    module, _, attribute = reference.partition(":")
    label = f"{what} {reference!r}".strip()
    if not module or not attribute:
        raise ConfigError(f"{label}: expected 'module:attribute'")
    added = [d for d in search if d and d not in sys.path]
    if added:
        sys.path.extend(added)
        invalidate_caches()
    try:
        return getattr(import_module(module), attribute)
    except (ImportError, AttributeError) as exc:
        raise ConfigError(f"{label}: {exc}") from exc


class Registry[T]:
    def __init__(self, kind: str, entries: dict[str, str], base: type | None = None):
        self.kind = kind
        self._entries = dict(entries)  # type name -> "module:attribute"
        self.base = base  # what a `module:Class` type must subclass

    def register(self, type_name: str, target: str) -> None:
        if type_name in self._entries:
            raise ValueError(f"{self.kind} type {type_name!r} already registered")
        self._entries[type_name] = target

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def get(self, type_name: object, search: Sequence[str] = ()) -> type[T]:
        """The class of a built-in type name, or of a `module:Class` reference (see
        `load_reference` for `search`)."""
        if isinstance(type_name, str) and ":" in type_name:
            cls = load_reference(type_name, search, f"{self.kind} type")
            if not isinstance(cls, type) or (
                self.base is not None and not issubclass(cls, self.base)
            ):
                wanted = self.base.__name__ if self.base is not None else "class"
                raise ConfigError(
                    f"{self.kind} type {type_name!r} is not a {wanted} subclass"
                )
            return cls
        if not isinstance(type_name, str) or type_name not in self._entries:
            raise ValueError(
                f"unsupported {self.kind} type {type_name!r}; expected one of "
                f"{', '.join(self.names())}, or module:Class for a class of your own"
            )
        module, _, attribute = self._entries[type_name].partition(":")
        return getattr(import_module(module), attribute)
