"""Gravity model contract. Implementations may be identified, model-based or learned."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class GravityModel(Protocol):
    @property
    def joint_names(self) -> tuple[str, ...]:
        """Joints whose positions the model reads, in input order."""
        ...

    @property
    def output_joints(self) -> tuple[str, ...]:
        """Joints it returns current for, in output order."""
        ...

    def effort_mA(self, positions: Sequence[float]) -> list[float]:
        """Holding current per output joint for raw positions of `joint_names`."""
        ...


def load_gravity_model(path: str) -> GravityModel:
    from .regressor import RegressorGravityModel

    return RegressorGravityModel.load(path)
