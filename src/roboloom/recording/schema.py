"""LeRobot feature schema assembled from each recorded source's own features."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.source import Features

if TYPE_CHECKING:
    from ..config import ExperimentConfig

META_FIELDS = (
    ("valid", "float32"), ("capture_age_ms", "float32"), ("ready_age_ms", "float32"),
    ("seq", "int64"), ("capture_ns", "int64"), ("ready_ns", "int64"), ("receive_ns", "int64"),
)


def features(cfg: ExperimentConfig) -> Features:
    dim = len(cfg.robot.joint_names)
    out: Features = {
        "action": {"dtype": "float32", "shape": (dim,), "names": None},
        "action.valid": {"dtype": "float32", "shape": (1,), "names": None},
        "action.seq": {"dtype": "int64", "shape": (1,), "names": None},
        "action.sent_ns": {"dtype": "int64", "shape": (1,), "names": None},
    }
    for name, source in cfg.sources.items():
        own = source.features(cfg.dataset_fps)
        own.update({f"observation.meta.{name}.{key}": {"dtype": dtype, "shape": (1,), "names": None} for key, dtype in META_FIELDS})
        if out.keys() & own.keys():
            raise ValueError(f"source {name!r} repeats dataset features {sorted(out.keys() & own.keys())}")
        out.update(own)
    return out
