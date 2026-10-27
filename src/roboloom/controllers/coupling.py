"""Relative joint compensation in robot coordinates, independent of any robot model."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ..core.checks import finite
from ..errors import ConfigError


@dataclass(frozen=True)
class JointCoupling:
    joint: int
    source: int
    scale: float
    reference: float  # source position at which nothing is added
    lead_s: float = 0.0  # look ahead along the source velocity (target joint lag)


REQUIRED = {"joint", "source", "scale", "reference"}
MAX_LEAD_MS = 500  # a longer lead extrapolates past any motion a hand makes


class JointCouplings:
    """Add measured source displacement from a fixed reference to mapped targets.

    Every source is read from the same measured snapshot, never another modified target.
    The reference is configured, not latched at alignment: a latched pose would carry
    the leader-follower difference allowed by the alignment tolerance into the target.

    `lead_ms` (optional, default 0) adds source velocity x lead: the target joint's own
    position loop trails its goal while the source moves (Rakuda2 head: about 70 ms at
    60 deg/s torso rotation, 2026-10-27), so the goal is placed that far ahead.
    """

    def __init__(self, raw: object, joint_names: Sequence[str], owner: str) -> None:
        if not isinstance(raw, list):
            raise ConfigError(f"{owner}.couplings must be a list")
        links: list[JointCoupling] = []
        used: set[str] = set()
        for item in raw:
            if not isinstance(item, dict) or not (
                REQUIRED <= set(item) <= {*REQUIRED, "lead_ms"}
            ):
                raise ConfigError(
                    f"{owner}.couplings: each entry needs joint, source, scale and "
                    "reference (and may set lead_ms)"
                )
            joint, source = item["joint"], item["source"]
            scale, reference = item["scale"], item["reference"]
            if (
                not isinstance(joint, str)
                or not isinstance(source, str)
                or joint not in joint_names
                or source not in joint_names
            ):
                raise ConfigError(f"{owner}.couplings: unknown robot joint or source")
            if joint == source or joint in used:
                raise ConfigError(
                    f"{owner}.couplings: targets must be unique and differ from sources"
                )
            for value in (scale, reference):
                if not finite(value):
                    raise ConfigError(
                        f"{owner}.couplings: scale and reference must be finite"
                    )
            lead_ms = item.get("lead_ms", 0)
            if not finite(lead_ms) or not 0 <= lead_ms <= MAX_LEAD_MS:
                raise ConfigError(
                    f"{owner}.couplings: lead_ms must be 0..{MAX_LEAD_MS}"
                )
            links.append(
                JointCoupling(
                    joint_names.index(joint),
                    joint_names.index(source),
                    scale,
                    reference,
                    lead_ms / 1000,
                )
            )
            used.add(joint)
        self.links = tuple(links)

    def apply(
        self,
        target: Sequence[float],
        current: Sequence[float],
        velocity: Sequence[float] | None = None,
    ) -> list[float]:
        """`velocity` (units/s) feeds `lead_ms`; without it the lead is left out."""
        out = list(target)
        for link in self.links:
            source = current[link.source]
            if link.lead_s and velocity is not None:
                source += velocity[link.source] * link.lead_s
            out[link.joint] += link.scale * (source - link.reference)
        if not all(math.isfinite(value) for value in out):
            raise ValueError("coupled joint targets must be finite")
        return out
