"""`meta/roboloom.json`: what a LeRobot dataset does not say about how it was recorded.

    {
      "roboloom": "0.1.0+g1a2b3c4",          the version that created the dataset
      "robot": "rakuda2",
      "units": {"action": ["dynamixel_count", ...], "observation.state": [...]},
      "audio": {...},                          audio processing settings, if any
      "sessions": [                            one entry per run that saved an episode
        {"opened": "2026-11-15T10:00:00+09:00", "roboloom": "0.1.0+g1a2b3c4",
         "options": ["gravity"], "mode": "hardware", "first_episode": 0,
         "config": "3f2a9c0d1e4b5a67"}
      ]
    }

`config` names `meta/roboloom_config/<config>.json`: the configuration as loaded (every
node file's values, the options applied), so the limits, rates and gains an episode was
recorded with can be looked up later. Files a node file points to (gravity models,
tuning, calibration) are not copied.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..version import version
from .schema import joined_parts

if TYPE_CHECKING:
    from ..config import RobotConfig

MANIFEST = "meta/roboloom.json"
CONFIGS = "meta/roboloom_config"


def read(root: Path) -> dict:
    path = root / MANIFEST
    return json.loads(path.read_text()) if path.exists() else {}


def units(cfg: RobotConfig) -> dict[str, list[str]]:
    """The unit of every entry of `action` and of the joined observation vectors."""
    state = [f.unit for f in cfg.followers.values() for _ in f.joint_names]
    out = {"action": state, "observation.state": state} if state else {}
    for key, parts in joined_parts(cfg.sources, cfg.dataset_fps).items():
        named = [part.unit for _, part in parts for _ in part.names]
        if key not in out and all(named):
            out[key] = [str(unit) for unit in named]
    return out


def snapshot(cfg: RobotConfig) -> dict[str, Any] | None:
    """The configuration as its files say it, with the launch choices applied; None
    when `cfg` was not loaded from files. Paths are relative to the configuration, so a
    shared dataset does not carry this machine's directories."""
    from ..config import ROLES, SERVICES, read_config

    path = Path(cfg.path)
    if not cfg.path or not path.is_file():
        return None
    tree = read_config(path, cfg.options, cfg.mock, list(cfg.sensors))
    base = path.parent

    def node(values: dict) -> dict:
        out: dict[str, Any] = {}
        for key, value in values.items():
            if key == "__file__":
                out["file"] = _relative(Path(value), base)
            elif key.startswith("__"):
                continue
            elif isinstance(value, dict) and "__file__" in value:
                out[key] = node(value)  # a nested controller (teleop, parts)
            elif isinstance(value, dict) and all(
                isinstance(v, dict) and "__file__" in v for v in value.values()
            ):
                out[key] = {name: node(v) for name, v in value.items()}
            else:
                out[key] = value
        return out

    settings = {k: v for k, v in tree["settings"].items() if k != "output"}
    return {
        "config": path.name,
        "options": list(cfg.options),
        "settings": settings,
        **{role: {n: node(v) for n, v in tree[role].items()} for role in ROLES},
        **{service: node(tree[service]) for service in SERVICES},
    }


def _relative(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return path.name


def create(root: Path, cfg: RobotConfig, audio: dict, new: bool) -> None:
    """Fill in what is missing. `new`: the dataset was just created (an existing one
    without a manifest came from an older roboloom, whose version is not known)."""
    data = read(root)
    before = json.dumps(data, sort_keys=True)
    if audio:
        data.setdefault("audio", audio)
    if new:
        data.setdefault("roboloom", version())
    data.setdefault("robot", cfg.robot)
    data.setdefault("units", units(cfg))
    if json.dumps(data, sort_keys=True) != before:
        _write(root, data)


def note_session(root: Path, cfg: RobotConfig, first_episode: int) -> None:
    """Record that this run saved its first episode (`first_episode`) with `cfg`."""
    data = read(root)
    entry: dict[str, Any] = {
        "opened": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "roboloom": version(),
        "options": list(cfg.options),
        "mode": cfg.mode,
        "first_episode": first_episode,
    }
    tree = snapshot(cfg)
    if tree is not None:
        text = json.dumps(tree, sort_keys=True, indent=1, default=str)
        name = hashlib.sha256(text.encode()).hexdigest()[:16]
        target = root / CONFIGS / f"{name}.json"
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        entry["config"] = name
    data.setdefault("sessions", []).append(entry)
    _write(root, data)


def _write(root: Path, data: dict) -> None:
    path = root / MANIFEST
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)
