"""Causal frame alignment and LeRobotDataset 0.6.1 writing."""

from __future__ import annotations

import math
import time
from importlib import import_module
from pathlib import Path
from typing import Any

import numpy as np

from .protocol import Envelope, unpack_array

SOURCES = ("leader", "robot", "camera", "digit_left", "digit_right", "audio")


def source_names(cfg: dict) -> tuple[str, ...]:
    nodes = cfg["nodes"]
    return tuple(k for k in nodes if k == "leader" or k == "robot" or nodes[k].get("type") in ("realsense_rgb", "digit", "image", "pcm_mono"))


def features(cfg: dict) -> dict:
    n = cfg["nodes"]
    dim = len(n["robot"]["limits"])
    out: dict[str, dict[str, Any]] = {
        "observation.state": {"dtype": "float32", "shape": (dim,), "names": None},
        "action": {"dtype": "float32", "shape": (dim,), "names": None},
        "action.valid": {"dtype": "float32", "shape": (1,), "names": None},
        "action.seq": {"dtype": "int64", "shape": (1,), "names": None},
        "action.sent_ns": {"dtype": "int64", "shape": (1,), "names": None},
    }
    if "leader" in n:
        out["observation.leader"] = {"dtype": "float32", "shape": (dim,), "names": None}
    if "audio" in n:
        out["observation.audio.pcm"] = {"dtype": "int16", "shape": (int(n["audio"]["sample_rate"] / cfg["experiment"]["dataset_fps"]),), "names": None}
    for key in (s for s in source_names(cfg) if s not in ("leader", "robot", "audio")):
        c = n[key]
        out[f"observation.images.{key}"] = {"dtype": "video", "shape": (c["height"], c["width"], 3), "names": ["height", "width", "channels"]}
    for key in source_names(cfg):
        for field, dtype in (("valid", "float32"), ("capture_age_ms", "float32"), ("ready_age_ms", "float32"), ("seq", "int64"), ("capture_ns", "int64"), ("ready_ns", "int64"), ("receive_ns", "int64")):
            out[f"observation.meta.{key}.{field}"] = {"dtype": dtype, "shape": (1,), "names": None}
    return out


class EpisodeRecorder:
    def __init__(self, cfg: dict, dataset=None):
        self.cfg = cfg
        self.sources = source_names(cfg)
        self.dataset: Any = dataset  # LeRobotDataset 0.6.1 has no py.typed marker.
        self.active = False
        self.stopped = False
        self.samples: dict[str, list[Envelope]] = {s: [] for s in (*self.sources, "action")}
        self.t0_ns = 0
        self.end_ns = 0
        self.task = ""

    def start(self, task: str, now_ns: int | None = None) -> None:
        if self.active or self.stopped:
            raise RuntimeError("finish or discard the previous episode first")
        if not task.strip():
            raise ValueError("task is required")
        self.samples = {s: [] for s in (*self.sources, "action")}
        self.task = task
        self.t0_ns = time.monotonic_ns() if now_ns is None else now_ns
        self.active = True

    def ingest(self, msg: Envelope) -> None:
        if self.active and msg.kind in self.samples:
            if not msg.t_receive_ns:
                msg.t_receive_ns = time.monotonic_ns()
            self.samples[msg.kind].append(msg)

    def stop(self, now_ns: int | None = None) -> None:
        if not self.active:
            raise RuntimeError("no active episode")
        self.end_ns = time.monotonic_ns() if now_ns is None else now_ns
        self.active, self.stopped = False, True

    def discard(self) -> None:
        if self.dataset is not None and self.dataset.has_pending_frames():
            self.dataset.clear_episode_buffer()
        self.active = self.stopped = False
        self.samples = {s: [] for s in (*self.sources, "action")}

    def _selected(self, source: str, t_ns: int) -> Envelope | None:
        age_limit = self.cfg["nodes"]["recorder"]["max_age_ms"][source] * 1e6
        eligible = [s for s in self.samples[source] if s.t_ready_ns <= t_ns and s.t_receive_ns <= t_ns and 0 <= t_ns - s.t_capture_ns <= age_limit]
        return max(eligible, key=lambda s: (s.t_ready_ns, s.seq)) if eligible else None

    def _frame(self, t_ns: int, next_ns: int) -> dict:
        frame: dict[str, Any] = {"task": self.task}
        dim = len(self.cfg["nodes"]["robot"]["limits"])
        for source in self.sources:
            msg = self._selected(source, t_ns)
            prefix = f"observation.meta.{source}."
            values = {
                "valid": float(msg is not None),
                "capture_age_ms": (t_ns - msg.t_capture_ns) / 1e6 if msg else 0.0,
                "ready_age_ms": (t_ns - msg.t_ready_ns) / 1e6 if msg else 0.0,
                "seq": msg.seq if msg else -1,
                "capture_ns": msg.t_capture_ns if msg else 0,
                "ready_ns": msg.t_ready_ns if msg else 0,
                "receive_ns": msg.t_receive_ns if msg else 0,
            }
            for key, value in values.items():
                dtype = np.int64 if key in ("seq", "capture_ns", "ready_ns", "receive_ns") else np.float32
                frame[prefix + key] = np.asarray([value], dtype=dtype)
            if source in ("leader", "robot"):
                frame["observation.leader" if source == "leader" else "observation.state"] = np.asarray(msg.payload["positions"] if msg else [0] * dim, dtype=np.float32)
            elif source != "audio":
                c = self.cfg["nodes"][source]
                image = unpack_array(msg.payload["image"]) if msg else np.zeros((c["height"], c["width"], 3), np.uint8)
                frame[f"observation.images.{source}"] = image.astype(np.uint8)
            elif source == "audio":
                size = features(self.cfg)["observation.audio.pcm"]["shape"][0]
                data = unpack_array(msg.payload["pcm"]).reshape(-1) if msg else np.zeros(size, np.int16)
                frame["observation.audio.pcm"] = np.pad(data[:size], (0, max(0, size - len(data))), constant_values=0).astype(np.int16)
        actions = [x for x in self.samples["action"] if x.payload.get("valid") and t_ns <= x.payload.get("t_sent_ns", 0) < next_ns]
        action = min(actions, key=lambda x: x.payload["t_sent_ns"]) if actions else None
        frame["action"] = np.asarray(action.payload["positions"] if action else [0] * dim, dtype=np.float32)
        frame["action.valid"] = np.asarray([float(action is not None)], dtype=np.float32)
        frame["action.seq"] = np.asarray([action.payload["command_seq"] if action else -1], dtype=np.int64)
        frame["action.sent_ns"] = np.asarray([action.payload["t_sent_ns"] if action else 0], dtype=np.int64)
        return frame

    def frames(self) -> list[dict]:
        if not self.stopped:
            raise RuntimeError("stop the episode first")
        period = int(1e9 / self.cfg["experiment"]["dataset_fps"])
        count = max(0, math.ceil((self.end_ns - self.t0_ns) / period))
        return [self._frame(self.t0_ns + i * period, self.t0_ns + (i + 1) * period) for i in range(count)]

    def metrics(self) -> dict:
        if not self.stopped:
            raise RuntimeError("stop the episode first")
        periods = [x.payload.get("tick_interval_ms", 0) for x in self.samples["robot"] if x.payload.get("tick_interval_ms", 0) > 0]
        latency = [(x.t_receive_ns - x.t_capture_ns) / 1e6 for key in self.sources for x in self.samples[key]]
        frames = self.frames()
        return {
            "control_interval_ms": summarize(periods),
            "latency_ms": summarize(latency),
            "missing_rate": {key: summarize([1 - float(frame[f"observation.meta.{key}.valid"][0]) for frame in frames]) for key in self.sources},
        }

    def save(self) -> int:
        rows = self.frames()
        if not rows:
            raise ValueError("empty episode")
        if self.dataset is None:
            LeRobotDataset = import_module("lerobot.datasets.lerobot_dataset").LeRobotDataset

            e = self.cfg["experiment"]
            root = Path(e["output"]).resolve()
            if (root / "meta" / "info.json").exists():
                self.dataset = LeRobotDataset.resume(repo_id=e["repo_id"], root=root)
                expected = features(self.cfg)
                if self.dataset.fps != e["dataset_fps"] or any(
                    name not in self.dataset.features or any(self.dataset.features[name].get(key) != value for key, value in spec.items())
                    for name, spec in expected.items()
                ):
                    raise ValueError("existing dataset schema or FPS differs from experiment")
            else:
                self.dataset = LeRobotDataset.create(repo_id=e["repo_id"], fps=e["dataset_fps"], features=features(self.cfg), root=root, robot_type=e.get("robot_type", e["robot_id"]), use_videos=True)
        for row in rows:
            self.dataset.add_frame(row)
        self.dataset.save_episode()
        self.discard()
        return len(rows)

    def close(self) -> None:
        if self.dataset is not None:
            if self.dataset.has_pending_frames():
                self.dataset.clear_episode_buffer()
            self.dataset.finalize()


def summarize(values: list[float]) -> dict:
    if not values:
        return {key: 0.0 for key in ("mean", "p95", "p99", "max")}
    a = np.asarray(values, dtype=float)
    return {"mean": float(a.mean()), "p95": float(np.percentile(a, 95)), "p99": float(np.percentile(a, 99)), "max": float(a.max())}
