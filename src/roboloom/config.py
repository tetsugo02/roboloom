"""Experiment configuration: resolve node files, build validated specs, cross-check the graph.

The experiment YAML groups node files by role (`inputs`, `controllers`, `robots`,
`sensors`) plus the `recorder` and `session` services. Each node's `type` selects
its class from that role's registry. Nothing here opens a device.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .controllers import CONTROLLERS
from .controllers.base import Controller
from .core.checks import identity, positive
from .core.source import Recordable, Source
from .inputs import INPUTS
from .inputs.base import InputDevice
from .recording import features
from .robots import ROBOTS
from .robots.base import Robot
from .sensors import SENSORS

ROLES = ("inputs", "controllers", "robots", "sensors")
SERVICES = ("recorder", "session")
# Service node ids and fixed dora input ids; LeRobot key collisions are checked by `features`.
RESERVED = {*SERVICES, "action", "tick"}


@dataclass
class ExperimentConfig:
    robot_id: str
    repo_id: str
    output: str
    dataset_fps: float
    robots: dict[str, Robot]
    inputs: dict[str, InputDevice] = field(default_factory=dict)
    sensors: dict[str, Source] = field(default_factory=dict)
    controllers: dict[str, Controller] = field(default_factory=dict)
    max_age_ms: dict[str, float] = field(default_factory=dict)
    recorder: dict = field(default_factory=dict)
    mode: str = "mock"
    robot_type: str = ""
    path: str = ""

    @property
    def mock(self) -> bool:
        return self.mode == "mock"

    @property
    def robot(self) -> Robot:
        (robot,) = self.robots.values()
        return robot

    @property
    def sources(self) -> dict[str, Recordable]:
        """Recorded streams in dataset order."""
        return {**self.inputs, **self.robots, **self.sensors}

    def controller_for(self, robot: str) -> Controller:
        (controller,) = (c for c in self.controllers.values() if c.robot.name == robot)
        return controller


def _read(path: Path) -> dict:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise TypeError(f"{path}: expected YAML mapping")
    return data


def read_experiment(path: str | Path) -> dict:
    """Load the experiment YAML and every referenced node file into one tree."""
    path = Path(path).resolve()
    raw = _read(path)
    if isinstance(raw.get("output"), str) and raw["output"]:
        raw["output"] = str((path.parent / raw["output"]).resolve())
    tree: dict = {"path": str(path)}

    def node(relative: object, where: str) -> dict:
        if not isinstance(relative, str):
            raise TypeError(f"{where}: expected YAML path")
        file = (path.parent / relative).resolve()
        return {
            **_read(file),
            "__dir__": str(file.parent),
        }  # resolves files a node names, e.g. gravity models

    for role in ROLES:
        group = raw.pop(role, None) or {}
        if not isinstance(group, dict):
            raise TypeError(f"{role}: expected mapping of node name to YAML path")
        tree[role] = {
            name: node(relative, f"{role}.{name}") for name, relative in group.items()
        }
    for service in SERVICES:
        tree[service] = node(raw.pop(service, None), service)
    tree["experiment"] = raw
    return tree


PLACEHOLDER = "SET_"
PROJECT_ROOT = ".roboloom"


def placeholders(value: object, where: str = "") -> list[str]:
    """Locations of template values still to be measured or filled (strings starting SET_)."""
    if isinstance(value, str):
        return [f"{where}: {value}"] if value.startswith(PLACEHOLDER) else []
    if isinstance(value, dict):
        return [
            hit
            for k, v in value.items()
            if not str(k).startswith("__")
            for hit in placeholders(v, f"{where}.{k}" if where else str(k))
        ]
    if isinstance(value, list):
        return [
            hit for i, v in enumerate(value) for hit in placeholders(v, f"{where}[{i}]")
        ]
    return []


def resolve_experiment(arg: str | Path, root: str | Path = PROJECT_ROOT) -> Path:
    """An experiment file, or a name under the project root: `rakuda2` is
    `.roboloom/rakuda2/experiment.yaml`, `rakuda2/experiment_gravity` its sibling."""
    path = Path(arg)
    if path.is_file():
        return path
    for candidate in (
        Path(root) / path / "experiment.yaml",
        Path(root) / f"{path}.yaml",
    ):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"{arg}: no such experiment file, nor {Path(root) / path}/experiment.yaml "
        "(create one with `roboloom init <robot>`)"
    )


def parse_experiment(tree: dict) -> ExperimentConfig:
    missing = placeholders({k: v for k, v in tree.items() if k != "path"})
    if missing:
        raise ValueError(
            "template values still to fill (see the README next to the experiment):\n  "
            + "\n  ".join(missing)
        )
    e = tree["experiment"]
    robot_id = identity(e.get("robot_id"), "robot_id")
    repo_id = identity(e.get("repo_id"), "repo_id")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo_id):
        raise ValueError("repo_id must be namespace/name")
    if e.get("mode") not in ("mock", "hardware"):
        raise ValueError("mode must be mock or hardware")
    fps = positive(e.get("dataset_fps"), "dataset_fps")

    names = [name for role in ROLES for name in tree[role]]
    if len(set(names)) != len(names):
        raise ValueError("node names must be unique across roles")
    for name in names:
        if name in RESERVED or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ValueError(f"invalid node name {name!r}")

    robots = {
        name: ROBOTS.get(c.get("type"))(name, c) for name, c in tree["robots"].items()
    }
    if len(robots) != 1:
        raise ValueError("exactly one robot per experiment is supported for now")
    inputs = {
        name: INPUTS.get(c.get("type"))(name, c) for name, c in tree["inputs"].items()
    }
    sensors = {
        name: SENSORS.get(c.get("type"))(name, c) for name, c in tree["sensors"].items()
    }
    controllers = {}
    for name, c in tree["controllers"].items():
        source, robot = inputs.get(c.get("input")), robots.get(c.get("robot"))
        if source is None or robot is None:
            raise ValueError(
                f"controllers.{name} must reference a configured input and robot"
            )
        controllers[name] = CONTROLLERS.get(c.get("type"))(
            name, c, source, robot, robot_id
        )
    for robot in robots.values():
        if [c.robot.name for c in controllers.values()].count(robot.name) != 1:
            raise ValueError(f"robot {robot.name!r} needs exactly one controller")
        if robot.control_hz < fps:
            raise ValueError("control_hz must be >= dataset_fps")

    if e["mode"] == "hardware":
        for owner in [*inputs.values(), *robots.values()]:
            check = getattr(owner, "check_hardware", None)
            if check is not None:
                check()

    owners: list[Source | Robot] = [
        *inputs.values(),
        *robots.values(),
        *sensors.values(),
    ]
    devices = [d for spec in owners for d in spec.device_ids()]
    if len(set(devices)) != len(devices):
        raise ValueError("duplicate port or sensor ID")

    ages = tree["recorder"].get("max_age_ms", {})
    cfg = ExperimentConfig(
        robot_id=robot_id,
        repo_id=repo_id,
        output=identity(e.get("output"), "output"),
        dataset_fps=fps,
        robots=robots,
        inputs=inputs,
        sensors=sensors,
        controllers=controllers,
        max_age_ms={
            name: positive(ages.get(name), f"max_age_ms.{name}")
            for name in (*inputs, *robots, *sensors)
        },
        recorder={
            k: v
            for k, v in tree["recorder"].items()
            if k
            in ("grace_ms", "image_writer_threads", "streaming_encoding", "queue_s")
        },
        mode=e["mode"],
        robot_type=e.get("robot_type", next(iter(robots.values())).robot_type),
        path=tree["path"],
    )
    if tree["session"].get("type") != "terminal":
        raise ValueError("session must be terminal")
    features(cfg)  # rejects colliding LeRobot keys
    return cfg


def load_experiment(path: str | Path) -> ExperimentConfig:
    return parse_experiment(read_experiment(path))
