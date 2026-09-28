"""Microphone capture through sounddevice (extra: hardware)."""

from __future__ import annotations

import time
from importlib import import_module

from ...core.checks import identity
from ...core.source import Reader, Sample
from .base import PcmAudio


class SoundDeviceReader:
    def __init__(self, device: str, sample_rate: float, size: int):
        self.sd = import_module("sounddevice")
        self.device, self.sample_rate, self.size = device, sample_rate, size

    def read(self) -> Sample:
        samples = self.sd.rec(self.size, samplerate=self.sample_rate, channels=1, dtype="int16", device=self.device, blocking=True)
        return Sample(samples.reshape(-1), time.monotonic_ns())

    def close(self) -> None:
        pass


class SoundDeviceMic(PcmAudio):
    def __init__(self, name: str, cfg: dict):
        super().__init__(name, cfg)
        self.device = identity(cfg.get("device"), f"{name}.device")
        if cfg.get("channels") != 1:
            raise ValueError(f"{name}: audio must have one channel")

    def device_ids(self) -> tuple[str, ...]:
        return (self.device,)

    def open_device(self, dataset_fps: float) -> Reader:
        return SoundDeviceReader(self.device, self.sample_rate, self.chunk(dataset_fps))
