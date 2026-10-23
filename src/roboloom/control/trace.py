"""Per-tick record of a JointDevice: what was measured, what the model said, what was sent.

Kept in memory and written as one npz when the device closes (also after a runaway
or watchdog stop, so the last second before the stop is in the file). Joints a tick
did not command hold NaN.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np

from ..drivers.base import JointState

MAX_ROWS = 60 * 60 * 30  # 30 min at 60 Hz; older rows are dropped first


class Trace:
    def __init__(self, path: str | Path, joint_names: Sequence[str]):
        self.path, self.joint_names = Path(path), list(joint_names)
        self.rows: list[np.ndarray] = []

    def add(
        self,
        t_ns: int,
        state: JointState,
        model_mA: dict[int, float],
        commanded_mA: dict[int, float],
    ) -> None:
        n = len(self.joint_names)
        row = np.full(1 + 5 * n, np.nan)
        row[0] = t_ns
        row[1 : 1 + n] = state.positions
        if state.velocities is not None:
            row[1 + n : 1 + 2 * n] = state.velocities
        if state.currents_mA is not None:
            row[1 + 2 * n : 1 + 3 * n] = state.currents_mA
        for i, v in model_mA.items():
            row[1 + 3 * n + i] = v
        for i, v in commanded_mA.items():
            row[1 + 4 * n + i] = v
        self.rows.append(row)
        if len(self.rows) > MAX_ROWS:
            del self.rows[: len(self.rows) - MAX_ROWS]

    def save(self) -> Path | None:
        if not self.rows:
            return None
        n = len(self.joint_names)
        a = np.array(self.rows)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(
            self.path,
            joints=np.array(self.joint_names),
            t_ns=a[:, 0].astype(np.int64),
            positions=a[:, 1 : 1 + n],
            velocities=a[:, 1 + n : 1 + 2 * n],
            measured_mA=a[:, 1 + 2 * n : 1 + 3 * n],
            model_mA=a[:, 1 + 3 * n : 1 + 4 * n],  # g(q) at gain 1
            # sent Goal Current: model after ramp, gain, damping, range barrier and clip
            commanded_mA=a[:, 1 + 4 * n :],
        )
        return self.path
