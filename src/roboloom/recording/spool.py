"""Lossless staging for episodes that have not entered the LeRobot writer."""

from __future__ import annotations

import json
import shutil
from collections import deque
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from zipfile import ZipFile

import numpy as np

from ..version import version
from .journal import atomic_replace

DIRECTORY = "roboloom_spool"
METADATA = "episode.json"
COMMITTED = "committed.json"


def _directories(root: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in (root / DIRECTORY).glob("*")
            if path.name.isascii() and path.name.isdigit() and path.is_dir()
        ),
        key=lambda path: int(path.name),
    )


def metadata(path: Path) -> dict:
    return json.loads((path / METADATA).read_text())


def _ready(path: Path) -> bool:
    if (path / COMMITTED).exists():
        return False
    try:
        entry = metadata(path)
    except (OSError, ValueError):
        return False
    return isinstance(entry, dict) and entry.get("ready") is True


def ready(root: Path) -> list[Path]:
    return [path for path in _directories(root) if _ready(path)]


def counts(root: Path) -> tuple[int, int]:
    paths = [p for p in _directories(root) if not (p / COMMITTED).exists()]
    accepted = sum(_ready(path) for path in paths)
    return accepted, len(paths) - accepted


def next_sequence(root: Path) -> int:
    paths = _directories(root)
    return int(paths[-1].name) + 1 if paths else 0


def prune(root: Path) -> None:
    for path in (root / DIRECTORY).glob(".*.removed"):
        sequence = path.name.removeprefix(".").removesuffix(".removed")
        if path.is_dir() and sequence.isascii() and sequence.isdigit():
            shutil.rmtree(path)
    for path in _directories(root):
        if not _ready(path):
            remove(path)


def remove(path: Path) -> None:
    # Hide the episode before deleting any files, including its commit receipt.
    removed = path.with_name(f".{path.name}.removed")
    try:
        path.rename(removed)
    except FileNotFoundError:
        return
    shutil.rmtree(removed)


def _write_image(stem: Path, array: np.ndarray) -> None:
    if array.dtype == np.uint8 and (
        array.ndim == 2 or (array.ndim == 3 and array.shape[2] in (3, 4))
    ):
        from PIL import Image

        Image.fromarray(array).save(stem.with_suffix(".png"), compress_level=1)
    else:
        np.save(stem.with_suffix(".npy"), array, allow_pickle=False)


class EpisodeSpool:
    def __init__(
        self,
        root: Path,
        image_keys: tuple[str, ...],
        threads: int,
        *,
        start_at: int = 0,
    ):
        self.image_keys = image_keys
        if any(Path(key).name != key or key == ".." for key in image_keys):
            raise ValueError("image feature keys must be filenames")
        self.seq = max(start_at, next_sequence(root))
        self.path = root / DIRECTORY / f"{self.seq:06d}"
        self.path.mkdir(parents=True)
        for key in image_keys:
            (self.path / key).mkdir()
        self._pool = (
            ThreadPoolExecutor(threads, thread_name_prefix="spool-image")
            if image_keys and threads > 0
            else None
        )
        self._limit = max(1, threads * 8)
        self._writes: deque[Future[None]] = deque()
        self._error: Exception | None = None
        self._columns: dict[str, list[np.ndarray]] = {}
        self._frames = 0
        self._closed = False

    def _join_write(self) -> None:
        try:
            self._writes.popleft().result()
        except Exception as exc:  # noqa: BLE001 - surface image failures at stop
            self._error = self._error or exc

    def add(self, row: dict) -> None:
        if self._closed:
            raise RuntimeError("the spool is closed")
        for key, value in row.items():
            if key == "task":
                continue
            array = np.array(value, copy=True)
            if array.dtype.hasobject:
                raise ValueError(f"cannot spool {key} with object dtype")
            if key not in self.image_keys:
                self._columns.setdefault(key, []).append(array)
                continue
            stem = self.path / key / f"frame-{self._frames:06d}"
            if self._pool is None:
                try:
                    _write_image(stem, array)
                except Exception as exc:  # noqa: BLE001 - surface image failures at stop
                    self._error = self._error or exc
            else:
                while self._writes and (
                    len(self._writes) >= self._limit or self._writes[0].done()
                ):
                    self._join_write()
                self._writes.append(self._pool.submit(_write_image, stem, array))
        self._frames += 1

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown()
        while self._writes:
            self._join_write()
        if self._error is not None:
            raise RuntimeError(
                f"could not write spool images: {self._error}"
            ) from self._error
        # np.savez only accepts allow_pickle on newer NumPy versions.
        with ZipFile(self.path / "rows.npz", "w") as archive:
            for key, values in self._columns.items():
                with archive.open(f"{key}.npy", "w", force_zip64=True) as column:
                    np.save(column, np.stack(values), allow_pickle=False)
        self._columns.clear()
        self._closed = True

    def mark_ready(self, meta: dict) -> Path:
        if not self._closed:
            raise RuntimeError("close the spool first")
        entry = {
            **meta,
            "frames": self._frames,
            "images": self.image_keys,
            "roboloom": version(),
            "ready": True,
        }
        atomic_replace(self.path / METADATA, json.dumps(entry).encode())
        return self.path

    def discard(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(cancel_futures=True)
        remove(self.path)


def rows(path: Path, entry: dict | None = None) -> Iterator[dict]:
    if entry is None:
        entry = metadata(path)
    image_keys = entry["images"]
    if any(Path(key).name != key or key == ".." for key in image_keys):
        raise ValueError("image feature keys must be filenames")
    with np.load(path / "rows.npz", allow_pickle=False) as data:
        columns = dict(data)
    for i in range(entry["frames"]):
        row = {key: column[i] for key, column in columns.items()}
        for key in image_keys:
            stem = path / key / f"frame-{i:06d}"
            png = stem.with_suffix(".png")
            if png.exists():
                from PIL import Image

                with Image.open(png) as image:
                    row[key] = np.array(image)
            else:
                row[key] = np.load(stem.with_suffix(".npy"), allow_pickle=False)
        yield {**row, "task": entry["task"]}
