"""In-memory bus for tests and mock experiments.

Position modes move instantly to the goal while torque is on. Current mode keeps
the position and records the goal current, so control laws can be tested.
"""

from __future__ import annotations

from .base import Health, JointState
from .dynamixel_table import OPERATING_MODES


class MockBus:
    def __init__(self, initial: float = 2048, dimension: int = 17, modes: list[int] | None = None):
        self.values = [float(initial)] * dimension
        self.velocities = [0.0] * dimension
        self.enabled = False
        self.torque = [False] * dimension
        self.modes = list(modes) if modes is not None else [OPERATING_MODES["position"]] * dimension
        self.goal_current = [0.0] * dimension
        self.health = Health([0] * dimension, [30.0] * dimension)
        self.eeprom_writes: list[tuple[str, list[int], list[int]]] = []
        self.fail = False  # fault injection: every read and write raises

    def _check(self) -> None:
        if self.fail:
            raise ConnectionError("mock bus failure")

    def read_positions(self) -> list[float]:
        self._check()
        return self.values.copy()

    def read_state(self) -> JointState:
        self._check()
        return JointState(self.values.copy(), self.velocities.copy(), self.goal_current.copy())

    def read_health(self) -> Health:
        self._check()
        return self.health

    def read_register(self, name: str) -> list[int]:
        self._check()
        if name == "operating_mode":
            return self.modes.copy()
        if name == "torque_enable":
            return [int(t) for t in self.torque]
        raise KeyError(name)

    def write_positions(self, values: list[float]) -> None:
        self.write_goal_positions(list(range(len(self.values))), values)

    def write_goal_positions(self, indices: list[int], values: list[float]) -> None:
        self._check()
        for i, v in zip(indices, values, strict=True):
            if self.modes[i] != OPERATING_MODES["current"]:
                self.values[i] = float(v)

    def write_goal_currents(self, indices: list[int], values_mA: list[float]) -> None:
        self._check()
        for i, v in zip(indices, values_mA, strict=True):
            self.goal_current[i] = float(v)

    def set_torque(self, indices: list[int], on: bool) -> None:
        self._check()
        for i in indices:
            self.torque[i] = on
        self.enabled = any(self.torque)

    def write_eeprom(self, name: str, indices: list[int], values: list[int]) -> None:
        self._check()
        if any(self.torque[i] for i in indices):
            raise RuntimeError("torque must be off before writing EEPROM")
        self.eeprom_writes.append((name, list(indices), list(values)))
        if name == "operating_mode":
            for i, v in zip(indices, values, strict=True):
                self.modes[i] = v

    def enable_torque(self) -> None:
        self.set_torque(list(range(len(self.values))), True)

    def disable_torque(self) -> None:
        self.set_torque(list(range(len(self.values))), False)

    def close(self) -> None:
        self.torque = [False] * len(self.values)
        self.enabled = False
