"""Vision stream type: HWC RGB frames. Used directly when the caller supplies readers."""

from __future__ import annotations

from typing import Any

import numpy as np

from ...core.checks import positive
from ...core.protocol import Envelope, pack_array, unpack_array
from ...core.source import ConstantReader, Features, Reader, Sample, Source


class ImageSensor(Source):
    """HWC RGB frames stored as a LeRobot video feature."""

    kind = "image"

    def __init__(self, name: str, cfg: dict):
        super().__init__(name, cfg)
        self.shape = (int(positive(cfg.get("height"), f"{name}.height")), int(positive(cfg.get("width"), f"{name}.width")), 3)

    def open(self, mock: bool, dataset_fps: float) -> Reader:
        return ConstantReader(np.zeros(self.shape, np.uint8)) if mock else self.open_device()

    def open_device(self) -> Reader:
        raise RuntimeError(f"{self.name}: no device driver; pass a reader instead")

    def encode(self, sample: Sample) -> dict:
        return {"image": pack_array(np.asarray(sample.value))}

    def features(self, dataset_fps: float) -> Features:
        return {f"observation.images.{self.name}": {"dtype": "video", "shape": self.shape, "names": ["height", "width", "channels"]}}

    def frame(self, msg: Envelope | None, dataset_fps: float) -> dict[str, Any]:
        image = unpack_array(msg.payload["image"]) if msg else np.zeros(self.shape, np.uint8)
        return {f"observation.images.{self.name}": image.astype(np.uint8)}
