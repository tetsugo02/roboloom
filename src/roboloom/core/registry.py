"""Config `type` -> class lookup. Modules load on first use, so device SDKs stay optional."""

from __future__ import annotations

from importlib import import_module


class Registry[T]:
    def __init__(self, kind: str, entries: dict[str, str]):
        self.kind = kind
        self._entries = dict(entries)  # type name -> "module:attribute"

    def register(self, type_name: str, target: str) -> None:
        if type_name in self._entries:
            raise ValueError(f"{self.kind} type {type_name!r} already registered")
        self._entries[type_name] = target

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def get(self, type_name: object) -> type[T]:
        if not isinstance(type_name, str) or type_name not in self._entries:
            raise ValueError(f"unsupported {self.kind} type {type_name!r}; expected one of {', '.join(self.names())}")
        module, _, attribute = self._entries[type_name].partition(":")
        return getattr(import_module(module), attribute)
