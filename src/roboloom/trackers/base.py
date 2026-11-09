"""Tracking systems: one node owns the hardware and publishes every tracked pose."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

from ..core.checks import positive


@dataclass(frozen=True)
class TrackedPose:
    """One tracked object's latest pose in the system's world frame.

    `position` in m, `quaternion` x, y, z, w (unit). `t_ns` is when the tracker node
    received it (`time.monotonic_ns`, one clock for every process on the machine), so a
    reader judges staleness itself. `tracking` is False when the system reports the
    object lost; the pose is then the last tracked one, not to be followed."""

    position: tuple[float, float, float]
    quaternion: tuple[float, float, float, float]
    t_ns: int
    tracking: bool = True


class TrackerReader(Protocol):
    """An opened tracking system."""

    def read(self) -> dict[str, TrackedPose]:
        """The latest pose of every object seen so far, by serial number."""
        ...

    def status(self) -> dict[str, Any]: ...
    def close(self) -> None: ...


class MockTrackerReader:
    """No hardware: no object is ever seen (mock inputs make up their own poses)."""

    def read(self) -> dict[str, TrackedPose]:
        return {}

    def status(self) -> dict[str, Any]:
        return {"objects": 0}

    def close(self) -> None:
        pass


class Tracker(ABC):
    """Validated description of one tracking system. Constructing it opens nothing.

    Keys every system takes: `type`, `poll_hz` (optional: how often the poses are
    published; by default as fast as the fastest input that reads it)."""

    kind: ClassVar[str] = "tracked_poses"
    keys: ClassVar[tuple[str, ...]] = ("type", "poll_hz")

    def __init__(self, name: str, cfg: dict):
        self.name, self.cfg = name, cfg
        unknown = sorted(
            k for k in cfg if not k.startswith("__") and k not in self.keys
        )
        if unknown:
            raise ValueError(
                f"trackers.{name}: unknown keys {unknown} (allowed: {', '.join(self.keys)})"
            )
        self.rate_hz()

    def rate_hz(self) -> float | None:
        poll = self.cfg.get("poll_hz")
        return None if poll is None else positive(poll, f"trackers.{self.name}.poll_hz")

    def device_ids(self) -> tuple[str, ...]:
        """Devices this system owns exclusively (e.g. its USB receiver)."""
        return ()

    @abstractmethod
    def open(self, mock: bool) -> TrackerReader: ...

    @staticmethod
    def encode(poses: dict[str, TrackedPose]) -> dict:
        return {
            "poses": {
                serial: {
                    "position": list(p.position),
                    "quaternion": list(p.quaternion),
                    "t_ns": p.t_ns,
                    "tracking": p.tracking,
                }
                for serial, p in poses.items()
            }
        }

    @staticmethod
    def decode(payload: dict) -> dict[str, TrackedPose]:
        out = {}
        for serial, p in (payload.get("poses") or {}).items():
            position = tuple(float(v) for v in p["position"])
            quaternion = tuple(float(v) for v in p["quaternion"])
            if len(position) != 3 or len(quaternion) != 4:
                raise ValueError(f"tracked pose of {serial!r}: wrong length")
            out[serial] = TrackedPose(
                position,  # type: ignore[arg-type]
                quaternion,  # type: ignore[arg-type]
                int(p["t_ns"]),
                bool(p["tracking"]),
            )
        return out


def unit_quaternion(
    q: tuple[float, float, float, float] | list[float],
) -> tuple[float, float, float, float] | None:
    """`q` normalized, or None when it is not a rotation: not finite, or (nearly) zero,
    which is how libsurvive reports a lost object."""
    if len(q) != 4 or not all(math.isfinite(v) for v in q):
        return None
    norm = math.sqrt(sum(v * v for v in q))
    if norm < 0.5:
        return None
    x, y, z, w = (v / norm for v in q)
    return (x, y, z, w)
