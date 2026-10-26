"""Causal frame alignment and LeRobotDataset 0.6.1 writing.

Rows are finalized while the episode runs, so memory stays bounded:

- Row k covers [t_k, t_{k+1}) with t_k = t0 + k / dataset_fps.
- Observations for row k are those the recorder had received by t_k.
- `action[k]` is the first command the robot sent in [t_k, t_{k+1}).
- A row is final once the robot's action stream has passed t_{k+1} (watermark),
  or `grace_ms` after t_{k+1} if the robot is silent.

Samples no later row can select are dropped. The newest sample received before
`start` is kept as pre-roll so row 0 is not empty.
"""

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
    def __init__(
        self,
        cfg: ExperimentConfig,
        dataset=None,
        grace_ms: float = 500,
        image_writer_threads: int = 4,
        streaming_encoding: bool = False,
        queue_s: float = 0.5,
    ):  # queue_s: dora input queues, see runtime.flow
        self.cfg = cfg
        self.sources = cfg.sources
        self.dataset: Any = dataset  # LeRobotDataset 0.6.1 has no py.typed marker.
        self.grace_ns = int(grace_ms * 1e6)
        self.writer_options = {
            "image_writer_threads": image_writer_threads,
            "streaming_encoding": streaming_encoding,
        }
        self.period_ns = int(1e9 / cfg.dataset_fps)
        self.active = False
        self.stopped = False
        self.samples: dict[str, list[Envelope]] = self._empty()
        self.preroll: dict[str, Envelope] = {}
        self.t0_ns = 0
        self.end_ns = 0
        self.task = ""
        self.next_row = 0
        self.watermark_ns = 0
        self.write = True
        self._reset_stats()

    def _empty(self) -> dict[str, list[Envelope]]:
        return {s: [] for s in (*self.sources, ACTION)}

    def _reset_stats(self) -> None:
        self.written = 0
        self.stats: dict[str, list[float]] = {
            "control_interval_ms": [],
            "latency_ms": [],
            "queue_ms": [],
        }
        self.missing = {key: 0 for key in self.sources}
        self.action_rows = self.clamped = 0

    # -- episode lifecycle -------------------------------------------------

    def open_dataset(self) -> None:
        if self.dataset is not None:
            return
        LeRobotDataset = import_module(
            "lerobot.datasets.lerobot_dataset"
        ).LeRobotDataset

        cfg = self.cfg
        root = Path(cfg.output).resolve()
        expected = features(cfg)
        if (root / "meta" / "info.json").exists():
            self.dataset = LeRobotDataset.resume(
                repo_id=cfg.repo_id, root=root, **self.writer_options
            )
            if self.dataset.fps != cfg.dataset_fps or any(
                name not in self.dataset.features
                or any(
                    self.dataset.features[name].get(key) != value
                    for key, value in spec.items()
                )
                for name, spec in expected.items()
            ):
                raise ValueError(
                    "existing dataset schema or FPS differs from experiment"
                )
        else:
            self.dataset = LeRobotDataset.create(
                repo_id=cfg.repo_id,
                fps=cfg.dataset_fps,
                features=expected,
                root=root,
                robot_type=cfg.robot_type or cfg.robot_id,
                use_videos=True,
                **self.writer_options,
            )

    def start(self, task: str, now_ns: int | None = None, write: bool = True) -> None:
        """Begin an episode. `write=False` keeps rows for `frames()` without a dataset (tests)."""
        if self.active or self.stopped:
            raise RuntimeError("finish or discard the previous episode first")
        if not task.strip():
            raise ValueError("task is required")
        if write:
            self.open_dataset()
        self.write = write
        self.samples = self._empty()
        for source, msg in self.preroll.items():
            self.samples[source].append(msg)
        self.task = task
        self.t0_ns = time.monotonic_ns() if now_ns is None else now_ns
        self.next_row = 0
        self._reset_stats()
        self.active = True

    def ingest(self, source: str, msg: Envelope) -> None:
        if source not in self.samples:
            return
        if not msg.t_receive_ns:
            msg.t_receive_ns = time.monotonic_ns()
        if source == ACTION:
            self.watermark_ns = max(self.watermark_ns, msg.t_ready_ns)
        if not self.active:
            if source != ACTION:
                self.preroll[source] = msg
            return
        self.samples[source].append(msg)
        self.stats["latency_ms"].append((msg.t_receive_ns - msg.t_capture_ns) / 1e6)
        self.stats["queue_ms"].append((msg.t_receive_ns - msg.t_ready_ns) / 1e6)
        if source == self.cfg.robot.name and msg.payload.get("tick_interval_ms", 0) > 0:
            self.stats["control_interval_ms"].append(msg.payload["tick_interval_ms"])

    def poll(self, now_ns: int | None = None) -> int:
        """Finalize every row whose interval has closed; return how many were written."""
        if not (self.active and self.write):
            return 0
        now = time.monotonic_ns() if now_ns is None else now_ns
        count = 0
        while True:
            end = self.t0_ns + (self.next_row + 1) * self.period_ns
            if self.watermark_ns < end and now < end + self.grace_ns:
                return count
            self._emit(self.next_row)
            count += 1

    def stop(self, now_ns: int | None = None) -> None:
        if not self.active:
            raise RuntimeError("no active episode")
        self.end_ns = time.monotonic_ns() if now_ns is None else now_ns
        if self.write:
            for k in range(self.next_row, self._row_count()):
                self._emit(k)
        self.active, self.stopped = False, True

    def discard(self) -> None:
        if self.dataset is not None and self.dataset.has_pending_frames():
            self.dataset.clear_episode_buffer()
        self.active = self.stopped = False
        self.samples = self._empty()

    def save(self) -> int:
        if not self.stopped:
            raise RuntimeError("stop the episode first")
        if not self.written:
            raise ValueError("empty episode")
        self.dataset.save_episode()
        count = self.written
        self.discard()
        return count

    def close(self) -> None:
        if self.dataset is not None:
            if self.dataset.has_pending_frames():
                self.dataset.clear_episode_buffer()
            self.dataset.finalize()

    # -- rows ---------------------------------------------------------------

    def _row_count(self) -> int:
        return max(0, math.ceil((self.end_ns - self.t0_ns) / self.period_ns))

    def _emit(self, k: int) -> None:
        t_ns = self.t0_ns + k * self.period_ns
        row = self._frame(t_ns, t_ns + self.period_ns)
        for key in self.sources:
            # int(): numpy bools would make the counters numpy ints, which JSON rejects
            self.missing[key] += int(row[f"observation.meta.{key}.valid"][0] == 0)
        self.action_rows += int(row["action.valid"][0] == 1)
        self.clamped += int(row["action.clamped"][0] == 1)
        if self.write:
            self.dataset.add_frame(row)
        self.written += 1
        self.next_row = k + 1
        self._prune(t_ns + self.period_ns)

    def _prune(self, next_ns: int) -> None:
        """Drop samples no row at or after `next_ns` can select."""
        for source, items in self.samples.items():
            if source == ACTION:
                self.samples[source] = [
                    x
                    for x in items
                    if x.payload.get("valid")
                    and x.payload.get("t_sent_ns", 0) >= next_ns
                ]
                continue
            keep = 0
            for i, s in enumerate(items):
                if s.t_ready_ns <= next_ns and s.t_receive_ns <= next_ns:
                    keep = i
            del items[:keep]

    def _selected(self, source: str, t_ns: int) -> Envelope | None:
        age_limit = self.cfg.max_age_ms[source] * 1e6
        eligible = [
            s
            for s in self.samples[source]
            if s.t_ready_ns <= t_ns
            and s.t_receive_ns <= t_ns
            and 0 <= t_ns - s.t_capture_ns <= age_limit
        ]
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
                frame[f"observation.meta.{name}.{key}"] = np.asarray(
                    [values[key]], dtype=dtype
                )
            frame.update(source.frame(msg, fps))
        dim = len(self.cfg.robot.joint_names)
        actions = [
            x
            for x in self.samples[ACTION]
            if x.payload.get("valid")
            and t_ns <= x.payload.get("t_sent_ns", 0) < next_ns
        ]
        action = min(actions, key=lambda x: x.payload["t_sent_ns"]) if actions else None
        frame["action"] = np.asarray(
            action.payload["positions"] if action else [0] * dim, dtype=np.float32
        )
        frame["action.valid"] = np.asarray(
            [float(action is not None)], dtype=np.float32
        )
        frame["action.clamped"] = np.asarray(
            [float(bool(action and action.payload.get("clamped")))], dtype=np.float32
        )
        frame["action.seq"] = np.asarray(
            [action.payload["command_seq"] if action else -1], dtype=np.int64
        )
        frame["action.sent_ns"] = np.asarray(
            [action.payload["t_sent_ns"] if action else 0], dtype=np.int64
        )
        return frame

    def frames(self) -> list[dict]:
        """All rows of a stopped episode recorded with `write=False` (no pruning has happened)."""
        if not self.stopped:
            raise RuntimeError("stop the episode first")
        return [
            self._frame(
                self.t0_ns + i * self.period_ns, self.t0_ns + (i + 1) * self.period_ns
            )
            for i in range(self._row_count())
        ]

    def metrics(self) -> dict:
        rows = max(self.written, 1)
        return {
            "rows": self.written,
            "control_interval_ms": summarize(self.stats["control_interval_ms"]),
            "latency_ms": summarize(self.stats["latency_ms"]),
            "queue_ms": summarize(self.stats["queue_ms"]),
            "missing_rate": {key: value / rows for key, value in self.missing.items()},
            "action_valid_rate": self.action_rows / rows,
            "clamped_rate": self.clamped / rows,
        }
