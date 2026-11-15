"""What each saved episode was: `meta/roboloom_episodes.jsonl` in the dataset.

One line is appended when an episode is saved: its task, rows, quality metrics, what
the controllers reported when it ended (a policy's inference time, the chunks it
dropped, its error) and the operator's verdict when one was given. `roboloom label`
appends a line with the verdict afterwards. Lines are only ever appended; `read` merges
the lines of an episode, later ones winning.

LeRobot does not read this file: a dataset trains the same with or without it. It is
what an evaluation run is counted from (`summary`).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

EPISODES = "meta/roboloom_episodes.jsonl"
LABELS = ("success", "failure")


def check_label(label: object) -> str | None:
    """`label` as it is stored: None (no verdict) or one of LABELS."""
    if label is None or label == "":
        return None
    if label not in LABELS:
        raise ValueError(f"label must be {' or '.join(LABELS)}, not {label!r}")
    return str(label)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _append(root: Path, entry: dict) -> None:
    path = Path(root) / EPISODES
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(entry, default=str) + "\n").encode()
    with open(path, "ab+") as out:
        if out.seek(0, os.SEEK_END):
            out.seek(-1, os.SEEK_END)
            if out.read(1) != b"\n":  # a line cut off by a crash: not glued to it
                line = b"\n" + line
        out.write(line)  # append mode: at the end, wherever the position is
        out.flush()
        os.fsync(out.fileno())


def read(root: str | Path) -> dict[int, dict]:
    """Episode index -> its record. A line cut off by a crash is skipped."""
    path = Path(root) / EPISODES
    if not path.exists():
        return {}
    merged: dict[int, dict] = {}
    for line in path.read_text().splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict) or not isinstance(entry.get("episode"), int):
            continue
        if (
            "saved" in entry
        ):  # the episode itself: whatever the index held before is gone
            merged[entry["episode"]] = entry
        else:
            merged.setdefault(entry["episode"], {}).update(entry)
    return merged


def saved(
    root: str | Path,
    episode: int,
    task: str,
    frames: int,
    metrics: dict,
    label: str | None = None,
    note: str | None = None,
    controllers: dict | None = None,
) -> dict:
    """Record that `episode` was saved; returns the line written."""
    entry: dict[str, Any] = {
        "episode": int(episode),
        "saved": _now(),
        "task": task,
        "frames": int(frames),
        "metrics": metrics,
        "label": check_label(label),
    }
    if note:
        entry["note"] = str(note)
    if controllers:
        entry["controllers"] = controllers
    _append(Path(root), entry)
    return entry


def total(root: str | Path) -> int:
    """How many episodes the dataset under `root` holds."""
    info = Path(root) / "meta" / "info.json"
    if not info.exists():
        raise ValueError(f"{root} holds no meta/info.json: not a LeRobot dataset")
    return int(json.loads(info.read_text()).get("total_episodes", 0))


def label(
    root: str | Path, episode: int, verdict: str, note: str | None = None
) -> dict:
    """Give the saved `episode` its verdict (replacing an earlier one); returns the
    episode's record."""
    root = Path(root)
    count = total(root)
    if not 0 <= episode < count:
        held = f"episodes 0..{count - 1}" if count else "no episodes"
        raise ValueError(f"episode {episode} is not in {root} ({held})")
    checked = check_label(verdict)
    if checked is None:
        raise ValueError(f"label must be {' or '.join(LABELS)}")
    entry: dict[str, Any] = {
        "episode": int(episode),
        "label": checked,
        "labelled": _now(),
    }
    if note:
        entry["note"] = str(note)
    _append(root, entry)
    return read(root)[episode]


def summary(root: str | Path, episodes: int) -> str | None:
    """How many of the dataset's `episodes` carry each verdict; None when no episode
    has a record."""
    records = read(root)
    if not records:
        return None
    counts = {name: 0 for name in LABELS}
    for index, record in records.items():
        if index < episodes and record.get("label") in counts:
            counts[record["label"]] += 1
    judged = sum(counts.values())
    text = ", ".join(f"{count} {name}" for name, count in counts.items())
    rate = (
        f" ({100 * counts['success'] / judged:.0f}% of the labelled)" if judged else ""
    )
    return f"labels: {text}, {episodes - judged} not labelled{rate}"
