"""Save the follower's current pose under a name, for `home` (`roboloom capture-pose`)."""

from __future__ import annotations

import re
import time
from pathlib import Path

import yaml

from ..config import load_experiment
from ..errors import ConfigError, SetupError
from .common import require_hardware


def pose_path(experiment_path: str | Path, name: str) -> Path:
    """`poses/<name>.yaml` next to the experiment (the robot's `.roboloom/<robot>/`)."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ConfigError(f"pose name {name!r}: use letters, digits, - and _")
    return Path(experiment_path).parent / "poses" / f"{name}.yaml"


def capture_pose(
    experiment: str | Path,
    name: str,
    *,
    hardware: bool = False,
    force: bool = False,
) -> Path:
    """Read the experiment's follower positions and save them as pose `name`.

    Moves nothing: the bus opens with the robot's usual startup checks, positions are
    read, and the bus closes. The dataflow must not be running (it owns the bus); pose
    the follower by teleoperation (then `quit` with `hold`) or by hand after `release`.
    Every joint must be inside the robot's limits. Returns the written file.
    """
    cfg = load_experiment(experiment)
    if not cfg.mock:
        require_hardware(cfg, hardware, "capture-pose")
    robot = cfg.robot
    path = pose_path(cfg.path, name)
    if path.exists() and not force:
        raise SetupError(f"{path} exists; pass force=True (--force) to replace it")
    bus = robot.open_bus(cfg.mock)
    try:
        values = [float(x) for x in bus.read_positions()]
    finally:
        bus.close()
    outside = [
        f"{joint}={value:.0f} not in [{limit['min']}, {limit['max']}]"
        for joint, value, limit in zip(
            robot.joint_names, values, robot.limits, strict=True
        )
        if not limit["min"] <= value <= limit["max"]
    ]
    if outside:
        raise SetupError("pose outside the robot limits: " + "; ".join(outside))
    port = getattr(robot, "port", "")
    header = (
        f"# roboloom capture-pose {time.strftime('%Y-%m-%d %H:%M')}, robot "
        f"`{robot.name}`{f' ({port})' if port else ''}.\n"
        f"# Select it in the controller YAML: home: {{pose: ../poses/{name}.yaml, ...}}\n"
    )
    body = {
        "robot_type": robot.robot_type,
        "unit": robot.unit,
        "pose": {
            j: round(v) if robot.unit == "dynamixel_count" else v
            for j, v in zip(robot.joint_names, values, strict=True)
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + yaml.safe_dump(body, sort_keys=False))
    return path
