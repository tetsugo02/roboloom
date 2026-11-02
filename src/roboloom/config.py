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
from .robots import FOLLOWERS
from .robots.base import Follower
from .sensors import SENSORS

ROLES = ("inputs", "controllers", "followers", "sensors", "estimators")
SERVICES = ("recorder", "session")
# Service node ids and fixed dora input ids; LeRobot key collisions are checked by `features`.
RESERVED = {*SERVICES, "action", "tick"}
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
    robot_id: str
    repo_id: str
    output: str
    dataset_fps: float
    followers: dict[str, Follower]
    inputs: dict[str, InputDevice] = field(default_factory=dict)
    sensors: dict[str, Source] = field(default_factory=dict)
    controllers: dict[str, Controller] = field(default_factory=dict)
    estimators: dict[str, Estimator] = field(default_factory=dict)
    max_age_ms: dict[str, float] = field(default_factory=dict)
    recorder: dict = field(default_factory=dict)
    quality: dict = field(default_factory=dict)  # see recording.metrics.QUALITY
    mode: str = "hardware"
    robot_type: str = ""
    path: str = ""
    options: tuple[str, ...] = ()  # enabled launch options, in declaration order
    available_options: dict[str, Option] = field(default_factory=dict)

    @property
    def mock(self) -> bool:
        return self.mode == "mock"

    @property
    def follower(self) -> Follower:
        (follower,) = self.followers.values()
        return follower

    @property
    def sources(self) -> dict[str, Recordable]:
        """Recorded streams in dataset order."""
        recorded = {n: e for n, e in self.estimators.items() if e.record}
        return {**self.inputs, **self.followers, **self.sensors, **recorded}

    def controller_for(self, follower: str) -> Controller:
        (controller,) = (
            c for c in self.controllers.values() if c.follower.name == follower
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
    tree["robot"] = raw
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


def parse_config(tree: dict) -> RobotConfig:
    missing = placeholders({k: v for k, v in tree.items() if k != "path"})
    if missing:
        raise ConfigError(
            "template values still to fill (see the README next to the configuration):\n  "
            + "\n  ".join(missing)
        )
    e = tree["robot"]
    robot_id = identity(e.get("robot_id"), "robot_id")
    repo_id = identity(e.get("repo_id"), "repo_id")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo_id):
        raise ValueError("repo_id must be namespace/name")
    e.setdefault("mode", "hardware")
    if e.get("mode") not in ("mock", "hardware"):
        raise ValueError("mode must be mock or hardware")
    fps = positive(e.get("dataset_fps"), "dataset_fps")

    names = [name for role in ROLES for name in tree[role]]
    if len(set(names)) != len(names):
        raise ValueError("node names must be unique across roles")
    for name in names:
        if name in RESERVED or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ValueError(f"invalid node name {name!r}")

    followers = {
        name: FOLLOWERS.get(c.get("type"))(name, c)
        for name, c in tree["followers"].items()
    }
    if len(followers) != 1:
        raise ValueError("exactly one follower per configuration is supported for now")
    inputs = {
        name: INPUTS.get(c.get("type"))(name, c) for name, c in tree["inputs"].items()
    }
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
        if not isinstance(targets, list) or len(targets) != 1:
            raise ValueError(
                f"controllers.{name}.followers: expected a list with one follower name"
            )
        source, follower = inputs.get(c.get("input")), followers.get(targets[0])
        if follower is None or (cls.uses_input and source is None):
            raise ValueError(
                f"controllers.{name} must reference a configured "
                f"{'input and follower' if cls.uses_input else 'follower'}"
            )
        controller = cls(
            name, c, source if cls.uses_input else None, follower, robot_id
        )
        unknown = set(controller.observes()) - {*inputs, *sensors}
        if unknown:
            raise ValueError(
                f"controllers.{name} observes unknown nodes {sorted(unknown)}"
            )
        bind = getattr(controller, "bind", None)
        if bind is not None:
            bind({**inputs, **sensors})
        controller.bind_feedback(estimators)
        controllers[name] = controller
    for follower in followers.values():
        if [c.follower.name for c in controllers.values()].count(follower.name) != 1:
            raise ValueError(f"follower {follower.name!r} needs exactly one controller")
        if follower.control_hz < fps:
            raise ValueError("control_hz must be >= dataset_fps")
    for name, controller in controllers.items():
        _check_home(name, controller)

    if e["mode"] == "hardware":
        for owner in [*inputs.values(), *followers.values()]:
            check = getattr(owner, "check_hardware", None)
            if check is not None:
                check()

    owners: list[Source | Follower] = [
        *inputs.values(),
        *followers.values(),
        *sensors.values(),
    ]
    devices = [d for spec in owners for d in spec.device_ids()]
    if len(set(devices)) != len(devices):
        raise ValueError("duplicate port or sensor ID")

    ages = tree["recorder"].get("max_age_ms", {})
    cfg = RobotConfig(
        robot_id=robot_id,
        repo_id=repo_id,
        output=identity(e.get("output"), "output"),
        dataset_fps=fps,
        followers=followers,
        inputs=inputs,
        sensors=sensors,
        controllers=controllers,
        estimators=estimators,
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
        },
        quality=_quality(tree["recorder"].get("quality") or {}),
        mode=e["mode"],
        robot_type=e.get("robot_type", next(iter(followers.values())).model),
        path=tree["path"],
        options=tuple(tree.get("options", ())),
        available_options=dict(tree.get("available", {})),
    )
    if tree["session"].get("type") != "terminal":
        raise ValueError("session must be terminal")
    features(cfg)  # rejects colliding LeRobot keys
    return cfg


def _check_home(name: str, controller: Controller) -> None:
    """With `home`, every current-mode group of the leader needs `homing` (the spring that
    pulls it along the move); without it the move would leave those joints behind."""
    source = controller.source
    if controller.home is None or source is None:
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
) -> RobotConfig:
    """Load and validate a configuration file, or one named under the project root.

    `options`: the launch options to enable (None: their defaults). `mock`: override the
    YAML's `mode` (True: mock devices, False: hardware)."""
    path = resolve_config(config, root)
    try:
        cfg = parse_config(read_config(path, options, mock))
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
