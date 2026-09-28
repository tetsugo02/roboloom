"""Audio stream type: mono PCM. Used directly when the caller supplies readers."""

from __future__ import annotations

from typing import Any

import numpy as np

from ...core.checks import positive
from ...core.protocol import Envelope, pack_array, unpack_array
from ...core.source import ConstantReader, Features, Reader, Sample, Source


class PcmAudio(Source):
    """Mono int16 PCM, one fixed-length chunk per dataset frame."""

    kind = "audio"

    def __init__(self, name: str, cfg: dict):
        super().__init__(name, cfg)
        self.sample_rate = positive(cfg.get("sample_rate"), f"{name}.sample_rate")

    def chunk(self, dataset_fps: float) -> int:
        return int(self.sample_rate / dataset_fps)

    def rate_hz(self, dataset_fps: float) -> float | None:
        return dataset_fps

    def open(self, mock: bool, dataset_fps: float) -> Reader:
        return ConstantReader(np.zeros(self.chunk(dataset_fps), np.int16)) if mock else self.open_device(dataset_fps)

    def open_device(self, dataset_fps: float) -> Reader:
        raise RuntimeError(f"{self.name}: no device driver; pass a reader instead")

    def encode(self, sample: Sample) -> dict:
        return {"pcm": pack_array(np.asarray(sample.value))}

    def features(self, dataset_fps: float) -> Features:
        return {f"observation.audio.{self.name}": {"dtype": "int16", "shape": (self.chunk(dataset_fps),), "names": None}}

    def frame(self, msg: Envelope | None, dataset_fps: float) -> dict[str, Any]:
        size = self.chunk(dataset_fps)
        data = unpack_array(msg.payload["pcm"]).reshape(-1) if msg else np.zeros(size, np.int16)
        pcm = np.pad(data[:size], (0, max(0, size - len(data))), constant_values=0).astype(np.int16)
        return {f"observation.audio.{self.name}": pcm}
