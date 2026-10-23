"""Periodic node status for the operator screen.

Every node publishes `kind="status"` messages on its `status` output:
`{"role", "level": ok|warn|error, "fields": {...}}`. Fields are plain JSON
values; the screen shows unknown fields as key=value, so a new robot or sensor
only has to add fields (and may register a renderer in `roboloom.ui.render`).
"""

from __future__ import annotations

import time

from .protocol import Envelope, Publisher

LEVELS = ("ok", "warn", "error")


class StatusReporter:
    def __init__(self, publisher: Publisher, role: str, period_s: float = 0.25):
        self.publisher, self.role = publisher, role
        self.period_ns = int(period_s * 1e9)
        self.last_ns: int | None = None

    def due(self, now_ns: int | None = None) -> bool:
        now = time.monotonic_ns() if now_ns is None else now_ns
        return self.last_ns is None or now - self.last_ns >= self.period_ns

    def maybe(self, fields: dict, level: str = "ok", now_ns: int | None = None) -> Envelope | None:
        """A status message when the period has passed, else None."""
        now = time.monotonic_ns() if now_ns is None else now_ns
        return self.make(fields, level, now) if self.due(now) else None

    def make(self, fields: dict, level: str = "ok", now_ns: int | None = None) -> Envelope:
        """A status message now; callers that build fields only when `due` use this."""
        now = time.monotonic_ns() if now_ns is None else now_ns
        if level not in LEVELS:
            raise ValueError(f"status level must be one of {LEVELS}")
        self.last_ns = now
        return self.publisher.make("status", {"role": self.role, "level": level, "fields": fields}, now)
