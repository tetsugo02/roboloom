"""In-memory position bus for tests and mock experiments."""

from __future__ import annotations


class MockBus:
    def __init__(self, initial: float = 2048, dimension: int = 17):
        self.values = [float(initial)] * dimension
        self.enabled = False

    def read_positions(self) -> list[float]:
        return self.values.copy()

    def write_positions(self, values: list[float]) -> None:
        self.values = list(values)

    def enable_torque(self) -> None:
        self.enabled = True

    def close(self) -> None:
        self.enabled = False
