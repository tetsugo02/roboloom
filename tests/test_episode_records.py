"""What each saved episode was (`meta/roboloom_episodes.jsonl`): the verdict of an
evaluation episode, given when it is saved or afterwards with `roboloom label`."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from conftest import mock_project
from test_session_failures import _session_node
from test_video_codec import COLOURS, FPS, _cfg, _frame

from roboloom.api import InProcessSession
from roboloom.cli import _with_config, main
from roboloom.core.protocol import Envelope
from roboloom.drivers.mock import MockBus
from roboloom.recording import EpisodeRecorder, SaveFailed, episodes
from roboloom.recording.check import check_dataset
from roboloom.runtime.node import parse_command
from roboloom.runtime.session import Session

TESTS = str(Path(__file__).resolve().parent)
needs_dora = pytest.mark.skipif(shutil.which("dora") is None, reason="needs dora")


def _stopped(recorder: EpisodeRecorder, start_ns: int, task: str = "colours") -> None:
    """One stopped episode of len(COLOURS) rows, not saved yet."""
    period = int(1e9 / FPS)
    recorder.start(task, start_ns)
    for k, colour in enumerate(COLOURS):
        t = start_ns + k * period
        for name, sensor in recorder.cfg.sensors.items():
            image = _frame(colour, sensor.shape)
            recorder.ingest(
                name,
                Envelope(
                    "image", name, "boot", k, t, t, {"image": image}, t_receive_ns=t
                ),
            )
    recorder.stop(start_ns + len(COLOURS) * period)


# -- the record ----------------------------------------------------------------------


def test_a_saved_episode_is_recorded_with_its_verdict(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    recorder = EpisodeRecorder(cfg, **cfg.recorder)
    root = tmp_path / "data"
    _stopped(recorder, 1_000_000_000, "open the drawer")
    status = {"policy": {"state": "ready", "infer_max_ms": 41.5, "dropped": 2}}
    assert recorder.save("success", "first try", status) == len(COLOURS)
    _stopped(recorder, 11_000_000_000, "close the drawer")
    recorder.save()  # collection: no verdict
    recorder.close()

    first, second = (episodes.read(root)[k] for k in (0, 1))
    assert first["task"] == "open the drawer" and first["frames"] == len(COLOURS)
    assert first["label"] == "success" and first["note"] == "first try"
    assert first["metrics"]["rows"] == len(COLOURS) and first["saved"]
    assert first["controllers"] == status  # what the policy reported when it ended
    assert second["task"] == "close the drawer" and second["label"] is None
    assert "note" not in second and "controllers" not in second
    counted = "labels: 1 success, 0 failure, 1 not labelled (100% of the labelled)"
    assert episodes.summary(root, 2) == counted

    # afterwards: the verdict of the second episode, then a changed mind about it
    assert episodes.label(root, 1, "success")["label"] == "success"
    record = episodes.label(root, 1, "failure", "let go of the handle")
    assert record["label"] == "failure" and record["note"] == "let go of the handle"
    assert record["task"] == "close the drawer" and record["frames"] == len(COLOURS)
    with pytest.raises(ValueError, match="episode 2 is not in .* \\(episodes 0..1\\)"):
        episodes.label(root, 2, "success")
    with pytest.raises(ValueError, match="label must be success or failure"):
        episodes.label(root, 0, "ok")
    # the dataset is as LeRobot wrote it; the check counts the verdicts
    checked = check_dataset(root)
    assert checked.ok, checked.describe()
    counted = "labels: 1 success, 1 failure, 0 not labelled (50% of the labelled)"
    assert counted in checked.describe()

    main(["label", str(root), "0", "failure", "--note", "watched the video again"])
    out = capsys.readouterr().out
    assert "episode 0" in out and "failure (watched the video again)" in out
    assert "labels: 0 success, 2 failure, 0 not labelled" in out
    with pytest.raises(SystemExit, match="episode 7 is not in"):
        main(["label", str(root), "7", "success"])


def test_a_mistyped_verdict_saves_nothing(tmp_path):
    cfg = _cfg(tmp_path)
    recorder = EpisodeRecorder(cfg, **cfg.recorder)
    _stopped(recorder, 1_000_000_000)
    with pytest.raises(ValueError, match="label must be success or failure, not 'ok'"):
        recorder.save("ok")
    assert recorder.stopped and recorder.episodes == 0  # still there to save
    assert recorder.save("failure") == len(COLOURS)
    recorder.close()
    assert episodes.read(tmp_path / "data")[0]["label"] == "failure"


def test_an_episode_that_was_not_saved_has_no_record(tmp_path, monkeypatch):
    import lerobot.datasets.dataset_writer as writer

    cfg = _cfg(tmp_path)
    recorder = EpisodeRecorder(cfg, **cfg.recorder)

    def full(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(writer.DatasetWriter, "_save_episode_video", full)
    _stopped(recorder, 1_000_000_000)
    with pytest.raises(SaveFailed):
        recorder.save("success")
    assert episodes.read(tmp_path / "data") == {}
    assert episodes.summary(tmp_path / "data", 0) is None


def test_reading_skips_a_cut_line_and_a_new_episode_replaces_an_index(tmp_path):
    root = tmp_path
    (root / "meta").mkdir()
    (root / "meta" / "info.json").write_text(json.dumps({"total_episodes": 1}))
    episodes.saved(root, 0, "old", 10, {"rows": 10}, "failure", "from a run undone")
    # the index is used again (the dataset was put back): nothing of the old one stays
    episodes.saved(root, 0, "new", 12, {"rows": 12})
    with open(root / episodes.EPISODES, "a") as out:
        out.write('{"episode": 0, "label": "succ')  # the process died while writing
    record = episodes.read(root)[0]
    assert record["task"] == "new" and record["label"] is None and "note" not in record
    assert episodes.label(root, 0, "success")["label"] == "success"  # still appends


def test_the_in_process_session_saves_the_verdict(tmp_path):
    limits = [
        {"name": n, "min": 0, "max": 4095, "max_speed": 3000, "max_jump": 400}
        for n in ("j1", "j2")
    ]
    with InProcessSession.from_components(
        robot="my-mock",
        bus=MockBus(dimension=2),
        joint_names=["j1", "j2"],
        unit="count",
        limits=limits,
        controller=lambda obs: [2048, 2048],
        output=str(tmp_path / "data"),
        repo_id="local/my-mock",
    ) as session:
        session.start_episode("handover")
        session.run(0.5)
        session.stop_episode()
        session.save_episode(label="failure", note="too slow")
    record = episodes.read(tmp_path / "data")[0]
    assert record["task"] == "handover" and record["label"] == "failure"
    assert record["note"] == "too slow"


# -- the command ---------------------------------------------------------------------


def test_save_carries_the_verdict_typed_or_sent():
    typed = parse_command("save success")
    assert typed == {"command": "save", "task": "", "label": "success"}
    assert parse_command("save") == {"command": "save", "task": ""}
    assert parse_command("start pick up the cup")["task"] == "pick up the cup"
    sent = parse_command(
        json.dumps({"id": 4, "command": "save", "label": "failure", "note": "slipped"})
    )
    assert sent == {
        "id": 4,
        "command": "save",
        "task": "",
        "label": "failure",
        "note": "slipped",
    }


def test_the_session_node_refuses_a_mistyped_verdict(tmp_path, monkeypatch):
    sent, reports, _, _ = _session_node(
        tmp_path, monkeypatch, [b"save succes\n", b"save success\n", b"quit\n"]
    )
    assert [m["command"] for m in sent] == ["save", "quit"]  # the first went nowhere
    assert sent[0]["label"] == "success" and sent[0]["controllers"] == {}
    assert "label must be success or failure, not 'succes'" in reports[0]["error"]


def test_the_command_line_takes_the_robot_before_the_episode():
    assert _with_config(["label", "3", "success"]) == ["label", "3", "success"]
    named = ["label", "--config", "rakuda2", "3", "success"]
    assert _with_config(["label", "rakuda2", "3", "success"]) == named
    # the operations of a policy with `teleop:` are session operations too
    assert _with_config(["session", "teleop"]) == ["session", "teleop"]
    assert _with_config(["session", "save", "failure"]) == [
        "session",
        "save",
        "failure",
    ]


# -- through the dataflow ------------------------------------------------------------


@needs_dora
def test_an_evaluation_run_records_each_verdict(tmp_path, monkeypatch, capsys):
    project = mock_project(tmp_path / ".roboloom")
    monkeypatch.setenv(
        "PYTHONPATH", os.pathsep.join([TESTS, os.environ.get("PYTHONPATH", "")])
    )
    with Session.launch(
        project / "config.yaml",
        options=["policy"],
        policy="policies:creep",
        log_dir=tmp_path / "logs",
    ) as s:
        s.wait_ready(30)
        first = s.record("creep", 1.5, label="success", note="reached the mark")
        assert first.saved and first.label == "success"
        # decided from the stopped episode, e.g. by a check of the scene
        second = s.record(
            "creep", 1.5, label=lambda ep: "failure" if ep.frames else None
        )
        assert second.label == "failure"
        with pytest.raises(ValueError, match="label must be success or failure"):
            s.record("creep", 1.5, label="ok")  # refused before the robot moves
        s.start("creep")
        s.stop()
        with pytest.raises(ValueError, match="label must be success or failure"):
            s.save(label="good")  # refused before anything is sent
        third = s.save()
        assert third.saved and third.label is None
        root = Path(s.cfg.output)
    records = episodes.read(root)
    assert [records[k]["label"] for k in range(3)] == ["success", "failure", None]
    assert records[0]["note"] == "reached the mark" and records[0]["task"] == "creep"
    assert records[0]["frames"] == first.frames
    # what the policy node reported when the episode ended
    policy = records[0]["controllers"]["policy"]
    assert policy["state"] in ("ready", "running") and "infer_max_ms" in policy
    # afterwards, by the robot's name and the options the dataset was recorded with
    monkeypatch.chdir(tmp_path)
    main(["label", "rakuda2", "--mock", "--with", "policy", "2", "success"])
    assert "labels: 2 success, 1 failure, 0 not labelled" in capsys.readouterr().out
    assert check_dataset(root).ok
