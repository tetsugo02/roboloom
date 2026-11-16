"""Robot configuration: resolve node files, build validated specs, cross-check the graph.

The configuration YAML (`.roboloom/<robot>/config.yaml`) groups node files by role
(`inputs`, `controllers`, `followers`, `sensors`, `estimators`) plus the `recorder` and
`session` services. Each node's `type` selects its class from that role's registry. Its
`options:` are features chosen at launch (gravity compensation, extra sensors, ...); each
replaces, adds or removes node files. Nothing here opens a device.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .controllers import CONTROLLERS
from .controllers.base import Controller
from .core.checks import identity, positive, unknown_keys
from .core.source import Recordable, Source
from .errors import ConfigError
from .estimators import ESTIMATORS
from .estimators.base import Estimator
from .inputs import INPUTS
from .inputs.base import InputDevice
from .recording import features
from .recording.metrics import QUALITY
from .recording.video import normalize_video_codec
from .robots import FOLLOWERS
from .robots.base import Follower
from .sensors import SENSORS
from .trackers import TRACKERS
from .trackers.base import Tracker

ROLES = ("trackers", "inputs", "controllers", "followers", "sensors", "estimators")
SERVICES = ("recorder", "session")
# Service node ids and fixed dora input ids; LeRobot key collisions are checked by `features`.
RESERVED = {*SERVICES, "action", "tick"}
RESERVED_PREFIXES = ("action_",)  # the recorder's per-follower action inputs
RESERVED_SUFFIXES = ("_status",)  # the session's per-node status inputs
# top-level keys of config.yaml besides the roles and services; anything else is refused
SETTINGS = ("repo_id", "output", "dataset_fps", "mode")
RENAMED = {
    "robot_id": "the robot's name is its directory (.roboloom/<robot>/); remove robot_id",
    "robot_type": "the dataset's robot type is the robot's directory name; remove it",
    "robots": "renamed to followers",
}
# the keys of the recorder's and the session's node files
RECORDER_KEYS = (
    "max_age_ms",
    "grace_ms",
    "image_writer_threads",
    "streaming_encoding",
    "queue_s",
    "video_codec",
    "quality",
)
SESSION_KEYS = ("type",)
CONFIG_FILE = "config.yaml"
INFER_OPTION = "policy"  # `infer` turns on the option of this name when one is declared
NO_OPTIONS = (
    "."  # ROBOLOOM_OPTIONS when none is enabled (an empty value may be dropped)
)
OPTION_KEYS = {"help", "default", "requires", "conflicts", "set", "dataset"}


@dataclass(frozen=True)
class Option:
    """One launch-time feature. `set` maps `<role>.<node>` to a node file (relative to the
    configuration), or to None to remove that node. `dataset` is appended to the dataset
    name while the option is on (required when it changes the recorded features)."""

    name: str
    help: str = ""
    default: bool = False
    requires: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    set: dict[str, str | None] = field(default_factory=dict)
    dataset: str = ""


def parse_options(raw: object) -> dict[str, Option]:
    """The `options:` mapping of a configuration, validated (no files are read)."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError("options: expected mapping of option name to settings")
    out: dict[str, Option] = {}
    for name, spec in raw.items():
        where = f"options.{name}"
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ConfigError(f"{where}: invalid option name")
        if not isinstance(spec, dict):
            raise ConfigError(f"{where}: expected mapping")
        unknown = set(spec) - OPTION_KEYS
        if unknown:
            raise ConfigError(f"{where}: unknown keys {sorted(unknown)}")
        changes = spec.get("set") or {}
        if not isinstance(changes, dict):
            raise ConfigError(f"{where}.set: expected mapping of <role>.<node> to file")
        for key, value in changes.items():
            role, _, node = str(key).partition(".")
            if role not in ROLES or not node:
                raise ConfigError(
                    f"{where}.set.{key}: expected <role>.<node>, role one of {ROLES}"
                )
            if value is not None and not isinstance(value, str):
                raise ConfigError(f"{where}.set.{key}: expected a file path or null")
        lists = {}
        for key in ("requires", "conflicts"):
            value = spec.get(key) or []
            if not isinstance(value, list) or not all(
                isinstance(v, str) for v in value
            ):
                raise ConfigError(f"{where}.{key}: expected a list of option names")
            lists[key] = tuple(value)
        dataset = spec.get("dataset") or ""
        if not isinstance(dataset, str) or (
            dataset and not re.fullmatch(r"[A-Za-z0-9_.-]+", dataset)
        ):
            raise ConfigError(f"{where}.dataset: expected a short name such as digit")
        default = spec.get("default", False)
        if not isinstance(default, bool):
            raise ConfigError(f"{where}.default: expected true or false")
        out[name] = Option(
            name=name,
            help=str(spec.get("help") or ""),
            default=default,
            requires=lists["requires"],
            conflicts=lists["conflicts"],
            set={str(k): v for k, v in changes.items()},
            dataset=dataset,
        )
    for option in out.values():
        for other in (*option.requires, *option.conflicts):
            if other not in out:
                raise ConfigError(f"options.{option.name}: unknown option {other!r}")
    check_options(out, {n for n, o in out.items() if o.default})
    return out


EXPERIMENT_DIR = Path("configs") / "roboloom"  # in the project, next to .roboloom/
RUN_KEYS = ("task", "seconds", "steps", "episodes", "home")
EXPERIMENT_KEYS = ("help", "robot", "options", "dataset", "nodes", *RUN_KEYS)
DATASET_KEYS = ("root", "repo_id")
# What an experiment may not change: the followers hold the limits every command is
# checked against (range, speed, jump), the last guard before the motors.
FIXED_ROLES = ("followers",)


@dataclass(frozen=True)
class Experiment:
    """One experiment: which robot and launch options, what its nodes are given on top
    of their files (the policy and its checkpoint, a leader variant), where the episodes
    go, and how `roboloom infer|record --experiment` runs it. It lives outside the
    robot's directory, by default in `configs/roboloom/<name>.yaml` of the project.
    None: not given (the command line, the robot's configuration or a default decides)."""

    name: str
    robot: str | None = None
    options: tuple[str, ...] | None = None
    # `<role>.<node>` -> a node file of the robot's directory (replaces the node's
    # file) or a mapping laid over the node's settings (`overlay`)
    nodes: Mapping[str, str | Mapping[str, Any]] = field(default_factory=dict)
    dataset: Mapping[str, str] = field(default_factory=dict)  # root (absolute), repo_id
    task: str | None = None
    seconds: float | None = None
    episodes: int | None = None
    home: bool | None = None
    steps: int | None = None  # policy actions per episode, instead of seconds

    def settings(self) -> dict[str, Any]:
        """What the nodes of the dataflow need to load the configuration as the
        launching process did (`read_config(experiment=...)`); plain data."""
        return {
            "name": self.name,
            "nodes": {
                k: v if isinstance(v, str) else dict(v) for k, v in self.nodes.items()
            },
            "dataset": dict(self.dataset),
        }


def experiment_path(name: str | Path, root: str | Path = ".") -> Path:
    """The file of the experiment `name`: a path when it has a directory or ends in
    .yaml, else `configs/roboloom/<name>.yaml` under `root` (the project)."""
    text = str(name)
    if "/" in text or text.endswith((".yaml", ".yml")):
        path = Path(text).expanduser()
    else:
        path = Path(root) / EXPERIMENT_DIR / f"{text}.yaml"
    if not path.is_file():
        directory = Path(root) / EXPERIMENT_DIR
        known = (
            sorted(f.stem for f in directory.glob("*.yaml"))
            if directory.is_dir()
            else []
        )
        raise ConfigError(
            f"no experiment {text!r} ({path}); in {directory}: "
            f"{', '.join(known) or 'none'}"
        )
    return path


def load_experiment(
    source: str | Path | Mapping[str, Any], root: str | Path = "."
) -> Experiment:
    """An experiment from its name or file (`experiment_path`), or from a mapping with
    the same keys (e.g. what Hydra composed). `dataset.root` is taken from `root`, the
    project's directory (default: where the command runs)."""
    if isinstance(source, Mapping):
        raw, name, where = (
            dict(source),
            str(source.get("name", "experiment")),
            "experiment",
        )
        raw.pop("name", None)
    else:
        file = experiment_path(source, root)
        loaded = yaml.safe_load(file.read_text()) or {}
        if not isinstance(loaded, dict):
            raise ConfigError(f"{file}: expected a mapping")
        raw, name, where = loaded, file.stem, str(file)
    unknown_keys(raw, EXPERIMENT_KEYS, where)
    robot = raw.get("robot")
    if robot is not None and not isinstance(robot, str):
        raise ConfigError(f"{where}.robot: expected the robot's name")
    options = raw.get("options")
    if options is not None and (
        not isinstance(options, list) or not all(isinstance(o, str) for o in options)
    ):
        raise ConfigError(f"{where}.options: expected a list of option names")
    nodes = raw.get("nodes") or {}
    if not isinstance(nodes, dict):
        raise ConfigError(
            f"{where}.nodes: expected mapping of <role>.<node> to settings"
        )
    for key, value in nodes.items():
        role, _, node = str(key).partition(".")
        if role not in ROLES or not node:
            raise ConfigError(
                f"{where}.nodes.{key}: expected <role>.<node>, role one of {ROLES}"
            )
        if role in FIXED_ROLES:
            raise ConfigError(
                f"{where}.nodes.{key}: an experiment does not change a follower (its "
                "limits guard every command); edit the robot's node file"
            )
        if not isinstance(value, str | dict):
            raise ConfigError(
                f"{where}.nodes.{key}: expected a node file of the robot, or a mapping "
                "of settings laid over the node's"
            )
    dataset = raw.get("dataset") or {}
    if not isinstance(dataset, dict):
        raise ConfigError(f"{where}.dataset: expected a mapping with root and repo_id")
    unknown_keys(dataset, DATASET_KEYS, f"{where}.dataset")
    for key, value in dataset.items():
        if not isinstance(value, str) or not value:
            raise ConfigError(f"{where}.dataset.{key}: expected text")
    placed = dict(dataset)
    if "root" in placed:
        base = Path(placed["root"]).expanduser()
        placed["root"] = str(
            base if base.is_absolute() else (Path(root) / base).resolve()
        )
    task, seconds, steps = raw.get("task"), raw.get("seconds"), raw.get("steps")
    episodes, home = raw.get("episodes"), raw.get("home")
    if task is not None and not isinstance(task, str):
        raise ConfigError(f"{where}.task: expected text")
    if seconds is not None and (
        isinstance(seconds, bool)
        or not isinstance(seconds, int | float)
        or seconds <= 0
    ):
        raise ConfigError(f"{where}.seconds: expected a positive number")
    if episodes is not None and (
        isinstance(episodes, bool) or not isinstance(episodes, int) or episodes < 1
    ):
        raise ConfigError(f"{where}.episodes: expected a whole number, at least 1")
    if home is not None and not isinstance(home, bool):
        raise ConfigError(f"{where}.home: expected true or false")
    if steps is not None and (
        isinstance(steps, bool) or not isinstance(steps, int) or steps < 1
    ):
        raise ConfigError(f"{where}.steps: expected a whole number, at least 1")
    if steps is not None and seconds is not None:
        raise ConfigError(
            f"{where}: write seconds or steps (the policy's actions), not both"
        )
    return Experiment(
        name=name,
        robot=robot,
        options=None if options is None else tuple(options),
        nodes={str(k): v for k, v in nodes.items()},
        dataset=placed,
        task=task,
        seconds=None if seconds is None else float(seconds),
        episodes=episodes,
        home=home,
        steps=steps,
    )


def declared_options(config: str | Path, raw: object = None) -> dict[str, Option]:
    """The launch options of the configuration file `config` (`raw`: its `options:`
    when the file was already read). No node file is read."""
    if raw is None:
        raw = (yaml.safe_load(Path(config).read_text()) or {}).get("options")
    return parse_options(raw)


def requirements(options: dict[str, Option], name: str) -> set[str]:
    """The options `name` requires, transitively."""
    seen: set[str] = set()
    todo = list(options[name].requires)
    while todo:
        item = todo.pop()
        if item not in seen:
            seen.add(item)
            todo.extend(options[item].requires)
    return seen


def _known(options: dict[str, Option], names: Iterable[str]) -> list[str]:
    names = list(names)
    unknown = sorted(set(names) - set(options))
    if unknown:
        known = ", ".join(options) or "none"
        raise ConfigError(f"unknown options {unknown}; available: {known}")
    return names


def select_options(
    options: dict[str, Option],
    add: Iterable[str] = (),
    remove: Iterable[str] = (),
    *,
    base: Iterable[str] | None = None,
) -> tuple[str, ...]:
    """The options to enable, in declaration order: `base` (default: each option's
    `default`); each of `add` is turned on with what it requires (turning off what
    conflicts with it), then each of `remove` off with what requires it. Raises
    ConfigError for unknown names or when the result is inconsistent."""
    add, remove = _known(options, add), _known(options, remove)
    chosen = (
        set(_known(options, base))
        if base is not None
        else {o.name for o in options.values() if o.default}
    )
    for name in add:
        chosen = toggle_option(options, chosen, name, True)
    if set(add) - chosen:  # a later one turned an earlier one off
        raise ConfigError(f"options {', '.join(add)} cannot be used together")
    for name in remove:
        chosen = toggle_option(options, chosen, name, False)
    return check_options(options, chosen)


def toggle_option(
    options: dict[str, Option], chosen: set[str], name: str, on: bool
) -> set[str]:
    """Turning an option on also turns on what it requires and off what conflicts with
    it; turning one off also turns off what requires it."""
    chosen = set(chosen)
    if not on:
        return chosen - {
            name,
            *(o for o in options if name in requirements(options, o)),
        }
    added = {name, *requirements(options, name)}
    for other, spec in options.items():
        if any(other in options[a].conflicts or a in spec.conflicts for a in added):
            chosen = toggle_option(options, chosen, other, False)
    return chosen | added


def check_options(options: dict[str, Option], chosen: Iterable[str]) -> tuple[str, ...]:
    """Validate a complete selection; returns it in declaration order."""
    chosen = set(_known(options, chosen))
    for name in sorted(chosen):
        missing = sorted(requirements(options, name) - chosen)
        if missing:
            raise ConfigError(f"option {name} requires {', '.join(missing)}")
        clash = sorted(
            other
            for other in chosen
            if other in options[name].conflicts or name in options[other].conflicts
        )
        if clash:
            raise ConfigError(f"option {name} cannot be used with {', '.join(clash)}")
    return tuple(name for name in options if name in chosen)


def option_changes(
    options: dict[str, Option], enabled: Iterable[str]
) -> dict[str, str | None]:
    """The node replacements of the enabled options. Two options setting one node
    differently is an error, unless one requires the other: the dependent one wins."""
    owner: dict[str, str] = {}
    out: dict[str, str | None] = {}
    for name in enabled:
        for key, value in options[name].set.items():
            if key in out and out[key] != value:
                previous = owner[key]
                if name in requirements(options, previous):
                    continue  # `previous` refines this one's setting
                if previous not in requirements(options, name):
                    raise ConfigError(
                        f"options {previous} and {name} both set {key}; make one "
                        "require the other or declare them as conflicts"
                    )
            out[key] = value
            owner[key] = name
    return out


def dataset_suffix(options: dict[str, Option], enabled: Iterable[str]) -> str:
    """`-a-b` for the enabled options with `dataset: a` and `dataset: b`."""
    names = [options[n].dataset for n in enabled if options[n].dataset]
    return "".join(f"-{n}" for n in names)


@dataclass
class RobotConfig:
    """A robot's validated configuration: its nodes by role and the recording settings.
    `robot` is the robot's name (the configuration's directory, e.g. `rakuda2`)."""

    robot: str
    repo_id: str
    output: str
    dataset_fps: float
    followers: dict[str, Follower]
    inputs: dict[str, InputDevice] = field(default_factory=dict)
    sensors: dict[str, Source] = field(default_factory=dict)
    controllers: dict[str, Controller] = field(default_factory=dict)
    estimators: dict[str, Estimator] = field(default_factory=dict)
    # tracking systems several inputs share (not recorded; see roboloom.trackers)
    trackers: dict[str, Tracker] = field(default_factory=dict)
    max_age_ms: dict[str, float] = field(default_factory=dict)
    recorder: dict = field(default_factory=dict)
    quality: dict = field(default_factory=dict)  # see recording.metrics.QUALITY
    mode: str = "hardware"
    path: str = ""
    options: tuple[str, ...] = ()  # enabled launch options, in declaration order
    available_options: dict[str, Option] = field(default_factory=dict)
    # the experiment it was loaded with (`Experiment.settings()`), if any
    experiment: dict | None = None

    @property
    def mock(self) -> bool:
        return self.mode == "mock"

    @property
    def sources(self) -> dict[str, Recordable]:
        """Recorded streams in dataset order."""
        recorded = {n: e for n, e in self.estimators.items() if e.record}
        return {**self.inputs, **self.followers, **self.sensors, **recorded}

    def controller_for(self, follower: str) -> Controller:
        """The controller that drives `follower` (every follower has exactly one)."""
        (controller,) = (
            c for c in self.controllers.values() if follower in c.followers
        )
        return controller


def _read(path: Path) -> dict:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise TypeError(f"{path}: expected YAML mapping")
    return data


EXTENDS, WITHOUT = "extends", "without"  # keys of a node file, gone once it is read
IDENTITY = ("group", "name")  # what names the entries of `control` and `limits`


def _identity(items: object) -> str | None:
    """The key that names every entry of a list of mappings, if one does."""
    if not isinstance(items, list) or not items:
        return None
    for key in IDENTITY:
        if all(isinstance(item, dict) and key in item for item in items):
            names = [item[key] for item in items]
            if len(set(map(str, names))) == len(names):
                return key
    return None


def overlay(base: object, top: object) -> object:
    """`top` laid over `base`, as a node file over the one it extends: mappings merge
    key by key; a list of mappings named by `group` or `name` (control, limits) merges
    entry by entry of the same name, new entries last; anything else is replaced."""
    if isinstance(base, dict) and isinstance(top, dict):
        out = dict(base)
        for key, value in top.items():
            out[key] = overlay(base[key], value) if key in base else value
        return out
    key = _identity(top)
    if key is not None and key == _identity(base):
        assert isinstance(base, list) and isinstance(top, list)
        over = {str(item[key]): item for item in top}
        merged = [
            overlay(item, over.pop(str(item[key]))) if str(item[key]) in over else item
            for item in base
        ]
        return [*merged, *over.values()]
    return top


def _without(data: dict, dotted: object, where: str) -> None:
    """Drop the key `a.b.c` of `data` (what the extended file says there)."""
    if not isinstance(dotted, str) or not dotted:
        raise ConfigError(f"{where}: `{WITHOUT}` lists keys such as registers.kp")
    *parents, last = dotted.split(".")
    at: object = data
    for part in parents:
        at = at.get(part) if isinstance(at, dict) else None
    if not isinstance(at, dict) or last not in at:
        raise ConfigError(f"{where}: `{WITHOUT}` names {dotted!r}, which is not there")
    del at[last]


def read_node(file: Path, _seen: tuple[Path, ...] = ()) -> dict:
    """A node file as a mapping. `extends: <file in the same directory>` reads that
    file first and lays this one over it (`overlay`), after dropping the keys listed in
    `without`. `__extends__` lists the files it was built on, nearest first."""
    file = file.resolve()
    if file in _seen:
        chain = " -> ".join(p.name for p in (*_seen, file))
        raise ConfigError(f"{file}: `{EXTENDS}` goes in a circle ({chain})")
    data = _read(file)
    base_name, dropped = data.pop(EXTENDS, None), data.pop(WITHOUT, None)
    if base_name is None:
        if dropped is not None:
            raise ConfigError(f"{file}: `{WITHOUT}` needs `{EXTENDS}`")
        return data
    if not isinstance(base_name, str) or Path(base_name).name != base_name:
        raise ConfigError(
            f"{file}: `{EXTENDS}` names a node file in the same directory "
            f"(e.g. leader.yaml), not {base_name!r}"
        )
    base_file = file.with_name(base_name)
    if not base_file.is_file():
        raise ConfigError(f"{file}: `{EXTENDS}` names {base_name}, which is not there")
    base = read_node(base_file, (*_seen, file))
    built_on = [str(base_file), *base.pop("__extends__", [])]
    if dropped is not None:
        if not isinstance(dropped, list):
            raise ConfigError(f"{file}: `{WITHOUT}` is a list of keys")
        for dotted in dropped:
            _without(base, dotted, str(file))
    merged = overlay(base, data)
    assert isinstance(merged, dict)
    return {**merged, "__extends__": built_on}


def read_config(
    path: str | Path,
    options: Iterable[str] | None = None,
    mock: bool | None = None,
    sensors: Iterable[str] | None = None,
    observe: Iterable[str] | None = None,
    video_codec: str | None = None,
    experiment: Experiment | Mapping[str, Any] | None = None,
) -> dict:
    """Load the configuration YAML and every referenced node file into one tree.

    `experiment`: an Experiment or its `settings()`: its `nodes` replace node files or
    are laid over the nodes' settings, its `dataset` says where the episodes go.

    `options`: the launch options to enable, with what they require (None: those with
    `default: true`). Their node changes are applied and their `dataset` names appended to `repo_id` and `output`.
    `mock`: override the YAML's `mode` (True: mock devices, False: hardware)."""
    path = Path(path).resolve()
    raw = _read(path)
    available = declared_options(path, raw.pop("options", None))
    enabled = (
        select_options(available)
        if options is None
        else select_options(available, options, base=())
    )
    for key, value in option_changes(available, enabled).items():
        role, _, name = key.partition(".")
        group = dict(raw.get(role) or {})
        if value is None:
            group.pop(name, None)
        else:
            group[name] = value
        raw[role] = group
    chosen_experiment = (
        experiment.settings() if isinstance(experiment, Experiment) else experiment
    )
    laid_over: dict[tuple[str, str], Mapping[str, Any]] = {}
    for key, value in ((chosen_experiment or {}).get("nodes") or {}).items():
        role, _, name = str(key).partition(".")
        group = dict(raw.get(role) or {})
        if role in FIXED_ROLES:
            raise ConfigError(f"experiment: nodes.{key}: a follower is not changed")
        if name not in group:
            there = ", ".join(f"{role}.{n}" for n in group) or "none"
            raise ConfigError(
                f"experiment: nodes.{key} is not a node of this configuration with "
                f"the options {', '.join(enabled) or 'none'} (there: {there})"
            )
        if isinstance(value, str):
            group[name] = value  # another node file of the robot's directory
            raw[role] = group
        else:
            laid_over[(role, name)] = value
    # Options may introduce sensors; explicit selection resolves after them.
    catalog = dict(raw.get("sensors") or {})
    for option in available.values():
        for key, value in option.set.items():
            role, _, name = key.partition(".")
            if role == "sensors" and value is not None and name not in catalog:
                catalog[name] = {"file": value, "default": False}
    chosen = (
        set(sensors)
        if sensors is not None
        else {
            name
            for name, value in catalog.items()
            if not isinstance(value, dict) or value.get("default", True)
        }
    )
    unknown_sensors = chosen - catalog.keys()
    if unknown_sensors:
        raise ConfigError(f"unknown sensors: {sorted(unknown_sensors)}")
    raw["sensors"] = {
        name: value["file"] if isinstance(value, dict) else value
        for name, value in catalog.items()
        if name in chosen
    }
    suffix = dataset_suffix(available, enabled)
    placed = (chosen_experiment or {}).get("dataset") or {}
    for key, given in (("repo_id", "repo_id"), ("output", "root")):
        if given in placed:  # the experiment's own dataset: named as written
            raw[key] = placed[given]
        elif suffix and isinstance(raw.get(key), str) and raw[key]:
            raw[key] += suffix
    if mock is not None:
        raw["mode"] = "mock" if mock else "hardware"
    if isinstance(raw.get("output"), str) and raw["output"]:
        raw["output"] = str((path.parent / raw["output"]).resolve())
    tree: dict = {
        "path": str(path),
        "options": enabled,
        "available": available,
        "experiment": chosen_experiment,
    }

    def node(relative: object, where: str) -> dict:
        if not isinstance(relative, str):
            raise TypeError(f"{where}: expected YAML path")
        file = (path.parent / relative).resolve()
        return {
            **read_node(file),
            "__dir__": str(file.parent),  # resolves files a node names (gravity models)
            "__file__": str(file),  # where setup steps record measured values
            "__robot_dir__": str(path.parent),  # where a node imports local code from
        }

    for role in ROLES:
        group = raw.pop(role, None) or {}
        if not isinstance(group, dict):
            raise TypeError(f"{role}: expected mapping of node name to YAML path")
        tree[role] = {
            name: node(relative, f"{role}.{name}") for name, relative in group.items()
        }
    for (role, name), settings in laid_over.items():
        if role not in tree or name not in tree[role]:
            raise ConfigError(
                f"experiment: nodes.{role}.{name} is not active (a sensor left out?)"
            )
        merged = overlay(tree[role][name], dict(settings))
        assert isinstance(merged, dict)
        tree[role][name] = merged
    for name, controller in tree["controllers"].items():
        # by what the keys hold, so a controller class of your own (`type:
        # module:Class`) built on the policy or parts controller works the same
        builtin = controller.get("type")
        if "teleop" in controller and (
            builtin == "policy" or isinstance(controller["teleop"], list)
        ):
            controller["teleop"] = _nested_nodes(
                controller, "teleop", f"controllers.{name}"
            )
        if builtin == "parts" or isinstance(controller.get("parts"), list):
            controller["parts"] = _nested_nodes(
                controller, "parts", f"controllers.{name}"
            )
    if observe is not None:
        observed = list(observe)
        for controller in tree["controllers"].values():
            if controller.get("type") == "policy" or "observe" in controller:
                controller["observe"] = observed
    for service in SERVICES:
        tree[service] = node(raw.pop(service, None), service)
    if video_codec is not None:
        tree["recorder"]["video_codec"] = video_codec
    unknown = set(raw) - set(SETTINGS)
    if unknown:
        problems = [f"{k}: {RENAMED[k]}" for k in sorted(unknown) if k in RENAMED]
        others = sorted(unknown - set(RENAMED))
        if others:
            allowed = ", ".join((*SETTINGS, *ROLES, *SERVICES, "options"))
            problems.append(f"unknown keys {others} (allowed: {allowed})")
        raise ConfigError(f"{path}: " + "; ".join(problems))
    tree["settings"] = raw
    if raw.get("mode") == "mock":
        table = mock_values(path.parent)
        for part in (*ROLES, *SERVICES):
            tree[part] = _stand_in(tree[part], table)
    return tree


PLACEHOLDER = "SET_"
PROJECT_ROOT = ".roboloom"
MOCK_VALUES = "mock.yaml"  # next to the configuration


def mock_values(directory: Path) -> dict:
    """`mock.yaml`: a stand-in for each SET_ value, used with mock devices only, so a
    project runs in mock before its robot was measured. With the hardware a SET_ value
    is refused as ever."""
    path = directory / MOCK_VALUES
    if not path.exists():
        return {}
    table = _read(path)
    wrong = [str(k) for k in table if not str(k).startswith(PLACEHOLDER)]
    if wrong:
        raise ConfigError(f"{path}: its keys are {PLACEHOLDER} names, not {wrong}")
    return table


def _stand_in(value: object, table: dict) -> object:
    if isinstance(value, str):
        return table.get(value, value)
    if isinstance(value, dict):
        return {
            k: v if str(k).startswith("__") else _stand_in(v, table)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_stand_in(v, table) for v in value]
    return value


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


def env_options(value: str | None) -> list[str] | None:
    """The options a node process was launched with (`ROBOLOOM_OPTIONS`)."""
    if value is None:
        return None
    return [] if value == NO_OPTIONS else [n for n in value.split(",") if n]


def project_robots(root: str | Path = PROJECT_ROOT) -> list[str]:
    """Robot directories under the project root that hold a configuration."""
    root = Path(root)
    if not root.is_dir():
        return []
    return sorted(p.parent.name for p in root.glob(f"*/{CONFIG_FILE}"))


def is_configuration(arg: str, root: str | Path = PROJECT_ROOT) -> bool:
    """Whether a CLI word names a configuration: a robot under the root or a YAML file."""
    path = Path(arg)
    return (Path(root) / path / CONFIG_FILE).is_file() or (
        path.suffix in (".yaml", ".yml") and path.is_file()
    )


def resolve_config(
    arg: str | Path | None = None, root: str | Path = PROJECT_ROOT
) -> Path:
    """A configuration file, or a robot name under the project root: `rakuda2` is
    `.roboloom/rakuda2/config.yaml`. Without a name, the only robot under the root."""
    if arg is None or str(arg) == "":
        robots = project_robots(root)
        if len(robots) == 1:
            return Path(root) / robots[0] / CONFIG_FILE
        if not robots:
            raise ConfigError(
                f"no {Path(root)}/<robot>/{CONFIG_FILE} here "
                "(create one with `roboloom init <robot>`)"
            )
        raise ConfigError(f"several robots under {root}: {', '.join(robots)}; name one")
    path = Path(arg)
    if path.is_file():
        return path
    for candidate in (Path(root) / path / CONFIG_FILE, Path(root) / f"{path}.yaml"):
        if candidate.is_file():
            return candidate
    raise ConfigError(
        f"{arg}: no such configuration file, nor {Path(root) / path}/{CONFIG_FILE} "
        "(create one with `roboloom init <robot>`)"
    )


def _nested_nodes(policy: dict, key: str, where: str) -> dict[str, dict]:
    """`teleop: [controller.yaml, ...]` of a policy (or `parts:` of a parts controller),
    paths next to its file -> the controllers' YAML by name (the file's stem)."""
    paths = policy.get(key)
    if (
        not isinstance(paths, list)
        or not paths
        or not all(isinstance(x, str) for x in paths)
    ):
        raise ConfigError(f"{where}.{key}: a list of controller YAML paths")
    out: dict[str, dict] = {}
    for relative in paths:
        file = (Path(policy["__dir__"]) / relative).resolve()
        if file.stem in out:
            raise ConfigError(f"{where}.{key}: two controllers named {file.stem!r}")
        out[file.stem] = {
            **read_node(file),
            "__dir__": str(file.parent),
            "__file__": str(file),
            "__robot_dir__": policy.get("__robot_dir__"),
        }
    return out


def _bind_teleop(
    name: str, controller: Controller, inputs: dict, followers: dict
) -> None:
    """Build the teleop controllers of a policy (`teleop:`) as controllers of their own
    type, inside the policy (one controller per follower stays the rule)."""
    nodes = controller.cfg.get("teleop") or {}
    built = {}
    for inner, c in nodes.items():
        cls = CONTROLLERS.get(c.get("type"), _search(c))
        targets = c.get("followers")
        source = inputs.get(c.get("input"))
        if not cls.uses_input or source is None:
            raise ConfigError(
                f"controllers.{name}.teleop.{inner} must follow a configured input "
                f"(input: {c.get('input')!r})"
            )
        if not isinstance(targets, list) or not all(t in followers for t in targets):
            raise ConfigError(
                f"controllers.{name}.teleop.{inner}.followers: configured followers"
            )
        built[inner] = cls(
            f"{name}.{inner}", c, source, {x: followers[x] for x in targets}
        )
        _check_keys(built[inner], c, f"controllers.{name}.teleop.{inner}")
    controller.bind_teleop(built)  # type: ignore[attr-defined]  # a PolicyController
    for c in built.values():
        if c.homes and not any(f in controller.homes for f in c.homes):
            controller.homes.update(
                c.homes
            )  # the teleop's home, unless the policy has one


def _bind_parts(name: str, controller: Controller, inputs: dict) -> None:
    """Build the inner controllers of a `type: parts` controller; each drives parts of
    the controller's follower (`<follower>.<part>`) from an input of its own."""
    follower = controller.follower
    built = {}
    for inner, c in (controller.cfg.get("parts") or {}).items():
        where = f"controllers.{name}.parts.{inner}"
        cls = CONTROLLERS.get(c.get("type"), _search(c))
        source = inputs.get(c.get("input"))
        if not cls.uses_input or source is None:
            raise ConfigError(
                f"{where} must follow a configured input (input: {c.get('input')!r})"
            )
        targets = c.get("followers")
        prefix = f"{follower.name}."
        if (
            not isinstance(targets, list)
            or not targets
            or not all(isinstance(t, str) and t.startswith(prefix) for t in targets)
        ):
            raise ConfigError(
                f"{where}.followers: parts of {follower.name}, as "
                f"{', '.join(prefix + p for p in follower.parts()) or prefix + '<part>'}"
            )
        parts = {t: follower.part(t.removeprefix(prefix)) for t in targets}
        built[inner] = cls(f"{name}.{inner}", c, source, parts)
        _check_keys(built[inner], c, where)
    controller.bind_parts(built)  # type: ignore[attr-defined]  # a PartsController


def _search(cfg: dict) -> list[str]:
    """Where a `type: module:Class` of this node file is imported from, after the
    installed packages: the robot's directory (`.roboloom/<robot>/`)."""
    directory = cfg.get("__robot_dir__")
    return [str(directory)] if directory else []


def _check_keys(owner: object, cfg: dict, where: str) -> None:
    """Refuse the keys of a node file its class does not read. A class says what it
    reads in `keys`; one that does not declare `keys` itself (an extension written
    before this check, or one that leaves it out) is not checked."""
    declared = vars(type(owner)).get("keys")
    if declared is not None:
        unknown_keys(cfg, declared, where)


def parse_config(tree: dict) -> RobotConfig:
    missing = placeholders({k: v for k, v in tree.items() if k != "path"})
    if missing:
        raise ConfigError(
            "template values still to fill (see the README next to the configuration):\n  "
            + "\n  ".join(missing)
        )
    e = tree["settings"]
    robot = Path(tree["path"]).parent.name
    repo_id = identity(e.get("repo_id"), "repo_id")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo_id):
        raise ValueError("repo_id must be namespace/name")
    e.setdefault("mode", "hardware")
    if e.get("mode") not in ("mock", "hardware"):
        raise ValueError("mode must be mock or hardware")
    fps = positive(e.get("dataset_fps"), "dataset_fps")

    names = [name for role in ROLES for name in tree.get(role) or {}]
    if len(set(names)) != len(names):
        raise ValueError("node names must be unique across roles")
    for name in names:
        if (
            name in RESERVED
            or name.startswith(RESERVED_PREFIXES)
            or name.endswith(RESERVED_SUFFIXES)
            or not re.fullmatch(r"[A-Za-z0-9_-]+", name)
        ):
            raise ValueError(
                f"invalid node name {name!r} (letters, digits, - and _; not "
                f"{', '.join(sorted(RESERVED))}, not starting with "
                f"{RESERVED_PREFIXES[0]} nor ending with {RESERVED_SUFFIXES[0]})"
            )

    followers = {
        name: FOLLOWERS.get(c.get("type"), _search(c))(name, c)
        for name, c in tree["followers"].items()
    }
    for name, model in followers.items():
        _check_keys(model, tree["followers"][name], f"followers.{name}")
        model.traits()  # a measured `unattended` must fill in an unknown one
    trackers = {
        name: TRACKERS.get(c.get("type"), _search(c))(name, c)
        for name, c in (tree.get("trackers") or {}).items()
    }
    inputs = {
        name: INPUTS.get(c.get("type"), _search(c))(name, c)
        for name, c in tree["inputs"].items()
    }
    for name, held in inputs.items():
        _check_keys(held, tree["inputs"][name], f"inputs.{name}")
        system = getattr(held, "tracker_system", lambda: None)()
        if system is not None and system not in trackers:
            raise ValueError(
                f"inputs.{name}.tracker.system: {system!r} is not a node under trackers: "
                f"({', '.join(trackers) or 'none configured'})"
            )
    sensors = {
        name: SENSORS.get(c.get("type"), _search(c))(name, c)
        for name, c in tree["sensors"].items()
    }
    for name, sensor in sensors.items():
        _check_keys(sensor, tree["sensors"][name], f"sensors.{name}")
    estimators = {}
    for name, c in tree["estimators"].items():
        estimator = ESTIMATORS.get(c.get("type"), _search(c))(name, c)
        _check_keys(estimator, c, f"estimators.{name}")
        follower = followers.get(estimator.follower)
        if follower is None:
            raise ValueError(f"estimators.{name} must reference a configured follower")
        estimator.bind(follower)
        estimators[name] = estimator
    controllers = {}
    for name, c in tree["controllers"].items():
        cls = CONTROLLERS.get(c.get("type"), _search(c))
        if "robot" in c:
            raise ConfigError(
                f"controllers.{name}.robot was renamed: use followers: [<follower>]"
            )
        targets = c.get("followers")
        if (
            not isinstance(targets, list)
            or not targets
            or not all(isinstance(x, str) for x in targets)
            or len(set(targets)) != len(targets)
        ):
            raise ValueError(
                f"controllers.{name}.followers: expected a list of follower names"
            )
        absent = [x for x in targets if x not in followers]
        source = inputs.get(c.get("input"))
        if absent or (cls.uses_input and source is None):
            raise ValueError(
                f"controllers.{name} must reference a configured "
                f"{'input and followers' if cls.uses_input else 'followers'}"
                + (f" (unknown: {', '.join(absent)})" if absent else "")
            )
        if cls.drives_all_followers and targets != list(followers):
            # the recorded action joins every follower in configuration order; a policy
            # trained on it outputs that whole vector
            raise ValueError(
                f"controllers.{name}.followers: a policy drives every follower, in "
                f"configuration order: [{', '.join(followers)}]"
            )
        controller = cls(
            name,
            c,
            source if cls.uses_input else None,
            {x: followers[x] for x in targets},
        )
        _check_keys(controller, c, f"controllers.{name}")
        unknown = set(controller.observes()) - {*inputs, *sensors}
        if unknown:
            raise ValueError(
                f"controllers.{name} observes unknown nodes {sorted(unknown)}"
            )
        bind = getattr(controller, "bind", None)
        if bind is not None:
            bind({**inputs, **sensors}, fps, tree["recorder"].get("max_age_ms", {}))
        if c.get("teleop"):
            _bind_teleop(name, controller, inputs, followers)
        if hasattr(controller, "bind_parts"):
            _bind_parts(name, controller, inputs)
        controller.bind_feedback(estimators)
        controllers[name] = controller
    for follower in followers.values():
        drivers = [n for n, c in controllers.items() if follower.name in c.followers]
        if len(drivers) != 1:
            raise ValueError(
                f"follower {follower.name!r} needs exactly one controller"
                + (f" (has {', '.join(drivers)})" if drivers else "")
            )
        if follower.control_hz < fps:
            raise ValueError("control_hz must be >= dataset_fps")
    for name, controller in controllers.items():
        _check_home(name, controller)
    if not followers:
        _check_without_followers(inputs, sensors, controllers, fps)

    if e["mode"] == "hardware":
        nested = [n for c in controllers.values() for n in c.nested()]
        for owner in [
            *inputs.values(),
            *followers.values(),
            *controllers.values(),
            *nested,
        ]:
            check = getattr(owner, "check_hardware", None)
            if check is not None:
                check()

    owners: list[Source | Follower | Tracker] = [
        *trackers.values(),
        *inputs.values(),
        *followers.values(),
        *sensors.values(),
    ]
    devices = [d for spec in owners for d in spec.device_ids()]
    if len(set(devices)) != len(devices):
        raise ValueError("duplicate port or sensor ID")

    unknown_keys(tree["recorder"], RECORDER_KEYS, "recorder")
    unknown_keys(tree["session"], SESSION_KEYS, "session")
    ages = tree["recorder"].get("max_age_ms", {})
    cfg = RobotConfig(
        robot=robot,
        repo_id=repo_id,
        output=identity(e.get("output"), "output"),
        dataset_fps=fps,
        followers=followers,
        inputs=inputs,
        sensors=sensors,
        controllers=controllers,
        estimators=estimators,
        trackers=trackers,
        max_age_ms={
            name: positive(ages.get(name), f"max_age_ms.{name}")
            for name in (
                *inputs,
                *followers,
                *sensors,
                *(n for n, e in estimators.items() if e.record),
            )
        },
        recorder={
            k: v
            for k, v in tree["recorder"].items()
            if k
            in ("grace_ms", "image_writer_threads", "streaming_encoding", "queue_s")
        }
        | {
            "video_codec": normalize_video_codec(
                tree["recorder"].get("video_codec"), "recorder.video_codec"
            )
        },
        quality=_quality(tree["recorder"].get("quality") or {}),
        mode=e["mode"],
        path=tree["path"],
        options=tuple(tree.get("options", ())),
        available_options=dict(tree.get("available", {})),
        experiment=tree.get("experiment"),
    )
    if tree["session"].get("type") != "terminal":
        raise ValueError("session must be terminal")
    features(cfg)  # rejects colliding LeRobot keys
    return cfg


def _check_without_followers(
    inputs: dict[str, InputDevice],
    sensors: dict[str, Source],
    controllers: dict[str, Controller],
    fps: float,
) -> None:
    """A configuration without followers records its inputs and sensors only (e.g. a
    hand-held device): nothing to drive, and no follower whose rate they could follow."""
    if controllers:
        raise ValueError(
            "followers: none configured, so there is nothing for controllers "
            f"({', '.join(controllers)}) to drive"
        )
    if not inputs and not sensors:
        raise ValueError(
            "followers: configure a follower, or inputs or sensors to record"
        )
    unpaced = [n for n, s in {**inputs, **sensors}.items() if s.rate_hz(fps) is None]
    if unpaced:
        raise ValueError(
            f"{', '.join(unpaced)}: without followers, set the polling rate "
            "(poll_hz for an input, fps for a sensor)"
        )


def _check_home(name: str, controller: Controller) -> None:
    """With `home`, every current-mode group of the leader needs `homing` (the spring that
    pulls it along the move); without it the move would leave those joints behind."""
    source = controller.source
    if not controller.homes or source is None:
        return
    from .control.device import law_class

    missing = [
        g.name
        for g in getattr(source, "control", None) or []
        if law_class(g.law).current_mode and g.cfg.get("homing") is None
    ]
    if missing:
        raise ConfigError(
            f"controllers.{name}.home: leader {source.name} groups {missing} need "
            "homing: {kp_mA_per_count, max_mA}"
        )


def _quality(cfg: dict) -> dict:
    unknown = set(cfg) - set(QUALITY)
    if unknown:
        raise ConfigError(f"recorder.quality: unknown keys {sorted(unknown)}")
    return {k: float(v) for k, v in cfg.items()}


def load_config(
    config: str | Path | None = None,
    root: str | Path = PROJECT_ROOT,
    *,
    options: Iterable[str] | None = None,
    mock: bool | None = None,
    sensors: Iterable[str] | None = None,
    observe: Iterable[str] | None = None,
    video_codec: str | None = None,
    experiment: Experiment | Mapping[str, Any] | None = None,
) -> RobotConfig:
    """Load and validate a configuration file, or one named under the project root.

    `experiment`: an Experiment (`load_experiment`) or its `settings()`; see
    `read_config`. Its options are not applied here: pass them as `options`.

    `sensors`: active recorded sensors (None: defaults, []: none).
    `observe`: policy inputs (None: YAML, []: follower state only).
    `video_codec`: codec of `storage: video` images, "av1" (alias "libsvtav1") or
    "h264" (None: the recorder YAML's `video_codec`, else the saved videos' codec when
    appending, else H.264).
    `options`: the launch options to enable (None: their defaults). `mock`: override the
    YAML's `mode` (True: mock devices, False: hardware)."""
    # Materialize iterable selections once; names remain in YAML declaration order.
    sensors = None if sensors is None else tuple(sensors)
    observe = None if observe is None else tuple(observe)
    video_codec = normalize_video_codec(video_codec)
    path = resolve_config(config, root)
    try:
        cfg = parse_config(
            read_config(path, options, mock, sensors, observe, video_codec, experiment)
        )
        if sensors is None:
            _check_datasets(path, cfg, experiment)
        return cfg
    except ConfigError:
        raise
    except (ValueError, TypeError, KeyError, FileNotFoundError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def _check_datasets(
    path: Path,
    cfg: RobotConfig,
    experiment: Experiment | Mapping[str, Any] | None = None,
) -> None:
    """An enabled option without `dataset` must not change the recorded features, or its
    episodes would share a dataset with differently shaped ones. Compared with the
    configuration loaded without that option and the options requiring it, with the
    same experiment: what the experiment changes is not the option's doing."""
    expected = features(cfg)
    for name in cfg.options:
        if cfg.available_options[name].dataset:
            continue
        rest = [
            n
            for n in cfg.options
            if n != name and name not in requirements(cfg.available_options, n)
        ]
        try:
            other = parse_config(
                read_config(path, rest, mock=True, experiment=experiment)
            )
        except (ConfigError, ValueError, TypeError, KeyError, FileNotFoundError):
            continue  # not loadable without it: nothing to compare with
        if features(other) != expected:
            raise ConfigError(
                f"{path}: options.{name} changes the recorded features; give it "
                "`dataset: <name>` so its episodes go to a dataset of their own"
            )
