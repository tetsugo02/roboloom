"""Causal frame alignment and LeRobotDataset 0.6.1 writing."""

from __future__ import annotations

import math
import time
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from ..core.protocol import Envelope
from .metrics import summarize
from .schema import META_FIELDS, features

if TYPE_CHECKING:
    from ..config import ExperimentConfig

ACTION = "action"  # stream of commands the robot actually sent


class EpisodeRecorder:
    def __init__(self, cfg: ExperimentConfig, dataset=None):
        self.cfg = cfg
        self.sources = cfg.sources
        self.dataset: Any = dataset  # LeRobotDataset 0.6.1 has no py.typed marker.
        self.active = False
        self.stopped = False
        self.samples: dict[str, list[Envelope]] = self._empty()
        self.t0_ns = 0
        self.end_ns = 0
        self.task = ""

    def _empty(self) -> dict[str, list[Envelope]]:
        return {s: [] for s in (*self.sources, ACTION)}

    def start(self, task: str, now_ns: int | None = None) -> None:
        if self.active or self.stopped:
            raise RuntimeError("finish or discard the previous episode first")
        if not task.strip():
            raise ValueError("task is required")
        self.samples = self._empty()
        self.task = task
        self.t0_ns = time.monotonic_ns() if now_ns is None else now_ns
        self.active = True

    def ingest(self, source: str, msg: Envelope) -> None:
        if self.active and source in self.samples:
            if not msg.t_receive_ns:
                msg.t_receive_ns = time.monotonic_ns()
            self.samples[source].append(msg)

    def stop(self, now_ns: int | None = None) -> None:
        if not self.active:
            raise RuntimeError("no active episode")
        self.end_ns = time.monotonic_ns() if now_ns is None else now_ns
        self.active, self.stopped = False, True

    def discard(self) -> None:
        if self.dataset is not None and self.dataset.has_pending_frames():
            self.dataset.clear_episode_buffer()
        self.active = self.stopped = False
        self.samples = self._empty()

    def _selected(self, source: str, t_ns: int) -> Envelope | None:
        age_limit = self.cfg.max_age_ms[source] * 1e6
        eligible = [s for s in self.samples[source] if s.t_ready_ns <= t_ns and s.t_receive_ns <= t_ns and 0 <= t_ns - s.t_capture_ns <= age_limit]
        return max(eligible, key=lambda s: (s.t_ready_ns, s.seq)) if eligible else None

    def _frame(self, t_ns: int, next_ns: int) -> dict:
        frame: dict[str, Any] = {"task": self.task}
        fps = self.cfg.dataset_fps
        for name, source in self.sources.items():
            msg = self._selected(name, t_ns)
            values = {
                "valid": float(msg is not None),
                "capture_age_ms": (t_ns - msg.t_capture_ns) / 1e6 if msg else 0.0,
                "ready_age_ms": (t_ns - msg.t_ready_ns) / 1e6 if msg else 0.0,
                "seq": msg.seq if msg else -1,
                "capture_ns": msg.t_capture_ns if msg else 0,
                "ready_ns": msg.t_ready_ns if msg else 0,
                "receive_ns": msg.t_receive_ns if msg else 0,
            }
            for key, dtype in META_FIELDS:
                frame[f"observation.meta.{name}.{key}"] = np.asarray([values[key]], dtype=dtype)
            frame.update(source.frame(msg, fps))
        dim = len(self.cfg.robot.joint_names)
        actions = [x for x in self.samples[ACTION] if x.payload.get("valid") and t_ns <= x.payload.get("t_sent_ns", 0) < next_ns]
        action = min(actions, key=lambda x: x.payload["t_sent_ns"]) if actions else None
        frame["action"] = np.asarray(action.payload["positions"] if action else [0] * dim, dtype=np.float32)
        frame["action.valid"] = np.asarray([float(action is not None)], dtype=np.float32)
        frame["action.seq"] = np.asarray([action.payload["command_seq"] if action else -1], dtype=np.int64)
        frame["action.sent_ns"] = np.asarray([action.payload["t_sent_ns"] if action else 0], dtype=np.int64)
        return frame

    def frames(self) -> list[dict]:
        if not self.stopped:
            raise RuntimeError("stop the episode first")
        period = int(1e9 / self.cfg.dataset_fps)
        count = max(0, math.ceil((self.end_ns - self.t0_ns) / period))
        return [self._frame(self.t0_ns + i * period, self.t0_ns + (i + 1) * period) for i in range(count)]

    def metrics(self) -> dict:
        if not self.stopped:
            raise RuntimeError("stop the episode first")
        robot = self.cfg.robot.name
        periods = [x.payload.get("tick_interval_ms", 0) for x in self.samples[robot] if x.payload.get("tick_interval_ms", 0) > 0]
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

            cfg = self.cfg
            root = Path(cfg.output).resolve()
            expected = features(cfg)
            if (root / "meta" / "info.json").exists():
                self.dataset = LeRobotDataset.resume(repo_id=cfg.repo_id, root=root)
                if self.dataset.fps != cfg.dataset_fps or any(
                    name not in self.dataset.features or any(self.dataset.features[name].get(key) != value for key, value in spec.items())
                    for name, spec in expected.items()
                ):
                    raise ValueError("existing dataset schema or FPS differs from experiment")
            else:
                self.dataset = LeRobotDataset.create(repo_id=cfg.repo_id, fps=cfg.dataset_fps, features=expected, root=root, robot_type=cfg.robot_type or cfg.robot_id, use_videos=True)
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
