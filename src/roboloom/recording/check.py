"""`roboloom check-dataset`: is a recorded dataset whole, and what should training know.

Reads the files only (no LeRobot dataset object, so nothing lands in a cache and a
broken dataset does not send it looking on the Hub). Problems are what makes the dataset
wrong as it is: unreadable files, counts that disagree, a video that is not as long as
its episode. Notes are what a training run should know: rows whose action or observation
is not valid.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import journal, manifest


@dataclass
class DatasetReport:
    root: Path
    episodes: int = 0
    frames: int = 0
    summary: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def describe(self) -> str:
        lines = [f"dataset: {self.root}", *self.summary]
        lines.append("problems:" if self.problems else "problems: none")
        lines += [f"  {text}" for text in self.problems]
        if self.notes:
            lines.append("notes:")
            lines += [f"  {text}" for text in self.notes]
        return "\n".join(lines)


def _share(count: int, total: int) -> str:
    return f"{count} of {total} rows ({100 * count / max(total, 1):.2f}%)"


def check_dataset(root: str | Path, recover: bool = False) -> DatasetReport:
    """Check the dataset under `root`. `recover=True` first undoes a save that was
    interrupted (what recording into the dataset again does too)."""
    import numpy as np
    import pyarrow.parquet as pq

    root = Path(root)
    report = DatasetReport(root)
    info_path = root / "meta" / "info.json"
    if not info_path.exists():
        report.problems.append("no meta/info.json: not a LeRobot dataset")
        return report
    if (root / journal.JOURNAL).exists():
        if recover:
            journal.recover(root)
            report.notes.append("undid a save that had been interrupted")
        else:
            report.problems.append(
                "a save was interrupted and its episode is half written; "
                "`roboloom check-dataset --recover` (or recording into the dataset "
                "again) puts the dataset back to its last saved episode"
            )
    info = json.loads(info_path.read_text())
    fps = float(info.get("fps") or 0)
    report.episodes = int(info.get("total_episodes", 0))
    report.frames = int(info.get("total_frames", 0))
    features = info.get("features", {})
    videos = [k for k, f in features.items() if f.get("dtype") == "video"]
    listed = manifest.read(root)
    made = (
        f", recorded with roboloom {listed['roboloom']}"
        if listed.get("roboloom")
        else ""
    )
    report.summary.append(
        f"episodes: {report.episodes}, frames: {report.frames}, fps: {fps:g}, "
        f"robot: {info.get('robot_type')}{made}"
    )

    # -- the episodes' metadata -----------------------------------------------
    rows: list[dict] = []
    files = sorted((root / "meta" / "episodes").glob("*/*.parquet"))
    for path in files:
        try:
            keep = [c for c in pq.read_schema(path).names if not c.startswith("stats/")]
            rows += pq.read_table(path, columns=keep).to_pylist()
        except Exception as exc:  # noqa: BLE001 - e.g. no footer: the writer was killed
            report.problems.append(f"{path.relative_to(root)} is unreadable ({exc})")
    rows.sort(key=lambda r: r["episode_index"])
    if len(rows) != report.episodes:
        report.problems.append(
            f"info.json counts {report.episodes} episodes, meta/episodes lists {len(rows)}"
        )
    if [r["episode_index"] for r in rows] != list(range(len(rows))):
        report.problems.append("episode indices in meta/episodes are not 0..N-1")
    listed_frames = sum(int(r["length"]) for r in rows)
    if listed_frames != report.frames:
        report.problems.append(
            f"info.json counts {report.frames} frames, the episodes list {listed_frames}"
        )

    # -- the rows ---------------------------------------------------------------
    data_files = sorted((root / "data").glob("*/*.parquet"))
    per_episode: dict[int, int] = {}
    total = 0
    invalid: dict[str, int] = {}
    zero_actions = 0
    for path in data_files:
        try:
            wanted = [
                c
                for c in pq.read_schema(path).names
                if c in ("episode_index", "action") or c.endswith(".valid")
            ]
            table = pq.read_table(path, columns=wanted)
        except Exception as exc:  # noqa: BLE001 - e.g. no footer: the writer was killed
            report.problems.append(f"{path.relative_to(root)} is unreadable ({exc})")
            continue
        total += table.num_rows
        index = np.asarray(table.column("episode_index").to_numpy())
        for episode, count in zip(*np.unique(index, return_counts=True), strict=True):
            per_episode[int(episode)] = per_episode.get(int(episode), 0) + int(count)
        for column in wanted:
            if column.endswith(".valid"):
                values = np.asarray(table.column(column).to_numpy(zero_copy_only=False))
                invalid[column] = invalid.get(column, 0) + int((values == 0).sum())
        if "action" in wanted and table.num_rows:
            action = np.stack(table.column("action").to_numpy(zero_copy_only=False))
            zero_actions += int((action == 0).all(axis=1).sum())
    for row in rows:
        have = per_episode.get(int(row["episode_index"]), 0)
        if have != int(row["length"]):
            report.problems.append(
                f"episode {row['episode_index']}: {have} rows in data/, its metadata "
                f"says {row['length']}"
            )
    extra = sorted(set(per_episode) - {int(r["episode_index"]) for r in rows})
    if extra:
        report.problems.append(f"data/ holds rows of unlisted episodes {extra}")

    # -- the videos -------------------------------------------------------------
    template = info.get("video_path") or ""
    video_files = set()
    for row in rows:
        for key in videos:
            names = [
                f"videos/{key}/{part}"
                for part in (
                    "chunk_index",
                    "file_index",
                    "from_timestamp",
                    "to_timestamp",
                )
            ]
            if any(name not in row or row[name] is None for name in names):
                report.problems.append(
                    f"episode {row['episode_index']}: no video listed for {key}"
                )
                continue
            chunk, file, start, end = (row[name] for name in names)
            path = root / template.format(
                video_key=key, chunk_index=int(chunk), file_index=int(file)
            )
            video_files.add(path)
            if not path.exists():
                report.problems.append(
                    f"episode {row['episode_index']}: {path.relative_to(root)} is missing"
                )
            frames = (float(end) - float(start)) * fps
            if abs(frames - int(row["length"])) > max(2.0, 0.02 * int(row["length"])):
                report.problems.append(
                    f"episode {row['episode_index']}: {key} has {frames:.0f} video "
                    f"frames for {row['length']} rows"
                )
    report.summary.append(
        f"files: {len(data_files)} data, {len(files)} episode metadata, "
        f"{len(video_files)} video"
    )

    # -- what training should know ------------------------------------------------
    for column, count in sorted(invalid.items()):
        if count:
            report.notes.append(f"{column} is 0 in {_share(count, total)}")
    if zero_actions:
        report.notes.append(
            f"action is all zeros in {_share(zero_actions, total)}: recorded before "
            "rows without a command kept the held target; leave them out "
            "(action.valid) and recompute the statistics before training"
        )
    staged = root / journal.STAGING
    if staged.exists() and any(staged.rglob("*.*")):
        report.notes.append(
            "images/ holds frames of an episode that was never saved (removed the "
            "next time the dataset is recorded into)"
        )
    return report
