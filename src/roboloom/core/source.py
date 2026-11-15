"""Sampled sources. Operator inputs and sensors share one open/read/encode/record contract."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

import numpy as np

from .checks import positive
from .protocol import Envelope

Features = dict[str, dict[str, Any]]


@dataclass
class Sample:
    value: np.ndarray
    capture_ns: int


class Reader(Protocol):
    """An opened device. `read` returns None when no new sample is available."""

    def read(self) -> Sample | None: ...
    def close(self) -> None: ...


class Recordable(Protocol):
    """Anything the recorder stores: its LeRobot features and one frame's values.

    A source may also contribute parts of features that several sources share
    (`observation.state` of every follower) through `joined` and `joined_frame`; see
    `recording.schema`."""

    def features(self, dataset_fps: float) -> Features: ...
    def frame(self, msg: Envelope | None, dataset_fps: float) -> dict[str, Any]: ...


@dataclass(frozen=True)
class Joined:
    """This source's part of a feature that several sources share. The recorder joins
    the parts in configuration order; `names` label the entries (e.g.
    `follower.r_arm_sh_pitch1`). Parts of one feature must agree on `dtype`, and on
    `unit` when it is set (one effort vector never mixes mA and N m)."""

    names: tuple[str, ...]
    dtype: str = "float32"
    unit: str | None = None


class ConstantReader:
    """Mock device returning a fixed value stamped with the read time."""

    def __init__(self, value: np.ndarray):
        self.value = value

    def read(self) -> Sample:
        return Sample(self.value.copy(), time.monotonic_ns())

    def close(self) -> None:
        pass


class Source(ABC):
    """Validated description of one sampled node. Constructing it never opens a device."""

    kind: ClassVar[str]  # Envelope.kind of published samples
    # The keys of its YAML this class reads; any other key is refused when the
    # configuration is loaded (a misspelled one would otherwise be ignored in silence).
    # A subclass that does not declare `keys` itself is not checked.
    keys: ClassVar[tuple[str, ...]] = ("type", "fps")

    def __init__(self, name: str, cfg: dict):
        self.name, self.cfg = name, cfg

    def rate_hz(self, dataset_fps: float) -> float | None:
        """Polling rate; None follows the robot control rate."""
        return positive(self.cfg.get("fps"), f"{self.name}.fps")

    def device_ids(self) -> tuple[str, ...]:
        """Ports or serials this source owns exclusively."""
        return ()

    @abstractmethod
    def open(self, mock: bool, dataset_fps: float) -> Reader: ...

    @abstractmethod
    def encode(self, sample: Sample) -> dict: ...

    @abstractmethod
    def features(self, dataset_fps: float) -> Features: ...

    @abstractmethod
    def frame(self, msg: Envelope | None, dataset_fps: float) -> dict[str, Any]: ...
