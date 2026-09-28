"""Operator input contracts. Inputs never talk to the follower; a controller converts them."""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

import numpy as np

from ..core.checks import names, positions, positive
from ..core.protocol import Envelope
from ..core.source import Features, Reader, Sample, Source
from ..robots.base import RobotBus


class InputDevice(Source):
    """A source that drives a controller rather than only being recorded."""

    def rate_hz(self, dataset_fps: float) -> float | None:
        poll = self.cfg.get("poll_hz")
        return None if poll is None else positive(poll, f"{self.name}.poll_hz")


class BusReader:
    """Reads a position bus as timestamped joint samples."""

    def __init__(self, bus: RobotBus):
        self.bus = bus

    def read(self) -> Sample:
        values = self.bus.read_positions()
        return Sample(np.asarray(values, dtype=np.float64), time.monotonic_ns())

    def close(self) -> None:
        self.bus.close()


class JointInput(InputDevice):
    """Joint-space intent, e.g. a physical leader arm. Used directly when the caller supplies readings."""

    kind = "joint_intent"

    def __init__(self, name: str, cfg: dict, joint_names: Sequence[str] | None = None, unit: str | None = None):
        super().__init__(name, cfg)
        self.joint_names = names(cfg.get("joints") if joint_names is None else joint_names, f"{name}.joints")
        self.unit = unit or cfg.get("unit", "dynamixel_count")
        self.rate_hz(0)

    def open_bus(self, mock: bool) -> RobotBus:
        raise RuntimeError(f"{self.name}: no bus driver; pass a reader instead")

    def open(self, mock: bool, dataset_fps: float) -> Reader:
        return BusReader(self.open_bus(mock))

    def encode(self, sample: Sample) -> dict:
        return {"positions": positions(np.asarray(sample.value).tolist(), len(self.joint_names)), "unit": self.unit}

    def features(self, dataset_fps: float) -> Features:
        return {f"observation.{self.name}": {"dtype": "float32", "shape": (len(self.joint_names),), "names": None}}

    def frame(self, msg: Envelope | None, dataset_fps: float) -> dict[str, Any]:
        values = msg.payload["positions"] if msg else [0] * len(self.joint_names)
        return {f"observation.{self.name}": np.asarray(values, dtype=np.float32)}
