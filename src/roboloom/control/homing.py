"""Slow, synchronized moves to a saved pose (home), shared by followers and leaders."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from ..core.checks import finite, positive
from ..errors import ConfigError

if TYPE_CHECKING:
    from ..config import RobotConfig


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
    """A saved follower pose (`roboloom capture-pose`), one value per follower joint."""

    name: str
    values: dict[str, float]


def load_pose(
    path: Path,
    follower: str,
    model: str,
    unit: str,
    joint_names: Sequence[str],
    limits: Sequence[dict],
) -> Pose:
    if not path.is_file():
        raise ConfigError(
            f"{path}: no such pose (save one with `roboloom capture-pose`)"
        )
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except UnicodeError as exc:
        raise ConfigError(f"{path}: pose file must be UTF-8 text") from exc
    if not isinstance(data, dict) or not isinstance(data.get("pose"), dict):
        raise ConfigError(f"{path}: expected follower, model, unit and pose")
    if data.get("follower") != follower:
        raise ConfigError(
            f"{path}: saved for follower {data.get('follower')!r}, not {follower!r} "
            "(a pose belongs to the follower it was captured on)"
        )
    if data.get("model") != model or data.get("unit") != unit:
        raise ConfigError(
            f"{path}: saved for {data.get('model')} in {data.get('unit')}, "
            f"not {model} in {unit}"
        )
    values = data["pose"]
    if set(values) != set(joint_names):
        missing = sorted(set(joint_names) - set(values))
        extra = sorted(set(values) - set(joint_names), key=str)
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

    poses: Mapping[str, Pose] = field(default_factory=dict)
    invalid: Mapping[str, str] = field(default_factory=dict)
    choices: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if not self.poses:
            object.__setattr__(self, "poses", {self.pose.name: self.pose})

    def get(self, name: str | None = None) -> Pose:
        if not name:
            return self.pose
        if name in self.poses:
            return self.poses[name]
        if name in self.invalid:
            raise ConfigError(f"invalid home pose {name!r}: {self.invalid[name]}")
        raise ConfigError(f"unknown home pose {name!r}")

    def target(
        self, joint_names: Sequence[str], name: str | None = None
    ) -> list[float]:
        pose = self.get(name)
        return [pose.values[j] for j in joint_names]

    def estimate(
        self,
        current: Sequence[float],
        joint_names: Sequence[str],
        name: str | None = None,
    ) -> dict[str, object]:
        diffs = [
            abs(g - c)
            for g, c in zip(self.target(joint_names, name), current, strict=True)
        ]
        worst = max(range(len(diffs)), key=diffs.__getitem__)
        eta = math.pi / 2 * diffs[worst] / self.max_speed
        return {
            "worst_joint": joint_names[worst],
            "dist": round(diffs[worst], 4),
            "eta_s": round(eta, 1),
            "over_timeout": eta > self.timeout_s,
        }


def parse_home(
    raw: object,
    owner: str,
    base_dir: str | None,
    robot,
    speed_limit: float,
) -> HomeSpec | None:
    if raw is None:
        return None
    keys = {"pose", "max_speed", "tolerance", "timeout_s", "choices"}
    if (
        not isinstance(raw, dict)
        or not {"pose", "max_speed", "tolerance"} <= set(raw) <= keys
    ):
        raise ConfigError(
            f"{owner}.home needs pose, max_speed and tolerance (in the follower's "
            "unit; it may set timeout_s and choices)"
        )
    if not isinstance(raw["pose"], str):
        raise ConfigError(f"{owner}.home.pose must be a path to a saved pose")
    try:
        max_speed = positive(raw["max_speed"], f"{owner}.home.max_speed")
        tolerance = positive(raw.get("tolerance"), f"{owner}.home.tolerance")
        timeout_s = positive(raw.get("timeout_s", 30), f"{owner}.home.timeout_s")
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    if max_speed > speed_limit:
        raise ConfigError(
            f"{owner}.home.max_speed {max_speed} exceeds the controller's max_speed "
            f"{speed_limit} ({robot.unit}/s)"
        )
    choices = None
    if "choices" in raw:
        names = raw["choices"]
        if (
            not isinstance(names, list)
            or not names
            or any(
                not isinstance(name, str) or not name or "/" in name or "\\" in name
                for name in names
            )
        ):
            raise ConfigError(
                f"{owner}.home.choices must be a non-empty list of pose names"
            )
        choices = tuple(names)

    path = Path(base_dir or ".") / raw["pose"]
    pose_args = (robot.name, robot.model, robot.unit, robot.joint_names, robot.limits)
    try:
        path = path.resolve()
        pose = load_pose(path, *pose_args)
    except (yaml.YAMLError, OSError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    if choices is not None and pose.name not in choices:
        raise ConfigError(
            f"{owner}.home.choices must include the default pose {pose.name!r}"
        )

    poses = {pose.name: pose}
    invalid: dict[str, str] = {}
    candidates = (
        sorted(path.parent.glob("*.yaml"), key=lambda candidate: candidate.stem)
        if choices is None
        else [path.parent / f"{name}.yaml" for name in sorted(set(choices))]
    )
    for candidate in candidates:
        name = candidate.stem
        if name == pose.name:
            continue
        try:
            if choices is not None and not candidate.is_file():
                invalid[name] = "no such pose"
                continue
            poses[name] = load_pose(candidate, *pose_args)
        except (ConfigError, yaml.YAMLError, OSError) as exc:
            invalid[name] = str(exc)
    return HomeSpec(pose, max_speed, tolerance, timeout_s, poses, invalid, choices)


def available_homes(cfg: RobotConfig) -> tuple[tuple[str, ...], dict[str, str], str]:
    """Named poses that every configured homing follower can use together."""
    homes = [
        (follower, spec)
        for c in cfg.controllers.values()
        for follower, spec in c.homes.items()
    ]
    if not homes:
        return (), {}, ""

    defaults = {spec.pose.name for _, spec in homes}
    default = next(iter(defaults)) if len(defaults) == 1 else ""
    common = set.intersection(*(set(spec.poses) for _, spec in homes))
    valid = tuple(sorted(common, key=lambda name: (name != default, name)))
    seen = {name for _, spec in homes for name in (*spec.poses, *spec.invalid)}
    invalid = {}
    for name in sorted(seen - common):
        for follower, spec in homes:
            if name not in spec.poses:
                invalid[name] = f"{follower}: {spec.invalid.get(name, 'missing pose')}"
                break
    return valid, invalid, default
