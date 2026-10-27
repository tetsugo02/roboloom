"""Slow, synchronized moves to a saved pose (home), shared by followers and leaders."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..core.checks import finite, positive
from ..errors import ConfigError


class Trajectory:
    """Every joint from `start` to `goal` in the same time, on a cosine profile.

    The duration is chosen so the fastest joint peaks at `max_speed` (units/s): a cosine
    move of distance d over T peaks at (pi/2) d / T.
    """

    def __init__(
        self, start: Sequence[float], goal: Sequence[float], max_speed: float
    ) -> None:
        if len(start) != len(goal):
            raise ValueError("trajectory start and goal differ in length")
        self.start, self.goal = [float(x) for x in start], [float(x) for x in goal]
        distance = max(
            (abs(g - s) for s, g in zip(start, goal, strict=True)), default=0
        )
        self.duration_s = math.pi / 2 * distance / positive(max_speed, "max_speed")

    def at(self, elapsed_s: float) -> list[float]:
        if self.duration_s <= 0 or elapsed_s >= self.duration_s:
            return list(self.goal)
        phase = (1 - math.cos(math.pi * max(0.0, elapsed_s) / self.duration_s)) / 2
        return [s + (g - s) * phase for s, g in zip(self.start, self.goal, strict=True)]

    def progress(self, elapsed_s: float) -> float:
        return (
            1.0
            if self.duration_s <= 0
            else min(1.0, max(0.0, elapsed_s) / self.duration_s)
        )


@dataclass(frozen=True)
class Pose:
    """A saved follower pose (`roboloom capture-pose`), one value per robot joint."""

    name: str
    values: dict[str, float]


def load_pose(
    path: Path,
    robot_type: str,
    unit: str,
    joint_names: Sequence[str],
    limits: Sequence[dict],
) -> Pose:
    if not path.is_file():
        raise ConfigError(
            f"{path}: no such pose (save one with `roboloom capture-pose`)"
        )
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict) or not isinstance(data.get("pose"), dict):
        raise ConfigError(f"{path}: expected robot_type, unit and pose")
    if data.get("robot_type") != robot_type or data.get("unit") != unit:
        raise ConfigError(
            f"{path}: saved for {data.get('robot_type')} in {data.get('unit')}, "
            f"not {robot_type} in {unit}"
        )
    values = data["pose"]
    if set(values) != set(joint_names):
        missing = sorted(set(joint_names) - set(values))
        extra = sorted(set(values) - set(joint_names))
        raise ConfigError(f"{path}: joints differ (missing {missing}, unknown {extra})")
    for joint, limit in zip(joint_names, limits, strict=True):
        value = values[joint]
        if not finite(value) or not limit["min"] <= value <= limit["max"]:
            raise ConfigError(
                f"{path}: {joint}={value} outside [{limit['min']}, {limit['max']}]"
            )
    return Pose(path.stem, {j: float(values[j]) for j in joint_names})


@dataclass(frozen=True)
class HomeSpec:
    """`home:` of a controller: which saved pose, how fast, when it counts as reached."""

    pose: Pose
    max_speed: float
    tolerance: float
    timeout_s: float

    def target(self, joint_names: Sequence[str]) -> list[float]:
        return [self.pose.values[j] for j in joint_names]


def parse_home(
    raw: object,
    owner: str,
    base_dir: str | None,
    robot,
    speed_limit: float,
) -> HomeSpec | None:
    if raw is None:
        return None
    keys = {"pose", "max_speed", "tolerance", "timeout_s"}
    if not isinstance(raw, dict) or not {"pose", "max_speed"} <= set(raw) <= keys:
        raise ConfigError(
            f"{owner}.home needs pose and max_speed (and may set tolerance, timeout_s)"
        )
    if not isinstance(raw["pose"], str):
        raise ConfigError(f"{owner}.home.pose must be a path to a saved pose")
    try:
        max_speed = positive(raw["max_speed"], f"{owner}.home.max_speed")
        tolerance = positive(raw.get("tolerance", 30), f"{owner}.home.tolerance")
        timeout_s = positive(raw.get("timeout_s", 30), f"{owner}.home.timeout_s")
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    if max_speed > speed_limit:
        raise ConfigError(
            f"{owner}.home.max_speed {max_speed} exceeds max_speed_counts_per_s {speed_limit}"
        )
    path = Path(base_dir or ".") / raw["pose"]
    pose = load_pose(
        path.resolve(),
        robot.robot_type,
        robot.unit,
        robot.joint_names,
        robot.limits,
    )
    return HomeSpec(pose, max_speed, tolerance, timeout_s)
