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


class JointCouplings:
    """Add measured source displacement from a fixed reference to mapped targets.

    Every source is read from the same measured snapshot, never another modified target.
    The reference is configured, not latched at alignment: a latched pose would carry
    the leader-follower difference allowed by the alignment tolerance into the target.
    """

    def __init__(self, raw: object, joint_names: Sequence[str], owner: str) -> None:
        if not isinstance(raw, list):
            raise ConfigError(f"{owner}.couplings must be a list")
        links: list[JointCoupling] = []
        used: set[str] = set()
        for item in raw:
            if not isinstance(item, dict) or set(item) != {
                "joint",
                "source",
                "scale",
                "reference",
            }:
                raise ConfigError(
                    f"{owner}.couplings: each entry needs joint, source, scale and reference"
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
            links.append(
                JointCoupling(
                    joint_names.index(joint),
                    joint_names.index(source),
                    scale,
                    reference,
                )
            )
            used.add(joint)
        self.links = tuple(links)

    def apply(self, target: Sequence[float], current: Sequence[float]) -> list[float]:
        out = list(target)
        for link in self.links:
            out[link.joint] += link.scale * (current[link.source] - link.reference)
        if not all(math.isfinite(value) for value in out):
            raise ValueError("coupled joint targets must be finite")
        return out
