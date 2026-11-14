"""Robot configuration: resolve node files, build validated specs, cross-check the graph.

The configuration YAML (`.roboloom/<robot>/config.yaml`) groups node files by role
(`inputs`, `controllers`, `followers`, `sensors`, `estimators`) plus the `recorder` and
`session` services. Each node's `type` selects its class from that role's registry. Its
`options:` are features chosen at launch (gravity compensation, extra sensors, ...); each
replaces, adds or removes node files. Nothing here opens a device.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .controllers import CONTROLLERS
from .controllers.base import Controller
from .core.checks import identity, positive
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


def read_config(
    path: str | Path,
    options: Iterable[str] | None = None,
    mock: bool | None = None,
    sensors: Iterable[str] | None = None,
    observe: Iterable[str] | None = None,
    video_codec: str | None = None,
) -> dict:
    """Load the configuration YAML and every referenced node file into one tree.

    `options`: the launch options to enable, with what they require (None: those with
    `default: true`). Their node changes are applied and their `dataset` names appended to `repo_id` and `output`.
    `mock`: override the YAML's `mode` (True: mock devices, False: hardware)."""
    path = Path(path).resolve()
    raw = _read(path)
    available = parse_options(raw.pop("options", None))
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
    for key in ("repo_id", "output"):
        if suffix and isinstance(raw.get(key), str) and raw[key]:
            raw[key] += suffix
    if mock is not None:
        raw["mode"] = "mock" if mock else "hardware"
    if isinstance(raw.get("output"), str) and raw["output"]:
        raw["output"] = str((path.parent / raw["output"]).resolve())
    tree: dict = {"path": str(path), "options": enabled, "available": available}

    def node(relative: object, where: str) -> dict:
        if not isinstance(relative, str):
            raise TypeError(f"{where}: expected YAML path")
        file = (path.parent / relative).resolve()
        return {
            **_read(file),
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
    for name, controller in tree["controllers"].items():
        if controller.get("type") == "policy" and "teleop" in controller:
            controller["teleop"] = _nested_nodes(
                controller, "teleop", f"controllers.{name}"
            )
        if controller.get("type") == "parts":
            controller["parts"] = _nested_nodes(
                controller, "parts", f"controllers.{name}"
            )
    if observe is not None:
        observed = list(observe)
        for controller in tree["controllers"].values():
            if controller.get("type") == "policy":
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
            **_read(file),
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
        cls = CONTROLLERS.get(c.get("type"))
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
        cls = CONTROLLERS.get(c.get("type"))
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
    controller.bind_parts(built)  # type: ignore[attr-defined]  # a PartsController


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
        name: FOLLOWERS.get(c.get("type"))(name, c)
        for name, c in tree["followers"].items()
    }
    for model in followers.values():
        model.traits()  # a measured `unattended` must fill in an unknown one
    trackers = {
        name: TRACKERS.get(c.get("type"))(name, c)
        for name, c in (tree.get("trackers") or {}).items()
    }
    inputs = {
        name: INPUTS.get(c.get("type"))(name, c) for name, c in tree["inputs"].items()
    }
    for name, held in inputs.items():
        system = getattr(held, "tracker_system", lambda: None)()
        if system is not None and system not in trackers:
            raise ValueError(
                f"inputs.{name}.tracker.system: {system!r} is not a node under trackers: "
                f"({', '.join(trackers) or 'none configured'})"
            )
    sensors = {
        name: SENSORS.get(c.get("type"))(name, c) for name, c in tree["sensors"].items()
    }
    estimators = {}
    for name, c in tree["estimators"].items():
        estimator = ESTIMATORS.get(c.get("type"))(name, c)
        follower = followers.get(estimator.follower)
        if follower is None:
            raise ValueError(f"estimators.{name} must reference a configured follower")
        estimator.bind(follower)
        estimators[name] = estimator
    controllers = {}
    for name, c in tree["controllers"].items():
        cls = CONTROLLERS.get(c.get("type"))
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
        if c.get("type") == "parts":
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
) -> RobotConfig:
    """Load and validate a configuration file, or one named under the project root.

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
            read_config(path, options, mock, sensors, observe, video_codec)
        )
        if sensors is None:
            _check_datasets(path, cfg)
        return cfg
    except ConfigError:
        raise
    except (ValueError, TypeError, KeyError, FileNotFoundError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def _check_datasets(path: Path, cfg: RobotConfig) -> None:
    """An enabled option without `dataset` must not change the recorded features, or its
    episodes would share a dataset with differently shaped ones. Compared with the
    configuration loaded without that option and the options requiring it."""
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
            other = parse_config(read_config(path, rest, mock=True))
        except (ConfigError, ValueError, TypeError, KeyError, FileNotFoundError):
            continue  # not loadable without it: nothing to compare with
        if features(other) != expected:
            raise ConfigError(
                f"{path}: options.{name} changes the recorded features; give it "
                "`dataset: <name>` so its episodes go to a dataset of their own"
            )
