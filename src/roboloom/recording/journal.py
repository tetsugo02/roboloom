"""Keep a dataset readable whatever happens to the recording process.

LeRobot 0.6.1 writes the footer of its parquet files (the rows, and the episodes'
metadata) only in `finalize()`, and appends each video to the previous one. A process
killed before that leaves `info.json` counting episodes whose files cannot be read. Two
steps avoid it:

- `checkpoint(dataset)` after every saved episode closes those files; the next episode
  starts new ones, as after `LeRobotDataset.resume()`. A dataset then holds one data
  file, one metadata file and one video per camera for each episode.
- `begin(root)` before a save notes which files exist and copies the small metadata
  files; `commit(root)` forgets the note once the episode is closed. `recover(root)`
  undoes a save that did not get that far: the next time the dataset is opened, or at
  once when the save raised.

This guards against the process dying (a crash, kill, a full disk), not against a power
loss: LeRobot does not sync its files to the disk.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import shutil
from importlib import metadata
from pathlib import Path
from typing import Any

JOURNAL = "meta/roboloom_saving.json"
# where a save adds files; with a checkpoint after every episode it only ever adds
WRITTEN = ("data", "videos", "meta/episodes")
# rewritten by every save
REWRITTEN = ("meta/info.json", "meta/stats.json", "meta/tasks.parquet")
STAGING = "images"  # frames waiting to be encoded; nothing is kept there between saves
CHECKPOINT_VERSION = "0.6.1"  # the LeRobot whose writer `checkpoint` knows


def _files(root: Path) -> list[str]:
    return sorted(
        str(path.relative_to(root))
        for name in WRITTEN
        for path in (root / name).rglob("*")
        if path.is_file()
    )


def _replace(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, path)


def begin(root: Path) -> None:
    """Call before `save_episode`: what `recover` puts back if the save does not finish."""
    kept = {}
    for name in REWRITTEN:
        path = root / name
        kept[name] = (
            base64.b64encode(path.read_bytes()).decode() if path.exists() else None
        )
    note = {"files": _files(root), "rewritten": kept}
    _replace(root / JOURNAL, json.dumps(note).encode())


def commit(root: Path) -> None:
    """The episode is closed (`checkpoint`): forget the note."""
    (root / JOURNAL).unlink(missing_ok=True)


def clean(root: Path) -> None:
    """Remove what an interrupted episode left behind and no saved episode needs: frames
    staged for encoding (they would be appended to the next episode's video) and the
    encoder's temporary directories. Only while no episode is being recorded or saved."""
    shutil.rmtree(root / STAGING, ignore_errors=True)
    for path in root.glob("tmp*"):  # tempfile.mkdtemp(dir=root) of the video encoder
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


def recover(root: Path) -> bool:
    """Undo a save that did not finish; True when there was one. The dataset is then as
    it was before that save: the episode is lost, the earlier ones are intact."""
    note_path = root / JOURNAL
    if not note_path.exists():
        return False
    note = json.loads(note_path.read_text())
    keep = set(note["files"])
    for name in WRITTEN:
        # deepest first, so directories the save created are empty when reached
        for path in sorted((root / name).rglob("*"), reverse=True):
            if path.is_file() and str(path.relative_to(root)) not in keep:
                path.unlink()
            elif path.is_dir() and not any(path.iterdir()):
                path.rmdir()
    for name, content in note["rewritten"].items():
        path = root / name
        if content is None:
            path.unlink(missing_ok=True)
        else:
            _replace(path, base64.b64decode(content))
    clean(root)
    note_path.unlink()
    return True


def lerobot_version() -> str:
    try:
        return metadata.version("lerobot")
    except metadata.PackageNotFoundError:
        return ""


def checkpoint(dataset: Any) -> bool:
    """Close the files of the episodes saved so far and make the next episode start new
    ones. False when this LeRobot is not the one whose writer is known here (the caller
    then finalizes and resumes the dataset, which has the same effect, slower).

    The writer keeps where the last episode went in three places; cleared, with the
    last episode as the only loaded one, they are what `LeRobotDataset.resume()` builds,
    without reading the metadata of every episode again."""
    if lerobot_version() != CHECKPOINT_VERSION:
        return False
    writer, meta = dataset.writer, dataset.meta
    writer.close_writer()
    meta._close_writer()  # flushes the buffered episode metadata, then closes
    latest = meta.latest_episode
    if latest is not None:  # each value is a one-element list (the row to write)
        meta.episodes = [
            {k: v[0] if isinstance(v, list) else v for k, v in latest.items()}
        ]
    meta.latest_episode = None
    writer._latest_episode = None
    return True


def abandon(dataset: Any) -> None:
    """Make a dataset whose save failed write nothing more. Its `__del__` would otherwise
    flush the failed episode's metadata into the files `recover` has put back."""
    writer, meta = dataset.writer, dataset.meta
    with contextlib.suppress(Exception):
        writer.cancel_pending_videos()
    with contextlib.suppress(Exception):
        if writer.image_writer is not None:
            writer.image_writer.stop()
            writer.image_writer = None
    for owner in (writer, meta):
        with contextlib.suppress(Exception):
            if owner._pq_writer is not None:
                owner._pq_writer.close()
        owner._pq_writer = None
    with contextlib.suppress(Exception):
        meta._metadata_buffer.clear()
    writer._finalized = meta._finalized = True
    dataset._is_finalized = True


def video_mismatches(dataset: Any, tolerance: float = 2.0) -> list[str]:
    """Cameras whose video of the episode just saved is not as long as its rows (frames
    left from an interrupted episode, or frames that could not be written)."""
    latest = dataset.meta.latest_episode
    if latest is None:
        return []

    def one(key: str) -> float:
        value = latest[key]
        return float(value[0] if isinstance(value, list) else value)

    rows, fps = one("length"), float(dataset.meta.fps)
    out = []
    for key in dataset.meta.video_keys:
        start, end = f"videos/{key}/from_timestamp", f"videos/{key}/to_timestamp"
        if start not in latest or end not in latest:
            continue
        frames = (one(end) - one(start)) * fps
        if abs(frames - rows) > max(tolerance, 0.02 * rows):
            out.append(f"{key}: {frames:.0f} video frames for {rows:.0f} rows")
    return out
