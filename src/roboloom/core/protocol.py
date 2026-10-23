"""Versioned wire messages. All times use this host's monotonic nanoseconds.

Wire format: 4-byte little-endian header length, a JSON header, then the raw
bytes of every top-level `np.ndarray` in the payload. Arrays never pass through
JSON or base64, so camera frames cost one copy on each side.
"""

from __future__ import annotations

import json
import struct
import time
import uuid
from dataclasses import asdict, dataclass, fields
from typing import Protocol, runtime_checkable

import numpy as np

SCHEMA_VERSION = 2
_ARRAYS = "__arrays__"


@runtime_checkable
class _ArrowArray(Protocol):
    def to_numpy(self, zero_copy_only: bool = ...) -> np.ndarray: ...


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
        if (
            self.version != SCHEMA_VERSION
            or self.seq < 0
            or self.t_capture_ns > self.t_ready_ns
        ):
            raise ValueError("invalid message header")

    def encode(self) -> bytes:
        header = {
            f.name: getattr(self, f.name) for f in fields(self) if f.name != "payload"
        }
        payload, arrays, blobs = {}, [], []
        for key, value in self.payload.items():
            if isinstance(value, np.ndarray):
                a = np.ascontiguousarray(value)
                arrays.append(
                    {
                        "key": key,
                        "dtype": a.dtype.str,
                        "shape": list(a.shape),
                        "nbytes": a.nbytes,
                    }
                )
                blobs.append(a.tobytes())
            else:
                payload[key] = value
        header["payload"] = payload
        header[_ARRAYS] = arrays
        raw = json.dumps(header, separators=(",", ":")).encode()
        return b"".join([struct.pack("<I", len(raw)), raw, *blobs])

    @classmethod
    def decode(cls, value: object) -> Envelope:
        if isinstance(value, (bytes, bytearray, memoryview)):
            buffer = np.frombuffer(value, dtype=np.uint8)
        elif isinstance(value, _ArrowArray):
            buffer = value.to_numpy(zero_copy_only=False).view(np.uint8)
        else:
            raise TypeError("wire payload must be bytes or an Arrow byte array")
        (size,) = struct.unpack("<I", buffer[:4].tobytes())
        header = json.loads(buffer[4 : 4 + size].tobytes())
        offset = 4 + size
        for spec in header.pop(_ARRAYS):
            end = offset + spec["nbytes"]
            array = (
                buffer[offset:end]
                .view(np.dtype(spec["dtype"]))
                .reshape(spec["shape"])
                .copy()
            )
            header["payload"][spec["key"]] = array
            offset = end
        if offset != len(buffer):
            raise ValueError("trailing bytes after message arrays")
        msg = cls(**header)
        msg.t_receive_ns = time.monotonic_ns()
        return msg

    def header(self) -> dict:
        """Header and non-array payload, e.g. for reports and logs."""
        out = asdict(self)
        out["payload"] = {
            k: v for k, v in self.payload.items() if not isinstance(v, np.ndarray)
        }
        return out


class Publisher:
    def __init__(self, source_id: str):
        self.source_id = source_id
        self.boot_id = str(uuid.uuid4())
        self.seq = 0

    def make(self, kind: str, payload: dict, capture: int | None = None) -> Envelope:
        ready = time.monotonic_ns()
        msg = Envelope(
            kind,
            self.source_id,
            self.boot_id,
            self.seq,
            capture or ready,
            ready,
            payload,
        )
        self.seq += 1
        return msg
