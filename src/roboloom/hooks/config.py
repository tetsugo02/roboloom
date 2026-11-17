"""Validate YAML limits before loading hooks, then validate their declarations."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace

from ..core.checks import positive, unknown_keys
from ..core.registry import load_reference
from ..errors import ConfigError
from .types import HOOKS_API, HookSpec, Requirements

ON_ERROR = {
    "fail": "fail the episode",
    "hold": "hold written entries",
    "pass": "pass input",
}
SOURCES = {"policy", "teleop"}
KEYS = (
    "factory",
    "from",
    "kwargs",
    "writes",
    "sources",
    "on_error",
    "budget_ms",
    "name",
)


def _names(raw: object, where: str, allowed: set[str] | None = None) -> tuple[str, ...]:
    if not isinstance(raw, (list, tuple)) or not all(isinstance(x, str) for x in raw):
        raise ConfigError(f"{where}: expected a list of names")
    if len(set(raw)) != len(raw) or (allowed is not None and not set(raw) <= allowed):
        raise ConfigError(
            f"{where}: names must be unique and from {sorted(allowed or [])}"
        )
    return tuple(raw)


def _error(raw: object, where: str) -> None:
    if not isinstance(raw, str) or raw not in ON_ERROR:
        raise ConfigError(f"{where}: expected one of {', '.join(ON_ERROR)}")


def _budget(raw: object, where: str) -> float:
    try:
        return positive(raw, where)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


@dataclass(frozen=True)
class HookEntry:
    factory: str | None = None
    kwargs: dict | None = None
    writes: tuple[str, ...] = ()
    sources: tuple[str, ...] | None = None
    on_error: str | None = None
    budget_ms: float | None = None
    name: str | None = None


def parse_hooks(
    raw: object, names: Sequence[str], *, teleop: bool = False, backend: str = "process"
) -> tuple[HookEntry, ...]:
    """Parse a policy node's hooks without importing factories or the policy."""
    if not isinstance(raw, list):
        raise ConfigError("hooks: expected a list")
    out: list[HookEntry] = []
    policy_seen = False
    for i, entry in enumerate(raw):
        where = f"hooks[{i}]"
        if not isinstance(entry, dict):
            raise ConfigError(f"{where}: expected a mapping")
        unknown_keys(entry, KEYS, where)
        if ("factory" in entry) == ("from" in entry):
            raise ConfigError(f"{where}: exactly one of factory or from is required")
        factory = entry.get("factory")
        if "from" in entry:
            if entry["from"] != "policy" or policy_seen:
                raise ConfigError(f"{where}: from: policy is allowed at most once")
            policy_seen = True
            if "kwargs" in entry:
                raise ConfigError(f"{where}: kwargs requires a factory")
        elif not isinstance(factory, str) or ":" not in factory:
            raise ConfigError(f"{where}.factory: expected module:callable")
        if not isinstance(entry.get("kwargs", {}), dict):
            raise ConfigError(f"{where}.kwargs: expected a mapping")
        writes = _names(entry.get("writes", []), f"{where}.writes", set(names))
        sources = (
            _names(entry["sources"], f"{where}.sources", SOURCES)
            if "sources" in entry
            else None
        )
        if sources is not None and "teleop" in sources and not teleop:
            raise ConfigError(f"{where}: sources: [teleop] requires teleop:")
        if factory is None and writes and backend == "server":
            raise ConfigError(
                f"{where}: from: policy with writes requires backend: process"
            )
        if "on_error" in entry:
            _error(entry["on_error"], f"{where}.on_error")
        budget = (
            _budget(entry["budget_ms"], f"{where}.budget_ms")
            if "budget_ms" in entry
            else None
        )
        name = entry.get("name")
        if name is not None and (not isinstance(name, str) or not name):
            raise ConfigError(f"{where}.name: expected nonempty text")
        out.append(
            HookEntry(
                factory,
                entry.get("kwargs"),
                writes,
                sources,
                entry.get("on_error"),
                budget,
                name,
            )
        )
    return tuple(out)


@dataclass(frozen=True)
class BoundHook:
    hook: object
    name: str
    requirements: Requirements


def build_hooks(
    entries: Sequence[HookEntry],
    policy_hooks: Sequence[object],
    spec: HookSpec,
    search: Sequence[str] = (),
) -> list[BoundHook]:
    """Build and bind hooks in YAML order, checking every write claim."""
    pending: list[tuple[object, HookEntry | None]] = []
    owned = {id(h): h for h in policy_hooks}
    result: list[BoundHook] = []
    try:
        if not any(e.factory is None for e in entries):
            pending.extend((h, None) for h in policy_hooks)
        for yaml_entry in entries:
            if yaml_entry.factory is None:
                pending.extend((h, yaml_entry) for h in policy_hooks)
            else:
                factory = load_reference(yaml_entry.factory, search, "hook")
                hook = factory(**(yaml_entry.kwargs or {}))
                owned[id(hook)] = hook
                pending.append((hook, yaml_entry))
        if len({id(h) for h, _ in pending}) != len(pending):
            raise ConfigError("each hook instance may occur only once in the chain")
        declarations: list[Requirements] = []
        for hook, _ in pending:
            read = getattr(hook, "requirements", None)
            req = read() if callable(read) else Requirements()
            if not isinstance(req, Requirements):
                raise ConfigError("hook requirements() must return Requirements")
            if (
                isinstance(req.api, bool)
                or not isinstance(req.api, int)
                or not 1 <= req.api <= HOOKS_API
            ):
                raise ConfigError(
                    f"hook requires API {req.api}; node offers {HOOKS_API}"
                )
            _names(req.observe, "hook observe", set(spec.observation))
            _names(req.writes, "hook writes", set(spec.names))
            _names(req.sources, "hook sources", SOURCES)
            if req.on_error is not None:
                _error(req.on_error, "hook on_error")
            if req.budget_ms is not None:
                _budget(req.budget_ms, "hook budget_ms")
            declarations.append(req)
        missing = tuple(
            dict.fromkeys(
                name
                for (_, entry), req in zip(pending, declarations, strict=True)
                if entry is None
                for name in req.writes
            )
        )
        if missing:
            raise ConfigError(
                "policy hooks that write require these exact YAML lines under hooks:\n"
                "- from: policy\n  writes: [" + ", ".join(missing) + "]"
            )
        for i, ((hook, entry), req) in enumerate(
            zip(pending, declarations, strict=True)
        ):
            if entry is not None and not set(req.writes) <= set(entry.writes):
                raise ConfigError(
                    f"hook writes {req.writes} exceed YAML writes {entry.writes}"
                )
            sources = (
                entry.sources if entry and entry.sources is not None else req.sources
            )
            if not set(sources) <= set(spec.sources):
                raise ConfigError(
                    "hook sources include teleop but this node has no teleop:"
                )
            if not set(sources) <= set(req.sources):
                raise ConfigError("hook sources may only narrow requirements.sources")
            on_error = (
                (entry.on_error if entry else None)
                or req.on_error
                or ("fail" if req.writes else "pass")
            )
            _error(on_error, "hook on_error")
            budget = (
                entry.budget_ms
                if entry and entry.budget_ms is not None
                else req.budget_ms
            )
            req = replace(req, sources=sources, on_error=on_error, budget_ms=budget)
            name = entry.name if entry and entry.name else f"{type(hook).__name__}:{i}"
            bind = getattr(hook, "bind", None)
            if callable(bind):
                bind(spec)
            result.append(BoundHook(hook, name, req))
    except BaseException:
        for hook in owned.values():
            close = getattr(hook, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logging.getLogger(__name__).exception(
                        "hook close raised after load refusal"
                    )
        raise
    return result
