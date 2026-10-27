"""Explicit display registration: device kind, role, then generic fields."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from rich.text import Text

from .models import NodeSnapshot
from .render import RENDERERS


@dataclass(frozen=True)
class Presentation:
    state: str
    explanation: str | Text  # Text keeps the renderer's emphasis (home pose, faults)
    values: tuple[tuple[str, str], ...]


Presenter = Callable[[NodeSnapshot], Presentation]
KINDS: dict[str, Presenter] = {}
ROLES: dict[str, Presenter] = {}


def register_presenter(
    *, kind: str = "", role: str = ""
) -> Callable[[Presenter], Presenter]:
    """Register explicitly at application startup; kinds override roles."""
    if bool(kind) == bool(role):
        raise ValueError("specify exactly one of kind or role")

    def add(presenter: Presenter) -> Presenter:
        (KINDS if kind else ROLES)[kind or role] = presenter
        return presenter

    return add


def present(node: NodeSnapshot) -> Presentation:
    presenter = KINDS.get(node.kind) or ROLES.get(node.role)
    if presenter is not None:
        return presenter(node)
    values = tuple((key, str(value)) for key, value in node.fields.items())
    renderer = RENDERERS.get(node.role)
    if renderer is None:
        return Presentation(
            str(node.fields.get("state", node.fields.get("mode", ""))), "", values
        )
    state, detail = renderer(dict(node.fields))
    return Presentation(state, detail, values)
