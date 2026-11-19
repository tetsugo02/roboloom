"""Background saves exercise the real LeRobot writer and mock runtime messages."""

from __future__ import annotations

import json
import queue
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pyarrow.parquet as pq
import pytest
from conftest import mock_project
from test_episode_records import _stopped
from test_video_codec import CAMERA, COLOURS, STILL, _cfg, _frame, _record, _streams

from roboloom.config import load_config
from roboloom.core.protocol import Publisher
from roboloom.errors import ConfigError
from roboloom.recording import EpisodeRecorder, episodes, journal, spool
from roboloom.recording.check import check_dataset
from roboloom.recording.saver import BackgroundSaver
from roboloom.runtime import node as runtime
from roboloom.runtime.session import Session, SessionError

S = 1_000_000_000


def _writer(tmp_path) -> EpisodeRecorder:
    cfg = _cfg(tmp_path)
    cfg.recorder["background_save"] = True
    writer = EpisodeRecorder(cfg, **cfg.recorder)
    writer.open_dataset()
    return writer


def _save(writer, *paths):
    reports = []
    saver = BackgroundSaver(writer, reports.append, close_writer=True)
    try:
        for ident, path in enumerate(paths):
            saver.submit(path, ident)
        assert saver.drain(20)
    finally:
        saver.stop()
    return reports


def test_spool_round_trip_matches_direct_parquet_rows_and_video(tmp_path):
    cfg = _cfg(tmp_path / "direct")
    direct = EpisodeRecorder(cfg, **cfg.recorder)
    _record(direct, S)
    direct.close()

    writer = _writer(tmp_path / "background")
    _stopped(writer, S)
    path = writer.enqueue()
    staged = list(spool.rows(path))
    for k, row in enumerate(staged):
        assert row["task"] == "colours"
        assert row["observation.meta.camera.seq"].dtype == np.int64
        assert row["observation.meta.camera.seq"].shape == (1,)
        for key, name in ((CAMERA, "camera"), (STILL, "still")):
            assert row[key].dtype == np.uint8
            np.testing.assert_array_equal(
                row[key], _frame(COLOURS[k], writer.cfg.sensors[name].shape)
            )

    (report,) = _save(writer, path)
    assert report["saved_frames"] == len(COLOURS)
    assert writer.root is not None
    assert (
        _streams(writer.root) == _streams(Path(cfg.output)) == [("h264", len(COLOURS))]
    )

    def parquet(root):
        file = next((root / "data").rglob("*.parquet"))
        keys = [k for k in pq.read_schema(file).names if k not in (CAMERA, STILL)]
        return pq.read_table(file, columns=keys)

    assert parquet(writer.root).equals(parquet(Path(cfg.output)))
    assert not path.exists()


def test_spool_preserves_non_rgb_image_arrays(tmp_path):
    episode = spool.EpisodeSpool(tmp_path, ("depth", "float_image"), threads=2)
    depth = np.array([[[0], [65535]], [[900], [1025]]], dtype=np.uint16)
    floats = np.array([[0.4, 0.1], [0.2, 1.0]], dtype=np.float32)
    episode.add({"task": "depth", "depth": depth, "float_image": floats})
    episode.close()
    path = episode.mark_ready({"task": "depth"})
    (row,) = spool.rows(path)
    for key, expected in [("depth", depth), ("float_image", floats)]:
        assert row[key].dtype == expected.dtype and row[key].shape == expected.shape
        np.testing.assert_array_equal(row[key], expected)


def test_queue_order_and_episode_records(tmp_path):
    writer = _writer(tmp_path)
    _stopped(writer, S, "first")
    metrics = writer.metrics()
    controllers = {"policy": {"state": "ready"}}
    first = writer.enqueue("success", "picked up", controllers)
    _stopped(writer, 2 * S, "second")
    second = writer.enqueue("failure")

    reports = _save(writer, first, second)
    assert [(r["save_id"], r["task"], r["index"]) for r in reports] == [
        (0, "first", 0),
        (1, "second", 1),
    ]
    records = episodes.read(Path(writer.cfg.output))
    assert records[0]["label"] == "success" and records[0]["note"] == "picked up"
    assert records[0]["controllers"] == controllers and records[0]["metrics"] == metrics
    assert records[1]["label"] == "failure"
    assert not first.exists() and not second.exists()


@pytest.mark.parametrize("where", ["import", "save"])
def test_dropped_episode_does_not_contaminate_the_next_save(
    tmp_path, monkeypatch, where
):
    writer = _writer(tmp_path)
    _stopped(writer, S, "broken")
    first = writer.enqueue()
    _stopped(writer, 2 * S, "next")
    second = writer.enqueue()

    if where == "import":
        # Fail only after the first row was handed to LeRobot (including image writes).
        (first / CAMERA / "frame-000001.png").unlink()
    else:

        def fail_video(*args, **kwargs):
            raise OSError("encoder failure")

        monkeypatch.setattr(writer.dataset.writer, "_save_episode_video", fail_video)

    broken, saved = _save(writer, first, second)
    assert broken["task"] == "broken" and broken["dropped"] and broken["error"]
    assert saved["task"] == "next" and saved["index"] == 0
    root = Path(writer.cfg.output)
    assert _streams(root) == [("h264", len(COLOURS))]
    assert check_dataset(root).ok and episodes.read(root)[0]["task"] == "next"
    assert not first.exists() and not second.exists()


def test_discard_and_label_validation(tmp_path):
    writer = _writer(tmp_path)
    try:
        _stopped(writer, S)
        assert writer.spool is not None
        path = writer.spool.path
        with pytest.raises(ValueError, match="label must be success or failure"):
            writer.enqueue("succes")
        assert writer.stopped and writer.episodes == 0
        assert not (path / spool.METADATA).exists()
        writer.discard()
        assert not path.exists()
        _stopped(writer, 2 * S)
        assert writer.spool is not None and writer.spool.seq > int(path.name)
    finally:
        writer.discard()
        writer.close()


def test_spool_surfaces_image_write_failure_at_close(tmp_path, monkeypatch):
    def fail(*_):
        raise OSError("disk full")

    monkeypatch.setattr(spool, "_write_image", fail)
    episode = spool.EpisodeSpool(tmp_path, ("image",), threads=2)
    episode.add({"task": "broken", "image": np.zeros((2, 2, 3), dtype=np.uint8)})
    with pytest.raises(RuntimeError, match="disk full"):
        episode.close()
    episode.discard()


@pytest.mark.parametrize(
    ("setting", "message"),
    [
        (
            "streaming_encoding: true",
            "set background_save or streaming_encoding to false",
        ),
        ("max_pending_saves: 0", "max_pending_saves must be an integer"),
        ("max_pending_saves: true", "max_pending_saves must be an integer"),
        ("max_pending_saves: 2.5", "max_pending_saves must be an integer"),
        ("background_save: nope", "background_save must be a bool"),
    ],
)
def test_background_config(tmp_path, setting, message):
    project = mock_project(tmp_path)
    path = project / "nodes/recorder.yaml"
    settings = [
        line
        for line in path.read_text().splitlines()
        if not line.startswith(setting.split(":")[0] + ":")
    ]
    path.write_text("\n".join([*settings, setting, ""]))
    with pytest.raises(ConfigError, match=f"recorder.yaml.*{message}"):
        load_config(project / "config.yaml")


def _node(monkeypatch, cfg, run):
    """Run the recorder loop on scripted events and assert dora sends use its thread."""
    inputs: queue.Queue = queue.Queue()
    outputs: queue.Queue = queue.Queue()
    sender = Publisher("session")
    failure = []

    def event(_):
        try:
            return inputs.get(timeout=0.02)
        except queue.Empty:
            return None, None

    def prepare(_, open_dataset):
        open_dataset()
        return True

    def command(name, **fields):
        inputs.put(("session", sender.make("session", {"command": name, **fields})))

    def receive(output, **fields):
        deadline = time.monotonic() + 20
        while (left := deadline - time.monotonic()) > 0:
            name, report = outputs.get(timeout=left)
            if name == output and all(
                report.get(key) == value for key, value in fields.items()
            ):
                return report
        pytest.fail(f"no {output} with {fields}")

    class Node:
        def send_output(self, output, data):
            from roboloom.core.protocol import Envelope

            assert threading.current_thread() is thread
            outputs.put((output, Envelope.decode(data).payload))

    def loop():
        try:
            runtime._recorder(Node(), cfg)
        except BaseException as exc:  # noqa: BLE001 - re-raised by the test thread owner
            failure.append(exc)

    monkeypatch.setattr(runtime, "_event", event)
    monkeypatch.setattr(runtime, "_prepare", prepare)
    thread = threading.Thread(target=loop)
    thread.start()
    try:
        run(command, receive)
    finally:
        command("quit")
        thread.join(25)
        assert not thread.is_alive()
        if failure:
            raise failure[0]


def test_recorder_recovers_prunes_and_drains_while_taking_events(tmp_path, monkeypatch):
    writer = _writer(tmp_path)
    _stopped(writer, S, "interrupted")
    ready = writer.enqueue("success")
    _stopped(writer, 2 * S, "never accepted")
    assert writer.spool is not None
    unfinished = writer.spool.path
    writer.close()  # process exit leaves both directories behind
    checked = check_dataset(Path(writer.cfg.output))
    assert checked.ok and any(
        "1 ready" in note and "1 unfinished" in note for note in checked.notes
    )

    saving, finish, processed = (threading.Event() for _ in range(3))
    save_closed = EpisodeRecorder._save_closed

    def delayed(recorder, *args, **kwargs):
        saving.set()
        assert finish.wait(15)
        return save_closed(recorder, *args, **kwargs)

    monkeypatch.setattr(EpisodeRecorder, "_save_closed", delayed)
    real_flush = runtime._send

    def send(node, output, msg):
        real_flush(node, output, msg)
        if msg.payload.get("command") == "quit":
            processed.set()

    monkeypatch.setattr(runtime, "_send", send)

    def run(command, receive):
        try:
            note = receive("report", level="warn")["note"]
            assert "1 episodes left from an interrupted run" in note
            assert saving.wait(10) and not unfinished.exists()
            command("start", task="during save", id=1)
            assert receive("report", command="start", id=1)["ok"]
            command("discard", id=2)  # operator-gone route
            assert receive("report", command="discard", id=2)["ok"]
            command("quit")
            assert not processed.wait(0.1)
        finally:
            finish.set()
        saved = receive("report", command="saved")
        assert saved["save_id"] is None and saved["index"] == 0
        assert saved["pending"] == 0
        receive("report", command="quit")

    _node(monkeypatch, writer.cfg, run)
    assert not ready.exists() and not journal.recover(Path(writer.cfg.output))
    assert episodes.read(Path(writer.cfg.output))[0]["task"] == "interrupted"


def test_commit_receipt_prevents_reimport_if_cleanup_is_interrupted(
    tmp_path, monkeypatch
):
    writer = _writer(tmp_path)
    _stopped(writer, S)
    path = writer.enqueue()
    with monkeypatch.context() as patch:
        patch.setattr(spool, "remove", lambda path: None)
        (saved,) = _save(writer, path)
    assert saved["index"] == 0 and (path / spool.COMMITTED).exists()
    assert spool.ready(Path(writer.cfg.output)) == []
    spool.prune(Path(writer.cfg.output))
    assert not path.exists() and check_dataset(Path(writer.cfg.output)).episodes == 1


def test_start_limit_and_queued_state(tmp_path):
    cfg = _cfg(tmp_path)
    state = {
        "recorder": {
            "t_ns": S,
            "fields": {"state": "idle", "pending_saves": 1, "max_pending_saves": 2},
        },
    }
    assert runtime.recorder_state_after({"command": "save", "queued": True}) == "idle"
    assert runtime.recorder_state_after({"command": "saved"}) is None
    assert runtime.start_warning(cfg, state, S) is None
    state["recorder"]["fields"]["pending_saves"] = 2
    assert runtime.start_warning(cfg, state, S) == (
        "2 episodes are waiting to be saved (max_pending_saves 2); wait, then retry start"
    )


class _Client:
    def __init__(self):
        self.reports = []
        self.auto_complete = False
        self.after_quit = None

    def status(self):
        return {
            "nodes": {
                "recorder": {
                    "t_ns": 1,
                    "fields": {"episodes": 3, "pending_saves": 0, "state": "stopped"},
                }
            }
        }

    def send(self, line):
        if line == "quit":
            if self.after_quit is not None:
                self.after_quit()
            return
        ident = json.loads(line)["id"]
        self.reports.append(
            {
                "command": "save",
                "id": ident,
                "queued": True,
                "pending": ident,
                "total_episodes": 3,
                "recorder_t_ns": 1 + ident,
                "metrics": {"rows": 5},
            }
        )
        if self.auto_complete:
            self.complete(ident, "new", 3)

    def new_reports(self):
        result, self.reports = self.reports, []
        return result

    def complete(self, ident, task, index=None, *, pending=0):
        report = {
            "command": "saved",
            "save_id": ident,
            "task": task,
            "pending": pending,
            "recorder_t_ns": 20 + ident,
        }
        if index is None:
            report.update(error="injected failure", dropped=True, total_episodes=3)
        else:
            report.update(
                index=index,
                saved_frames=5,
                episodes=index + 1,
                total_episodes=index + 1,
            )
        self.reports.append(report)


@pytest.fixture
def fake_session(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.recorder["background_save"] = True
    process = Mock(spec=subprocess.Popen)
    process.poll.return_value = None
    work = tempfile.TemporaryDirectory(dir=tmp_path)
    client = _Client()
    session = Session(cfg, process, client, tmp_path, work, tmp_path / "fifo")
    yield session, client
    work.cleanup()


def test_session_queue_wait_and_next_index(fake_session):
    session, client = fake_session
    assert session.next_info().index == 3
    for i, task in enumerate(("one", "two"), 1):
        session._episode = task
        result = session.save(wait=False)
        assert result.task == task and result.pending and not result.saved
        assert result.index is None and result.frames == 5
        assert session.pending_saves == i and session.next_info().index == 3 + i
    with pytest.raises(SessionError, match="timed out"):
        session.wait_saves(timeout=0)
    client.complete(1, "one", 3, pending=1)
    client.complete(2, "two", 4)
    assert [(r.task, r.index, r.saved) for r in session.wait_saves()] == [
        ("one", 3, True),
        ("two", 4, True),
    ]
    assert session.wait_saves() == [] and session.pending_saves == 0
    assert session.next_info().previous == ["one", "two"]


def test_wait_true_handles_completion_in_same_poll(fake_session):
    session, client = fake_session
    client.auto_complete = True
    session._episode = "new"
    result = session.save(wait=True)
    assert result.saved and result.index == 3 and not result.pending
    assert session.wait_saves() == []


def test_wait_saves_aggregates_failures_after_the_other_saves(fake_session):
    session, client = fake_session
    notes = []
    session.listen(notes.append)
    for task in ("bad", "good"):
        session._episode = task
        assert session.save().pending
    client.complete(1, "bad", pending=1)
    with pytest.raises(SessionError, match="timed out"):
        session.wait_saves(timeout=0)
    client.complete(2, "good", 3)
    with pytest.raises(SessionError, match="'bad': injected failure") as error:
        session.wait_saves()
    assert error.value.report["results"][0].task == "good"
    assert error.value.report["failures"][0]["dropped"]
    assert any("episode 'bad' was not saved" in item.get("note", "") for item in notes)
    assert session.wait_saves() == []


def test_session_close_waits_for_the_recorder_to_finish(fake_session):
    session, client = fake_session
    session._episode = "last"
    session.save()
    # Failure of a controller must not truncate saves already in the recorder.
    session.log_path.write_text("node exited with error: ExitCode(1) node_id=policy\n")
    notes = []
    session.listen(notes.append)

    def wait(timeout):
        assert session.episodes == 4 and session.pending_saves == 0, (
            "process wait began before saves finished"
        )

    session.process.wait.side_effect = wait
    timer = threading.Timer(0.15, lambda: client.complete(1, "last", 3))
    client.after_quit = timer.start
    try:
        session.close(release=False)
    finally:
        timer.cancel()
        timer.join()
    assert any("saving 1 queued episodes" in item.get("note", "") for item in notes)


def test_coordinator_uses_save_reports_before_next_recorder_status(
    tmp_path, monkeypatch
):
    import os

    cfg = _cfg(tmp_path)
    fifo = tmp_path / "session.fifo"
    log = tmp_path / "reports.jsonl"
    os.mkfifo(fifo)
    monkeypatch.setenv("ROBOLOOM_SESSION_FIFO", str(fifo))
    monkeypatch.setenv("ROBOLOOM_REPORT_PATH", str(log))
    monkeypatch.delenv("ROBOLOOM_STATUS_PATH", raising=False)
    commands = iter([b"", b"", b"start blocked\n", b"start allowed\n", b"quit\n"])
    publisher = Publisher("recorder")
    events = iter(
        [
            (
                "recorder_status",
                publisher.make(
                    "status", {"fields": {"state": "stopped", "episodes": 0}}
                ),
            ),
            (
                "report",
                publisher.make(
                    "report",
                    {
                        "command": "save",
                        "queued": True,
                        "pending": 2,
                        "total_episodes": 0,
                    },
                ),
            ),
            (
                "report",
                publisher.make(
                    "report",
                    {
                        "command": "saved",
                        "pending": 1,
                        "total_episodes": 1,
                    },
                ),
            ),
            (None, None),
            ("report", publisher.make("report", {"command": "quit"})),
        ]
    )
    monkeypatch.setattr(runtime.os, "read", lambda *_: next(commands))
    monkeypatch.setattr(runtime, "_event", lambda _: next(events))
    sent = []
    monkeypatch.setattr(
        runtime, "_send", lambda _, output, msg: sent.append(msg.payload)
    )
    runtime._session(object(), cfg)
    assert [(m["command"], m["task"]) for m in sent] == [
        ("start", "allowed"),
        ("quit", ""),
    ]
    reports = [json.loads(line) for line in log.read_text().splitlines()]
    assert (
        reports[1]["task"] == "blocked"
        and "max_pending_saves 2" in reports[1]["warning"]
    )


def test_synchronous_save_ignores_wait_false(fake_session, monkeypatch):
    session, client = fake_session
    session.cfg.recorder["background_save"] = False

    def send(line):
        ident = json.loads(line)["id"]
        client.reports.append(
            {"command": "save", "id": ident, "episodes": 4, "saved_frames": 5}
        )

    monkeypatch.setattr(client, "send", send)
    session._episode = "synchronous"
    result = session.save(wait=False)
    assert result.saved and not result.pending and result.index == 3
    assert session.wait_saves() == []


def test_the_next_episode_index_counts_the_queued_saves():
    # lifecycle events (hooks) get the index the started episode will have if saved
    from roboloom.runtime.node import next_episode_index

    assert next_episode_index({"episodes": 3}) == 3
    assert next_episode_index({"episodes": 3, "pending_saves": 2}) == 5
    assert next_episode_index({"pending_saves": 1}) is None
