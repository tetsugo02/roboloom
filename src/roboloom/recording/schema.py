"""LeRobot feature schema assembled from each recorded source's own features.

Features one source owns (`observation.images.camera`) come from its `features()`.
Features several sources share are joined in configuration order from each source's
`joined()` part: `observation.state` and `observation.effort` over the followers,
`observation.effort_ext` and `observation.contact` over the recorded estimators. Their
`names` say which entry belongs to which node (`follower.r_arm_sh_pitch1`).

`action` has the same layout as `observation.state`: one entry per follower joint.
`action.valid` is 1 when every follower sent a command in the row, `action.clamped`
when any of them was limited; `action.meta.<follower>.*` keep each follower's own.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import numpy as np

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


def state_names(followers: Mapping[str, Follower]) -> list[str]:
    """`observation.state` and `action` entries: `<follower>.<joint>`, in order."""
    return [f"{name}.{j}" for name, f in followers.items() for j in f.joint_names]


def features(cfg: RobotConfig) -> Features:
    names = state_names(cfg.followers)
    out: Features = {
        "action": {"dtype": "float32", "shape": (len(names),), "names": names},
        "action.valid": _one("float32"),
        "action.clamped": _one("float32"),
    }
    for follower in cfg.followers:
        for key, dtype in ACTION_META_FIELDS:
            out[f"action.meta.{follower}.{key}"] = _one(dtype)

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


def observation_frame(
    sources: Mapping[str, Recordable],
    msgs: Mapping[str, Envelope | None],
    dataset_fps: float,
) -> dict[str, Any]:
    """The observation values of one row (or one policy step) from each source's latest
    message: each source's own features plus the joined ones. Without `observation.meta`."""
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
