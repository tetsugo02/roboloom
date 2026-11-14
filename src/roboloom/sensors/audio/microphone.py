"""Continuous mono microphone capture (extra: audio)."""

from __future__ import annotations

import time
from importlib import import_module
from threading import Lock
from typing import ClassVar

import numpy as np

from ...core.checks import identity, positive
from ...core.protocol import Envelope
from ...core.source import ConstantReader, Features, Reader, Sample
from .base import PcmAudio


class SoundDeviceReader:
    def __init__(self, device: str, sample_rate: float, size: int):
        self.size = size
        self.lock = Lock()
        self.buffer = np.empty(0, np.int16)
        self.generation = self.seen = 0
        self.capture_ns = 0
        self.stream = import_module("sounddevice").InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
            device=device,
            callback=self._capture,
        )
        try:
            self.stream.start()
        except BaseException:
            self.stream.close()
            raise

    def _capture(self, data, frames, timing, status) -> None:
        end = time.monotonic_ns()
        if timing is not None:
            # PortAudio times share a clock; translate window end to monotonic time.
            end += int(
                (
                    timing.inputBufferAdcTime
                    + frames / self.stream.samplerate
                    - timing.currentTime
                )
                * 1e9
            )
        with self.lock:
            if status:
                self.buffer = np.empty(0, np.int16)
            self.buffer = np.concatenate((self.buffer, data.reshape(-1)))[-self.size :]
            self.capture_ns = end
            self.generation += 1

    def read(self) -> Sample | None:
        with self.lock:
            if self.buffer.size < self.size or self.seen == self.generation:
                return None
            self.seen = self.generation
            return Sample(self.buffer.copy(), self.capture_ns)

    def close(self) -> None:
        try:
            self.stream.stop()
        finally:
            self.stream.close()


class SoundDeviceMic(PcmAudio):
    keys: ClassVar[tuple[str, ...]] = (*PcmAudio.keys, "device", "channels")

    def __init__(self, name: str, cfg: dict):
        super().__init__(name, cfg)
        self.device = identity(cfg.get("device"), f"{name}.device")
        if cfg.get("channels") != 1:
            raise ValueError(f"{name}: audio must have one channel")

    def device_ids(self) -> tuple[str, ...]:
        return (self.device,)

    def open_device(self, dataset_fps: float) -> Reader:
        return SoundDeviceReader(self.device, self.sample_rate, self.chunk(dataset_fps))


class MelReader:
    def __init__(self, reader: Reader, sensor: MelMono):
        self.reader, self.sensor = reader, sensor
        self.librosa = import_module("librosa")

    def read(self) -> Sample | None:
        sample = self.reader.read()
        if sample is None:
            return None
        sensor = self.sensor
        power = self.librosa.feature.melspectrogram(
            y=sample.value.astype(np.float32) / 32768,
            sr=int(sensor.sample_rate),
            n_fft=sensor.n_fft,
            hop_length=sensor.hop_length,
            n_mels=sensor.n_mels,
            fmax=sensor.fmax,
            center=True,
            power=2.0,
        )
        return Sample(
            self.librosa.power_to_db(power, ref=1.0).astype(np.float32),
            sample.capture_ns,
        )

    def close(self) -> None:
        self.reader.close()


class MelMono(SoundDeviceMic):
    """Low-to-high frequency log mel power; no display transform."""

    keys = (
        *SoundDeviceMic.keys,
        "window_seconds",
        "n_fft",
        "hop_length",
        "n_mels",
        "fmax",
    )

    def __init__(self, name: str, cfg: dict):
        super().__init__(name, {"sample_rate": 44100, **cfg})
        self.window_seconds = positive(
            cfg.get("window_seconds", 1.0), f"{name}.window_seconds"
        )
        self.n_fft = self._integer(cfg.get("n_fft", 2048), "n_fft")
        self.hop_length = self._integer(cfg.get("hop_length", 690), "hop_length")
        self.n_mels = self._integer(cfg.get("n_mels", 64), "n_mels")
        self.fmax = positive(cfg.get("fmax", 15000), f"{name}.fmax")
        if self.fmax > self.sample_rate / 2 or self.chunk(1) < self.n_fft:
            raise ValueError(
                f"{name}: fmax must not exceed Nyquist and window must fit n_fft"
            )

    def _integer(self, value: object, field: str) -> int:
        number = positive(value, f"{self.name}.{field}")
        if int(number) != number:
            raise ValueError(f"{self.name}.{field}: expected integer")
        return int(number)

    def chunk(self, dataset_fps: float) -> int:
        return int(self.sample_rate * self.window_seconds)

    @property
    def shape(self) -> tuple[int, int]:
        return self.n_mels, 1 + self.chunk(1) // self.hop_length

    def open(self, mock: bool, dataset_fps: float) -> Reader:
        if mock:
            return ConstantReader(np.zeros(self.shape, np.float32))
        reader = self.open_device(dataset_fps)
        try:
            return MelReader(reader, self)
        except BaseException:
            reader.close()
            raise

    def encode(self, sample: Sample) -> dict:
        return {"mel": np.asarray(sample.value)}

    def features(self, dataset_fps: float) -> Features:
        return {
            f"observation.audio.{self.name}": {
                "dtype": "float32",
                "shape": self.shape,
                "names": None,
            }
        }

    def frame(self, msg: Envelope | None, dataset_fps: float) -> dict:
        return {
            f"observation.audio.{self.name}": np.asarray(
                msg.payload["mel"], dtype=np.float32
            )
            if msg
            else np.zeros(self.shape, np.float32)
        }

    def signature(self, dataset_fps: float) -> dict:
        return {
            "representation": "mel",
            "sample_rate": self.sample_rate,
            "window_seconds": self.window_seconds,
            "n_fft": self.n_fft,
            "hop_length": self.hop_length,
            "n_mels": self.n_mels,
            "fmax": self.fmax,
            "center": True,
            "power": 2.0,
            "ref": 1.0,
            "frequency_order": "ascending",
            "window": "hann",
            "mel_norm": "slaney",
            "htk": False,
            "top_db": 80.0,
        }
