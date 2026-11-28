"""LeRobot feature schema assembled from each recorded source's own features.

Features one source owns (`observation.images.camera`) come from its `features()`.
Features several sources share are joined in configuration order from each source's
`joined()` part: `observation.state` and `observation.effort` over the followers,
`observation.effort_ext` and `observation.contact` over the recorded estimators. Their
`names` say which entry belongs to which node (`follower.r_arm_sh_pitch1`).

`action` has the same layout as `observation.state`: one entry per follower joint. A
configuration without followers (a hand-held device) records no `action*` features.
`action.valid` is 1 when every follower sent a command in the row, `action.clamped`
when any of them was limited; `action.meta.<follower>.*` keep each follower's own.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator, Mapping
from typing import TYPE_CHECKING, Any, Literal, overload

import numpy as np

from ..controllers.teleop import teleop_mode
from ..core.protocol import Envelope
from ..core.source import Features, Joined, Recordable

if TYPE_CHECKING:
    from ..config import RobotConfig
    from ..robots.base import Follower

META_FIELDS = (
    ("valid", "float32"),
    ("capture_age_ms", "float32"),
    ("ready_age_ms", "float32"),
    ("seq", "int64"),
    ("capture_ns", "int64"),
    ("ready_ns", "int64"),
    ("receive_ns", "int64"),
)
ACTION_META_FIELDS = (
    ("valid", "float32"),
    ("clamped", "float32"),
    ("seq", "int64"),
    ("sent_ns", "int64"),
)


def _one(dtype: str) -> dict[str, Any]:
    return {"dtype": dtype, "shape": (1,), "names": None}


def joined_parts(
    sources: Mapping[str, Recordable], dataset_fps: float
) -> dict[str, list[tuple[str, Joined]]]:
    """Shared feature -> (source name, its part), in source order. Raises ValueError
    when the parts of one feature disagree on dtype or unit."""
    out: dict[str, list[tuple[str, Joined]]] = {}
    for name, source in sources.items():
        parts = getattr(source, "joined", None)
        for key, part in (parts(dataset_fps) if parts is not None else {}).items():
            out.setdefault(key, []).append((name, part))
    for key, parts in out.items():
        first = parts[0][1]
        for name, part in parts[1:]:
            if part.dtype != first.dtype:
                raise ValueError(
                    f"{key}: {name} records {part.dtype}, {parts[0][0]} {first.dtype}"
                )
            if part.unit != first.unit:
                raise ValueError(
                    f"{key}: {name} records {part.unit}, {parts[0][0]} {first.unit}; "
                    "one vector cannot mix units (record it for one of them only)"
                )
    return out


def _joined_features(sources: Mapping[str, Recordable], fps: float) -> Features:
    return {
        key: {
            "dtype": parts[0][1].dtype,
            "shape": (sum(len(p.names) for _, p in parts),),
            "names": [n for _, p in parts for n in p.names],
        }
        for key, parts in joined_parts(sources, fps).items()
    }


FILTERED = "action.filtered"  # 1 when a hook changed any command in the row


def records_filtered(cfg: RobotConfig) -> bool:
    """Decide from YAML alone, without importing a hook or policy factory."""
    return any(
        c.cfg.get("type") == "policy"
        and any(entry.get("writes") for entry in c.cfg.get("hooks", []))
        for c in cfg.controllers.values()
    )


INTERVENTION = "action.intervention"  # 1 where a person drove the row (policy teleop)


def records_intervention(cfg: RobotConfig) -> bool:
    """A policy that can hand the followers to teleoperation (`teleop:`) records which
    rows a person drove."""
    mode = teleop_mode(cfg.controllers)
    return mode is not None and mode.handback


def state_names(followers: Mapping[str, Follower]) -> list[str]:
    """`observation.state` and `action` entries: `<follower>.<joint>`, in order."""
    return [f"{name}.{j}" for name, f in followers.items() for j in f.joint_names]


def features(cfg: RobotConfig) -> Features:
    """The LeRobot features a configuration records: name -> {"dtype", "shape",
    "names"}. `action*` only with followers, `action.intervention` only with a policy
    that has `teleop:`, `action.filtered` only for YAML hook write claims,
    then each recorded source's own features and
    `observation.meta.<source>.*`, then the joined ones (`observation.state`, ...)."""
    names = state_names(cfg.followers)
    out: Features = (
        {
            "action": {"dtype": "float32", "shape": (len(names),), "names": names},
            "action.valid": _one("float32"),
            "action.clamped": _one("float32"),
        }
        if cfg.followers  # without followers nothing is commanded: no action
        else {}
    )
    for follower in cfg.followers:
        for key, dtype in ACTION_META_FIELDS:
            out[f"action.meta.{follower}.{key}"] = _one(dtype)
    if records_intervention(cfg):
        out[INTERVENTION] = _one("float32")
    if records_filtered(cfg):
        out[FILTERED] = _one("float32")

    def add(own: Features, owner: str) -> None:
        clash = out.keys() & own.keys()
        if clash:
            raise ValueError(f"{owner} repeats dataset features {sorted(clash)}")
        out.update(own)

    for name, source in cfg.sources.items():
        own = source.features(cfg.dataset_fps)
        own.update(
            {
                f"observation.meta.{name}.{key}": _one(dtype)
                for key, dtype in META_FIELDS
            }
        )
        add(own, f"source {name!r}")
    add(_joined_features(cfg.sources, cfg.dataset_fps), "a joined feature")
    return out


def observation_features(
    sources: Mapping[str, Recordable], dataset_fps: float
) -> Features:
    """The names, dtypes and shapes of what `observation_frame` returns for `sources`:
    each source's own features plus the joined ones, without `observation.meta`."""
    out: Features = {}
    for source in sources.values():
        out.update(source.features(dataset_fps))
    out.update(_joined_features(sources, dataset_fps))
    return out


class _ObservationFrame(Mapping[str, Any]):
    """A period's values, decoded by source only when a declared key is read."""

    def __init__(
        self,
        sources: Mapping[str, Recordable],
        msgs: Mapping[str, Envelope | None],
        fps: float,
        keys: Collection[str],
    ):
        self.sources, self.msgs, self.fps = sources, msgs, fps
        self.keys_requested = tuple(keys)
        self.owners = {
            key: name
            for name, source in sources.items()
            for key in source.features(fps)
        }
        self.parts = joined_parts(sources, fps)
        self.own: dict[str, dict[str, Any]] = {}
        self.joined: dict[str, dict[str, Any]] = {}
        self.cache: dict[str, Any] = {}

    def __getitem__(self, key: str) -> Any:
        if key not in self.keys_requested:
            raise KeyError(key)
        if key not in self.cache:
            if key in self.parts:
                parts = self.parts[key]
                values = []
                for name, part in parts:
                    if name not in self.joined:
                        self.joined[name] = self.sources[name].joined_frame(  # type: ignore[attr-defined]
                            self.msgs.get(name), self.fps
                        )
                    value = self.joined[name][key]
                    if len(value) != len(part.names):
                        raise ValueError(
                            f"{name}: {key} has {len(value)} values, not {len(part.names)}"
                        )
                    values.append(np.asarray(value, dtype=part.dtype))
                self.cache[key] = np.concatenate(values).astype(parts[0][1].dtype)
            else:
                name = self.owners[key]
                if name not in self.own:
                    self.own[name] = self.sources[name].frame(
                        self.msgs.get(name), self.fps
                    )
                self.cache[key] = self.own[name][key]
        return self.cache[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys_requested)

    def __len__(self) -> int:
        return len(self.keys_requested)


@overload
def observation_frame(
    sources: Mapping[str, Recordable],
    msgs: Mapping[str, Envelope | None],
    dataset_fps: float,
    *,
    keys: Collection[str] | None = None,
    lazy: Literal[False] = False,
) -> dict[str, Any]: ...


@overload
def observation_frame(
    sources: Mapping[str, Recordable],
    msgs: Mapping[str, Envelope | None],
    dataset_fps: float,
    *,
    keys: Collection[str],
    lazy: Literal[True],
) -> Mapping[str, Any]: ...


def observation_frame(
    sources: Mapping[str, Recordable],
    msgs: Mapping[str, Envelope | None],
    dataset_fps: float,
    *,
    keys: Collection[str] | None = None,
    lazy: bool = False,
) -> Mapping[str, Any]:
    """The observation values of one row (or one policy step) from each source's latest
    message: each source's own features plus the joined ones. Without `observation.meta`.

    ``keys`` restricts the features to materialize. With ``lazy=True`` it returns a
    read-only mapping whose values are decoded and cached on first access, so a hook
    reading state does not decode an unread image. The default returns the full dict.
    """
    if keys is not None:
        frame = _ObservationFrame(sources, msgs, dataset_fps, keys)
        return frame if lazy else dict(frame)
    out: dict[str, Any] = {}
    for name, source in sources.items():
        out.update(source.frame(msgs.get(name), dataset_fps))
    for key, parts in joined_parts(sources, dataset_fps).items():
        values = []
        for name, part in parts:
            value = sources[name].joined_frame(msgs.get(name), dataset_fps)[key]  # type: ignore[attr-defined]
            if len(value) != len(part.names):
                raise ValueError(
                    f"{name}: {key} has {len(value)} values, not {len(part.names)}"
                )
            values.append(np.asarray(value, dtype=part.dtype))
        out[key] = np.concatenate(values).astype(parts[0][1].dtype)
    return out
