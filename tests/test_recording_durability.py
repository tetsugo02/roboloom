"""A saved episode stays readable whatever happens to the recording process, and a save
that fails or is interrupted is undone instead of leaving half an episode."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import numpy as np
import pytest
from conftest import mock_project
from test_recording import MS, msg
from test_video_codec import CAMERA, COLOURS, _cfg, _frame, _record, _streams

from roboloom.cli import main
from roboloom.config import load_config
from roboloom.core.protocol import Envelope
from roboloom.recording import EpisodeRecorder, SaveFailed, journal, manifest
from roboloom.recording.check import check_dataset
from roboloom.runtime.session import Session

TESTS = str(Path(__file__).resolve().parent)
ROWS = len(COLOURS)


def _dataset(root: Path):
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    return LeRobotDataset("local/codec", root=root, video_backend="pyav")


def _check(root: Path, episodes: int) -> None:
    """The dataset on disk reads back as `episodes` full episodes, video included."""
    ds = _dataset(root)
    assert ds.meta.total_episodes == episodes
    assert ds.meta.total_frames == len(ds) == episodes * ROWS
    assert not (root / journal.JOURNAL).exists()
    for index in (0, len(ds) - 1):  # the first and the last row, through the video
        row = ds[index]
        mean = row[CAMERA].numpy().reshape(3, -1).mean(axis=1) * 255
        assert np.abs(mean - COLOURS[index % ROWS]).max() < 25, (index, mean)
    assert _streams(root) == [("h264", ROWS)] * episodes  # one video per episode


def _child(tmp_path: Path, body: str) -> None:
    """Run `body` in another process with `recorder` (on the dataset under `tmp_path`)
    and `record()` (one full episode) defined; it ends as the body says."""
    code = (
        textwrap.dedent(
            """
            import os, sys, time, traceback
            from pathlib import Path
            from test_video_codec import _cfg, _frame, _record
            from roboloom.core.protocol import Envelope
            from roboloom.recording import EpisodeRecorder

            cfg = _cfg(Path(sys.argv[1]))
            recorder = EpisodeRecorder(cfg, **cfg.recorder)
            clock = [1_000_000_000]

            def record():
                _record(recorder, clock[0])
                clock[0] += 10_000_000_000

            try:
            """
        )
        + textwrap.indent(textwrap.dedent(body).strip(), "    ")
        # a failure must not wait for the image writer's threads at interpreter exit
        + "\nexcept BaseException:\n    traceback.print_exc()\n    os._exit(1)\n"
    )
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([TESTS, *sys.path])}
    done = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 7, done.stdout[-2000:] + done.stderr[-4000:]


def test_saved_episodes_survive_a_killed_process(tmp_path):
    # no close(), no finalizers: what `save` returned for must already be on disk
    _child(tmp_path, "record(); record(); os._exit(7)")
    _check(tmp_path / "data", 2)


def test_appending_keeps_the_earlier_episodes_when_the_process_is_killed(tmp_path):
    _child(tmp_path, "record(); recorder.close(); os._exit(7)")
    _child(
        tmp_path,
        """
        record()
        recorder.start("cut short", clock[0])  # dies inside the next episode
        t = clock[0]
        for name, sensor in cfg.sensors.items():
            image = _frame((9, 9, 9), sensor.shape)
            recorder.ingest(
                name, Envelope("image", name, "b", 0, t, t, {"image": image}, t_receive_ns=t)
            )
        recorder.poll(t + 400_000_000)
        assert recorder.written >= 3
        staged = Path(cfg.output) / "images"
        deadline = time.monotonic() + 30  # the frames are written on other threads
        while len(list(staged.rglob("*.png"))) < 3 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert len(list(staged.rglob("*.png"))) >= 3
        os._exit(7)
        """,
    )
    root = tmp_path / "data"
    _check(root, 2)
    # the frames the dead process left staged do not get into the next episode's video
    cfg = _cfg(tmp_path)
    recorder = EpisodeRecorder(cfg, **cfg.recorder)
    _record(recorder, 1_000_000_000)
    recorder.close()
    _check(root, 3)


@pytest.mark.parametrize("where", ["video", "info"])
def test_a_save_interrupted_by_a_kill_is_undone_when_the_dataset_opens(tmp_path, where):
    patch = {
        # after the rows were written, before the video
        "video": "writer.DatasetWriter._save_episode_video = lambda *a, **k: os._exit(7)",
        # after info.json counted the episode, before its metadata was written
        "info": "metadata.write_stats = lambda *a, **k: os._exit(7)",
    }[where]
    _child(
        tmp_path,
        f"""
        record()
        import lerobot.datasets.dataset_metadata as metadata
        import lerobot.datasets.dataset_writer as writer
        {patch}
        record()
        """,
    )
    root = tmp_path / "data"
    assert (root / journal.JOURNAL).exists()
    if where == "info":  # what a reader would trust: one episode more than there is
        assert json.loads((root / "meta/info.json").read_text())["total_episodes"] == 2
    cfg = _cfg(tmp_path)
    recorder = EpisodeRecorder(cfg, **cfg.recorder)
    recorder.open_dataset()
    assert recorder.recovered and recorder.episodes == 1
    _check(root, 1)
    _record(recorder, 1_000_000_000)
    recorder.close()
    _check(root, 2)


def test_a_failed_save_drops_the_episode_and_recording_goes_on(tmp_path, monkeypatch):
    import lerobot.datasets.dataset_writer as writer

    cfg = _cfg(tmp_path)
    recorder = EpisodeRecorder(cfg, **cfg.recorder)
    _record(recorder, 1_000_000_000)
    real = writer.DatasetWriter._save_episode_video

    def full(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(writer.DatasetWriter, "_save_episode_video", full)
    with pytest.raises(SaveFailed, match="dropped.*No space left.*intact"):
        _record(recorder, 11_000_000_000)
    assert not recorder.active and not recorder.stopped and recorder.episodes == 1
    monkeypatch.setattr(writer.DatasetWriter, "_save_episode_video", real)
    recorder.discard()  # what a Session sends after a failure: still fine
    _record(recorder, 21_000_000_000)
    assert recorder.episodes == 2
    recorder.close()
    _check(tmp_path / "data", 2)


def test_frames_that_do_not_match_the_rows_fail_the_save(tmp_path):
    cfg = _cfg(tmp_path)
    recorder = EpisodeRecorder(cfg, **cfg.recorder)
    _record(recorder, 1_000_000_000)
    # frames beyond the episode's rows in its staging directory, as an image writer
    # that lost its place would leave them
    from PIL import Image

    staged = Path(cfg.output) / "images" / CAMERA / "episode-000001"
    staged.mkdir(parents=True)
    for k in range(ROWS, ROWS + 40):
        Image.fromarray(_frame((1, 2, 3), (48, 64))).save(staged / f"frame-{k:06d}.png")
    with pytest.raises(SaveFailed, match="video frames for 5 rows"):
        _record(recorder, 11_000_000_000)
    _record(recorder, 21_000_000_000)
    recorder.close()
    _check(tmp_path / "data", 2)


def test_another_lerobot_closes_the_files_through_its_public_api(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "CHECKPOINT_VERSION", "not this one")
    cfg = _cfg(tmp_path)
    recorder = EpisodeRecorder(cfg, **cfg.recorder)
    _record(recorder, 1_000_000_000)
    _record(recorder, 11_000_000_000)
    assert recorder.episodes == 2
    _check(tmp_path / "data", 2)  # before close(): each save finalized the dataset
    recorder.close()


def test_a_missing_sample_repeats_the_last_valid_one():
    cfg = load_config(
        "examples/mock/config.yaml"
    )  # 10 fps; max_age_ms decides validity
    recorder = EpisodeRecorder(cfg)
    t = time.monotonic_ns()
    recorder.start("gap", t, write=False)
    recorder.ingest(
        "follower",
        msg(
            "follower_state",
            0,
            t - MS,
            t - MS,
            t - MS,
            {"positions": [2100] * 17, "target": [2090] * 17},
        ),
    )
    late = int(cfg.max_age_ms["follower"] * MS) + 250 * MS
    recorder.stop(t + late)
    rows = recorder.frames()
    first, last = rows[0], rows[-1]
    assert first["observation.meta.follower.valid"][0] == 1
    assert last["observation.meta.follower.valid"][0] == 0  # too old for this row
    assert last["observation.state"][0] == 2100  # ... yet not zero
    assert last["action"][0] == 2090 and last["action.valid"][0] == 0  # the held target
    # a source that never sent anything has nothing to repeat
    assert np.count_nonzero(last["observation.images.camera"]) == 0
    assert (
        recorder.frames()[0]["observation.state"][0] == 2100
    )  # frames() is repeatable


def test_an_episode_saved_through_the_dataflow_survives_killing_it(tmp_path):
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    project = mock_project(tmp_path / ".roboloom")
    session = Session.launch(project / "config.yaml", log_dir=tmp_path / "logs")
    try:
        session.wait_ready(60)
        saved = session.record("pick", 2.0)
        assert saved.saved
        root = Path(session.cfg.output)
        session.start("cut short")  # an episode is running when every node dies
        time.sleep(0.7)
        os.killpg(session.process.pid, signal.SIGKILL)
        session.process.wait()
    finally:
        session.close()
    ds = LeRobotDataset(f"local/{root.name}", root=root, video_backend="pyav")
    assert ds.meta.total_episodes == 1 and len(ds) == saved.frames
    assert ds[len(ds) - 1]["observation.images.camera"].shape[0] == 3  # decodes
    # how it was recorded: the version, the units and the configuration of the run
    listed = manifest.read(root)
    assert listed["roboloom"] and listed["robot"] == "rakuda2"
    assert listed["units"]["action"] == ["dynamixel_count"] * 17
    (run,) = listed["sessions"]
    assert run["first_episode"] == 0 and run["mode"] == "mock"
    kept = (root / manifest.CONFIGS / f"{run['config']}.json").read_text()
    assert json.loads(kept)["followers"]["follower"]["control_hz"] == 120
    assert str(tmp_path) not in kept  # no directories of this machine
    # the next session appends to it; the frames the dead recorder staged are not used
    with Session.launch(project / "config.yaml", log_dir=tmp_path / "logs2") as s:
        s.wait_ready(60)
        again = s.record("pick", 2.0)
    ds = LeRobotDataset(f"local/{root.name}", root=root, video_backend="pyav")
    assert ds.meta.total_episodes == 2 and len(ds) == saved.frames + again.frames
    assert ds[len(ds) - 1]["observation.images.camera"].shape[0] == 3
    runs = manifest.read(root)["sessions"]
    assert [r["first_episode"] for r in runs] == [0, 1]
    assert runs[0]["config"] == runs[1]["config"]  # the same configuration: one copy
    checked = check_dataset(root)
    assert checked.ok and checked.episodes == 2, checked.describe()


# -- check-dataset ----------------------------------------------------------------


def test_check_dataset_finds_what_a_killed_recorder_leaves(tmp_path, capsys):
    _child(
        tmp_path,
        """
        record(); record()
        import lerobot.datasets.dataset_metadata as metadata
        metadata.write_stats = lambda *a, **k: os._exit(7)
        record()
        """,
    )
    root = tmp_path / "data"
    broken = check_dataset(root)
    assert not broken.ok
    text = broken.describe()
    assert "a save was interrupted" in text and "is unreadable" in text
    assert "info.json counts 3 episodes, meta/episodes lists 2" in text
    with pytest.raises(SystemExit):
        main(["check-dataset", str(root)])
    main(["check-dataset", str(root), "--recover"])
    out = capsys.readouterr().out
    assert "problems: none" in out and "undid a save" in out
    assert (
        "episodes: 2, frames: 10" in out and "files: 2 data, 2 episode metadata" in out
    )
    _check(root, 2)


def test_check_dataset_notes_rows_that_are_not_valid(tmp_path):
    from dataclasses import replace

    cfg = _cfg(tmp_path)
    cfg = replace(cfg, max_age_ms={name: 50 for name in cfg.sensors})
    recorder = EpisodeRecorder(cfg, **cfg.recorder)
    start, period = 1_000_000_000, 100_000_000
    recorder.start("gap", start)
    for k, colour in enumerate(COLOURS):
        if k in (2, 3):
            continue  # the camera misses two rows
        t = start + k * period
        for name, sensor in cfg.sensors.items():
            image = _frame(colour, sensor.shape)
            recorder.ingest(
                name,
                Envelope("image", name, "b", k, t, t, {"image": image}, t_receive_ns=t),
            )
    recorder.stop(start + ROWS * period)
    assert recorder.save() == ROWS  # the video still has one frame per row
    recorder.close()
    root = tmp_path / "data"
    checked = check_dataset(root)
    assert checked.ok, checked.describe()
    assert "observation.meta.camera.valid is 0 in 2 of 5 rows (40.00%)" in checked.notes
    # those rows repeat the last frame the camera sent (COLOURS[1]), not black
    row = _dataset(root)[3]
    mean = row[CAMERA].numpy().reshape(3, -1).mean(axis=1) * 255
    assert np.abs(mean - COLOURS[1]).max() < 25, mean
