"""Versioned wire messages. All times use this host's monotonic nanoseconds."""

from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Protocol, runtime_checkable

SCHEMA_VERSION = 1


@runtime_checkable
class _ArrowBytes(Protocol):
    def to_pylist(self) -> list[int]: ...


@dataclass
class Envelope:
    kind: str
    source_id: str
    boot_id: str
    seq: int
    t_capture_ns: int
    t_ready_ns: int
    payload: dict
    version: int = SCHEMA_VERSION
    t_receive_ns: int = 0

    def __post_init__(self) -> None:
        if self.version != SCHEMA_VERSION or self.seq < 0 or self.t_capture_ns > self.t_ready_ns:
            raise ValueError("invalid message header")

    def encode(self) -> bytes:
        return json.dumps(asdict(self), separators=(",", ":")).encode()

    @classmethod
    def decode(cls, value: object) -> Envelope:
        if isinstance(value, (bytes, bytearray, memoryview)):
            raw = bytes(value)
        elif isinstance(value, _ArrowBytes):
            raw = bytes(value.to_pylist())
        else:
            raise TypeError("wire payload must be bytes or an Arrow byte array")
        msg = cls(**json.loads(raw))
        msg.t_receive_ns = time.monotonic_ns()
        return msg


class Publisher:
    def __init__(self, source_id: str):
        self.source_id = source_id
        self.boot_id = str(uuid.uuid4())
        self.seq = 0

    def make(self, kind: str, payload: dict, capture: int | None = None) -> Envelope:
        ready = time.monotonic_ns()
        msg = Envelope(kind, self.source_id, self.boot_id, self.seq, capture or ready, ready, payload)
        self.seq += 1
        return msg


def pack_array(array) -> dict:
    import numpy as np

    a = np.ascontiguousarray(array)
    return {"shape": a.shape, "dtype": str(a.dtype), "bytes": base64.b64encode(a.tobytes()).decode()}


def unpack_array(value: dict):
    import numpy as np

    a = np.frombuffer(base64.b64decode(value["bytes"]), dtype=np.dtype(value["dtype"]))
    return a.reshape(value["shape"])
