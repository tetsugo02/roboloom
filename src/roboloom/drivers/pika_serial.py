"""Serial link of AgileX Pika devices (Pika Gripper, Pika Sense), over pyserial.

The protocol, as the vendor's pika_sdk (github.com/agilexrobotics/pika_sdk) speaks it:
460800 baud 8N1; commands are one byte, a little-endian float32 and `\\r\\n`; the device
streams JSON objects (`{"motor": {...}, "motorstatus": {...}}`, keys vary by device),
sometimes with trailing commas. The frames carry no timestamp or sequence number, so
`PikaSerial` stamps each top-level key when it arrives and callers judge staleness.

The vendor SDK is not used: it pulls in GUI and camera packages, and a thin reader with
receive stamps is what the bus contract needs.
"""

from __future__ import annotations

import json
import re
import struct
import threading
import time
from collections.abc import Callable
from typing import Any

BAUDRATE = 460_800
MAX_BUFFER = 4096  # text kept while looking for the end of an object
PORT_HINT = (
    "check the USB cable and the device's power; use a stable path such as "
    "/dev/serial/by-path/... (ls -l /dev/serial/by-path), not /dev/ttyUSB<n>"
)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def encode(cmd: int, value: float = 0.0) -> bytes:
    """One command frame: `cmd`, `value` as little-endian float32, `\\r\\n`."""
    if not 0 <= cmd <= 0xFF:
        raise ValueError(f"command {cmd} is not one byte")
    return bytes([cmd]) + struct.pack("<f", float(value)) + b"\r\n"


class JsonStream:
    """Cuts complete JSON objects out of a byte stream that may split them anywhere, start
    mid-object, or carry noise between them. Broken objects are skipped (`dropped`)."""

    def __init__(self) -> None:
        self.buffer = ""
        self.dropped = 0

    def feed(self, data: bytes) -> list[dict[str, Any]]:
        self.buffer += data.decode("utf-8", errors="ignore")
        out: list[dict[str, Any]] = []
        while True:
            start = self.buffer.find("{")
            if start < 0:
                self.buffer = ""
                return out
            depth, end = 0, -1
            for i in range(start, len(self.buffer)):
                c = self.buffer[i]
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            if end < 0:  # incomplete: keep it, unless it can no longer be an object
                self.buffer = self.buffer[start:]
                if len(self.buffer) > MAX_BUFFER:
                    self.buffer, self.dropped = "", self.dropped + 1
                return out
            text = _TRAILING_COMMA.sub(r"\1", self.buffer[start : end + 1])
            self.buffer = self.buffer[end + 1 :]
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                self.dropped += 1
                continue
            if isinstance(value, dict):
                out.append(value)
            else:
                self.dropped += 1


def open_serial(port: str) -> Any:
    import serial

    return serial.Serial(port=port, baudrate=BAUDRATE, timeout=0.01)


class PikaSerial:
    """The device on `port`: a receive thread keeps the latest value of every top-level
    key and when it arrived (`clock`, monotonic seconds)."""

    def __init__(
        self,
        port: str,
        *,
        serial: Any | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.port, self.clock = port, clock
        try:
            self.serial = open_serial(port) if serial is None else serial
        except Exception as exc:
            raise ConnectionError(f"Pika on {port}: {exc}; {PORT_HINT}") from exc
        self.stream = JsonStream()
        self.lock = threading.Lock()
        self.values: dict[str, tuple[Any, float]] = {}
        self.counts: dict[str, int] = {}
        self.error: Exception | None = None  # what stopped the receive thread
        self.stopping = threading.Event()
        self.thread = threading.Thread(
            target=self._receive, name=f"pika:{port}", daemon=True
        )
        self.thread.start()

    def _receive(self) -> None:
        while not self.stopping.is_set():
            try:
                data = self.serial.read(max(1, int(self.serial.in_waiting or 0)))
            except Exception as exc:  # noqa: BLE001  unplugged: readers see the values go stale
                self.error = exc
                return
            if data:
                self.take(data)

    def take(self, data: bytes) -> None:
        """Parse received bytes (the receive thread calls this; tests may too)."""
        objects = self.stream.feed(data)
        if not objects:
            return
        now = self.clock()
        with self.lock:
            for obj in objects:
                for key, value in obj.items():
                    self.values[key] = (value, now)
                    self.counts[key] = self.counts.get(key, 0) + 1

    def latest(self, key: str) -> tuple[Any, float] | None:
        """The last value of `key` and its receive time, or None if it never came."""
        with self.lock:
            return self.values.get(key)

    def count(self, key: str) -> int:
        with self.lock:
            return self.counts.get(key, 0)

    def send(self, cmd: int, value: float = 0.0) -> None:
        self.serial.write(encode(cmd, value))

    def send_line(self, text: str) -> None:
        self.serial.write(text.encode() + b"\r\n")

    def close(self) -> None:
        self.stopping.set()
        if self.thread is not threading.current_thread():
            self.thread.join(timeout=1.0)
        self.serial.close()
