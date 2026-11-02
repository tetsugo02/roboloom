"""Save a follower's current pose under a name, for `home` (`roboloom capture-pose`)."""

from __future__ import annotations

import re
import time
from pathlib import Path

import yaml

from ..config import RobotConfig
from ..errors import ConfigError, SetupError
from .common import load


def pose_path(config_path: str | Path, follower: str, name: str) -> Path:
    """`poses/<follower>/<name>.yaml` next to the configuration (the robot's
    `.roboloom/<robot>/`). Each follower keeps its own poses: a pose saved on the left
    arm never loads on the right one."""
    for word, what in ((follower, "follower"), (name, "pose name")):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", word):
            raise ConfigError(f"{what} {word!r}: use letters, digits, - and _")
    return Path(config_path).parent / "poses" / follower / f"{name}.yaml"


def capture_pose(
    config: str | Path | RobotConfig,
    name: str,
    *,
    follower: str | None = None,
    force: bool = False,
) -> Path:
    """Read a follower's positions and save them as pose `name`.

    `follower`: which follower node (may be omitted when the robot has only one).
    Moves nothing: the bus opens with the follower's usual startup checks, positions
    are read, and the bus closes. The dataflow must not be running (it owns the bus);
    pose the follower by teleoperation (then `quit` with `hold`) or by hand after
    `release`. Every joint must be inside the follower's limits. Returns the written
    file.
    """
    cfg = load(config)
    if follower is None:
        if len(cfg.followers) != 1:
            raise ConfigError(
                f"name the follower to capture: one of {', '.join(cfg.followers)}"
            )
        (follower,) = cfg.followers
    if follower not in cfg.followers:
        raise ConfigError(
            f"no follower {follower!r}; followers: {', '.join(cfg.followers)}"
        )
    robot = cfg.followers[follower]
    path = pose_path(cfg.path, follower, name)
    if path.exists() and not force:
        raise SetupError(f"{path} exists; pass force=True (--force) to replace it")
    bus = robot.open_bus(cfg.mock)
    try:
        values = [float(x) for x in bus.read_positions()]
    finally:
        bus.close()
    outside = [
        f"{joint}={value:g} not in [{limit['min']}, {limit['max']}]"
        for joint, value, limit in zip(
            robot.joint_names, values, robot.limits, strict=True
        )
        if not limit["min"] <= value <= limit["max"]
    ]
    if outside:
        raise SetupError(f"pose outside the {follower} limits: " + "; ".join(outside))
    port = getattr(robot, "port", "")
    header = (
        f"# roboloom capture-pose {time.strftime('%Y-%m-%d %H:%M')}, follower "
        f"`{robot.name}`{f' ({port})' if port else ''}.\n"
        f"# Select it in the controller YAML: "
        f"home: {{pose: ../poses/{follower}/{name}.yaml, ...}}\n"
    )
    body = {
        "follower": robot.name,
        "model": robot.model,
        "unit": robot.unit,
        "pose": {
            j: round(v) if robot.unit == "dynamixel_count" else v
            for j, v in zip(robot.joint_names, values, strict=True)
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + yaml.safe_dump(body, sort_keys=False))
    return path
