"""What happens when something breaks while a robot runs: the operator's process dies,
a policy raises, a node refuses `start`, a node has failed when ESTOP is needed."""

from __future__ import annotations

import itertools
import json
import os
import shutil
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from conftest import mock_project
from test_policy_observation import Recorder, _controller, _run

from roboloom.config import load_config
from roboloom.core.protocol import Envelope
from roboloom.runtime import node as runtime
from roboloom.runtime.session import (
    EpisodeFailed,
    Session,
    SessionError,
    _fifo_in_use,
)
from roboloom.ui.client import SessionClient

TESTS = str(Path(__file__).resolve().parent)
S = 1_000_000_000
needs_dora = pytest.mark.skipif(shutil.which("dora") is None, reason="needs dora")


def _gone(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)
    return False


# -- the operator's process ---------------------------------------------------------


@needs_dora
def test_the_robot_stops_when_the_operator_process_is_killed(tmp_path):
    project = mock_project(tmp_path / ".roboloom")
    code = textwrap.dedent(
        """
        import sys, time
        from roboloom.runtime.session import Session

        s = Session.launch(sys.argv[1], log_dir=sys.argv[2])
        s.wait_ready(60)
        s.start("left alone")  # the follower follows the leader, an episode records
        time.sleep(1.0)
        print("RUNNING", s.process.pid, s._workdir.name, flush=True)
        time.sleep(600)
        """
    )
    logs = tmp_path / "logs"
    operator = subprocess.Popen(
        [sys.executable, "-c", code, str(project / "config.yaml"), str(logs)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert operator.stdout is not None
        line = operator.stdout.readline().split()
        assert line and line[0] == "RUNNING", line
        dora, workdir = int(line[1]), Path(line[2])
        fifo = project / "config.fifo"
        assert fifo.exists() and workdir.exists()
        operator.kill()  # SIGKILL: no handler, no cleanup
        operator.wait()
        assert _gone(dora, 30), "the dataflow outlived its operator"
    finally:
        operator.kill()
    assert not fifo.exists() and not workdir.exists()
    # what happened is kept with the logs (nobody was left to read the reports)
    assert "the operator's process is gone" in (logs / "reports.jsonl").read_text()
    trace = np.load(logs / "follower_trace.npz")
    modes = [str(trace["modes"][i]) for i in trace["mode"]]
    assert "ACTIVE" in modes  # it was following when the operator died ...
    assert modes[-1] in ("HOLD", "ESTOP")  # ... and ended holding, torque on
    # nothing is left in the way of the next run, and the cut episode was not saved
    with Session.launch(project / "config.yaml", log_dir=tmp_path / "logs2") as s:
        s.wait_ready(60)
        assert s.episodes == 0


def test_a_fifo_nobody_reads_was_left_by_a_dead_run(tmp_path):
    fifo = tmp_path / "config.fifo"
    os.mkfifo(fifo)
    assert _fifo_in_use(fifo)  # just made: a run may still be starting
    old = time.time() - 120
    os.utime(fifo, (old, old))
    assert not _fifo_in_use(fifo)
    reader = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
    try:
        assert _fifo_in_use(fifo)  # a session node reads it
    finally:
        os.close(reader)


def _session_node(tmp_path, monkeypatch, reads):
    """Run the session node on scripted FIFO reads (an exception is raised, bytes are
    returned), 0.25 s apart; returns the commands it sent and its reports."""
    cfg = load_config("examples/mock/config.yaml")
    work = tmp_path / "work"
    work.mkdir()
    fifo = tmp_path / "session.fifo"
    os.mkfifo(fifo)
    monkeypatch.setenv("ROBOLOOM_SESSION_FIFO", str(fifo))
    monkeypatch.setenv("ROBOLOOM_REPORT_PATH", str(work / "report.jsonl"))
    monkeypatch.setenv("ROBOLOOM_STATUS_PATH", str(work / "status.json"))
    now = S
    script = iter(reads)
    seen: list[dict] = []

    def read(fd: int, count: int) -> bytes:
        nonlocal now
        now += S // 4
        item = next(script)
        if isinstance(item, BaseException):
            raise item
        return item

    real_open = open

    def keep(
        path, mode="r", *args, **kwargs
    ):  # the reports, before the node removes them
        if str(path).endswith("report.jsonl") and "a" in mode:
            return real_open(tmp_path / "reports.jsonl", mode, *args, **kwargs)
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(runtime.os, "read", read)
    monkeypatch.setattr(runtime.time, "monotonic_ns", lambda: now)
    monkeypatch.setattr(runtime, "_event", lambda node: (None, None))
    monkeypatch.setattr("builtins.open", keep)

    class Node:
        def send_output(self, output: str, value: bytes) -> None:
            seen.append(Envelope.decode(value).payload)

    runtime._session(Node(), cfg)
    reports = tmp_path / "reports.jsonl"
    lines = reports.read_text().splitlines() if reports.exists() else []
    return seen, [json.loads(line) for line in lines], fifo, work


def test_the_session_node_ends_the_dataflow_when_the_fifo_loses_its_writer(
    tmp_path, monkeypatch
):
    held = BlockingIOError()  # the operator holds the FIFO open, nothing to read
    sent, reports, fifo, work = _session_node(
        tmp_path,
        monkeypatch,
        [b'{"command": "attach"}\n', held, held, *[b""] * 6],
    )
    assert [m["command"] for m in sent] == ["discard", "quit"]
    assert "operator's process is gone" in reports[0]["note"]
    assert not fifo.exists() and not work.exists()


def test_a_fifo_without_a_writer_ends_nothing_before_an_operator_attached(
    tmp_path, monkeypatch
):
    # `roboloom session` writers come and go; without `attach` nobody is expected to stay
    sent, _, fifo, work = _session_node(
        tmp_path, monkeypatch, [b"", b"", b"", b"", b"", b"", b"quit\n"]
    )
    assert [m["command"] for m in sent] == ["quit"]
    assert fifo.exists() and work.exists()


# -- a policy that raises -----------------------------------------------------------


def test_a_failed_policy_is_ready_again_after_the_episode_ended(tmp_path):
    _, controller = _controller(tmp_path, observe=["camera"])
    controller.policy = Recorder()
    controller.state = "ready"
    controller.start("task")
    controller.fail("ValueError: boom")
    assert not controller.running and controller.status()["state"] == "failed"
    controller.stop()  # what `stop` and `discard` do
    assert controller.status()["state"] == "ready"
    assert controller.status()["error"] == "ValueError: boom"  # until the next start
    controller.start("task")
    assert controller.status()["state"] == "running"


def test_an_episode_that_ends_while_the_policy_waits_leaves_it_ready(tmp_path):
    # e.g. a camera froze near the end: the next episode must still be able to start
    _, controller = _controller(tmp_path)
    controller.policy = Recorder()
    controller.start("task")
    _run(controller, 1)
    controller.state = "stale_observation"
    controller.stop()
    assert controller.status()["state"] == "ready"
    controller.policy = None  # a policy that never loaded stays failed
    controller.state = "failed"
    controller.stop()
    assert controller.status()["state"] == "failed"


@needs_dora
def test_a_failed_policy_episode_is_discarded_and_the_next_one_runs(
    tmp_path, monkeypatch
):
    project = mock_project(tmp_path / ".roboloom")
    monkeypatch.setenv(
        "PYTHONPATH", os.pathsep.join([TESTS, os.environ.get("PYTHONPATH", "")])
    )
    with Session.launch(
        project / "config.yaml",
        options=["policy"],
        policy="policies:flaky",
        log_dir=tmp_path / "logs",
    ) as s:
        s.wait_ready(30)
        with pytest.raises(EpisodeFailed, match="out of memory"):
            s.record("creep", 8.0)
        assert s.episodes == 0  # the broken episode was not saved
        s.wait_ready(10)  # no restart: the policy is ready again
        fields = s.status()["policy"]["fields"]
        assert "out of memory" in fields["error"]  # shown until the next start
        result = s.record("creep", 1.5)
        assert result.saved and s.episodes == 1
        assert "error" not in s.status()["policy"]["fields"]


# -- start ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "why"),
    [
        ("saving", "still being saved"),
        ("stopped", "save or discard"),
        ("recording", "already being recorded"),
    ],
)
def test_start_waits_for_the_recorder(state, why):
    cfg = load_config("examples/mock/config.yaml")
    latest = {
        "controller": {"t_ns": S, "fields": {"state": "following"}},
        "recorder": {"t_ns": S, "fields": {"state": state}},
    }
    assert why in runtime.start_warning(cfg, latest, S)
    latest["recorder"]["fields"]["state"] = "idle"
    assert runtime.start_warning(cfg, latest, S) is None
    latest["recorder"]["t_ns"] = S - 2 * S  # a recorder that went silent
    assert "recorder" in runtime.start_warning(cfg, latest, S)


@needs_dora
def test_start_is_refused_while_the_last_episode_is_neither_saved_nor_discarded(
    tmp_path,
):
    project = mock_project(tmp_path / ".roboloom")
    with Session.launch(project / "config.yaml", log_dir=tmp_path / "logs") as s:
        s.wait_ready(60)
        s.start("first")
        time.sleep(0.5)
        s.stop()
        time.sleep(0.8)  # the recorder's next status
        with pytest.raises(SessionError, match="save or discard"):
            s.start("second")
        time.sleep(0.5)
        follower = s.status()["follower"]["fields"]
        assert not follower["armed"] and follower["mode"] == "HOLD"  # nothing moved
        assert s.save().saved  # the stopped episode is still there
        result = s.record("second", 1.0)
        assert result.saved and s.episodes == 2


# -- ESTOP ----------------------------------------------------------------------------


def test_estop_goes_out_when_a_node_has_failed(tmp_path):
    fifo = tmp_path / "config.fifo"
    os.mkfifo(fifo)
    reader = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)

    class Alive:
        returncode = None

        def poll(self):
            return None

    session = Session.__new__(Session)
    session.process = Alive()
    session.client = SessionClient(fifo, tmp_path / "report", tmp_path / "status")
    session.log_path = tmp_path / "dora.log"
    session.log_path.write_text("node exited with error: ExitCode(1) node_id=policy\n")
    session._ids = itertools.count(1)
    session._cancel_local = threading.local()
    try:
        with pytest.raises(SessionError, match="a node failed"):
            session.send("stop")  # every other command refuses
        session.estop()
        assert json.loads(os.read(reader, 4096))["command"] == "estop"
    finally:
        os.close(reader)


def test_a_start_the_recorder_refuses_stops_what_already_started(tmp_path):
    """`start` reaches every node at once; if the recorder then refuses, the followers
    and the policy that took it are stopped again."""
    sent: list[str] = []
    session = Session.__new__(Session)
    session._episode = None

    def send(command: str, task: str = "") -> int:
        sent.append(command)
        return len(sent)

    def refused(ident: int, timeout: float = 10.0) -> dict:
        raise SessionError(
            "start: disk full", {"command": "start", "error": "disk full"}
        )

    session.send = send  # type: ignore[method-assign]
    session.wait_report = refused  # type: ignore[method-assign]
    with pytest.raises(SessionError, match="disk full"):
        session.start("task")
    assert sent == ["start", "stop"] and session._episode is None

    def warned(ident: int, timeout: float = 10.0) -> dict:
        raise SessionError("start: align", {"command": "start", "warning": "align"})

    sent.clear()
    session.wait_report = warned  # type: ignore[method-assign]
    with pytest.raises(SessionError, match="align"):
        session.start("task")
    assert sent == ["start"]  # the session node sent it to nobody: nothing to stop
