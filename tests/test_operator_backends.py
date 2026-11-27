"""Thread ownership, cancellation, and saves tested with fake Session / MockBus."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml
from test_control_laws import GRAVITY, FlatGravity, device
from test_homing import home_tree

from roboloom.config import load_config, parse_config
from roboloom.control.laws import GravityComp
from roboloom.control.tuning import TuningSave, TuningSession
from roboloom.errors import Cancelled
from roboloom.recording.episodes import check_label
from roboloom.runtime.session import EpisodeResult, Session, SessionError
from roboloom.ui.backend import RecordingPlan, SessionBackend
from roboloom.ui.client import SessionClient
from roboloom.ui.models import Closed, LogEvent, Notice, Snapshot
from roboloom.ui.record import record
from roboloom.ui.tuning_backend import TuningBackend


class Notices:
    def __init__(self) -> None:
        self.items: list[Notice] = []
        self.condition = threading.Condition()

    def __call__(self, notice: Notice) -> None:
        with self.condition:
            self.items.append(notice)
            self.condition.notify_all()

    def wait(
        self, predicate: Callable[[Notice], bool], timeout: float = 5, *, since: int = 0
    ) -> Notice:
        end = time.monotonic() + timeout
        with self.condition:
            while True:
                found = next(
                    (item for item in reversed(self.items[since:]) if predicate(item)),
                    None,
                )
                if found is not None:
                    return found
                remaining = end - time.monotonic()
                assert remaining > 0, self.items[-4:]
                self.condition.wait(remaining)

    def wait_phase(self, phase: str, *enabled: str, since: int = 0) -> Snapshot:
        snapshot = self.wait(
            lambda n: (
                isinstance(n, Snapshot)
                and n.phase == phase
                and set(enabled) <= {o.command for o in n.operations if o.enabled}
            ),
            since=since,
        )
        assert isinstance(snapshot, Snapshot)
        return snapshot


class FakeClient(SessionClient):
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.fail = False
        self.confirm = True
        self.stop_ns = 0

    def send(self, line: str, attempts: int = 30) -> None:
        if self.fail:
            raise OSError("disconnected")
        self.sent.append(line)
        self.stop_ns = time.monotonic_ns()

    def new_reports(self) -> list[dict]:
        raise AssertionError("UI must use Session.poll")


class FakeSession(Session):
    def __init__(self, tmp_path: Path, *, home: bool = False):
        self.cfg = (
            parse_config(home_tree(tmp_path))
            if home
            else load_config("examples/mock/config.yaml")
        )
        self.cfg.mode = "mock"
        self.client = FakeClient()
        self._cancel_local = threading.local()
        self.log_path = tmp_path / "dora.log"
        self.log_path.write_text("dora is alive\n")
        self._alive = True
        self.refuse = False
        self.closed: list[bool | None] = []
        self.started: list[str] = []
        self.stopped = 0
        self.homed = 0
        self.discarded = 0
        self.saved = 0
        self.save_gate = threading.Event()
        self.save_gate.set()
        self.home_gate = threading.Event()
        self.home_gate.set()
        self.polls = 0

    @property
    def alive(self) -> bool:
        return self._alive

    def _check_alive(self) -> None:
        self._check_cancelled()

    def status(self) -> dict:
        now = time.monotonic_ns()
        status: dict = {}
        for role, owners in [
            ("follower", self.cfg.followers),
            ("input", self.cfg.inputs),
            ("controller", self.cfg.controllers),
        ]:
            for name in owners:
                fields: dict = {
                    "state": "following",
                    "home_state": "moving"
                    if not self.home_gate.is_set()
                    else "reached",
                }
                if role == "follower":
                    fields["mode"] = (
                        "ESTOP" if self.client.sent and self.client.confirm else "HOLD"
                    )
                status[name] = {"role": role, "fields": fields, "t_ns": now}
        return status

    def listen(self, listener: Callable[[dict], None]) -> None:
        self.listener = listener

    def poll(self) -> None:
        self.polls += 1
        self.listener({"note": "polled"})

    def wait_ready(self, timeout: float = 30) -> None:
        self._check_cancelled()

    def start(self, task: str) -> None:
        if self.refuse:
            self.refuse = False
            raise SessionError("leader is still moving home; retry")
        self.started.append(task)

    def home(self, timeout: float | None = None) -> None:
        while not self.home_gate.wait(0.01):
            self._check_cancelled()
        self.homed += 1

    def stop(self) -> EpisodeResult:
        self._check_cancelled()
        self.stopped += 1
        return EpisodeResult(self.started[-1], False, 10)

    def save(
        self,
        timeout: float = 300,
        *,
        label: str | None = None,
        note: str | None = None,
    ) -> EpisodeResult:
        label = check_label(label)  # as Session.save: before anything is sent
        while not self.save_gate.wait(0.01):
            self._check_cancelled()
        self.saved += 1
        return EpisodeResult(self.started[-1], True, 10, self.saved - 1, label=label)

    def discard(self) -> None:
        self._check_cancelled()
        self.discarded += 1

    def release(self, *, confirm: bool = False) -> None:
        assert confirm

    def close(self, timeout: float = 15, *, release: bool | None = None) -> None:
        self.closed.append(release)
        self._alive = False


def ready(notice: Notice) -> bool:
    return isinstance(notice, Snapshot) and any(
        o.command == "start" and o.enabled for o in notice.operations
    )


def test_start_refusal_does_not_disable_retry_and_close_once(tmp_path):
    session = FakeSession(tmp_path)
    backend = SessionBackend(lambda: session)
    notices = Notices()
    backend.start(notices)
    try:
        notices.wait(ready)
        session.refuse = True
        backend.submit("start first")
        notices.wait(lambda n: isinstance(n, LogEvent) and "retry" in n.text)
        notices.wait(
            lambda n: (
                isinstance(n, Snapshot)
                and n.phase == "operation refused; retry when ready"
                and ready(n)
            )
        )
        backend.submit("start second")
        notices.wait(lambda n: isinstance(n, Snapshot) and n.phase == "recording")
        assert session.started == ["second"]
        backend.request_close("release")
    finally:
        backend.shutdown()
        backend.shutdown()
    assert session.closed == [True]


def test_a_typed_verdict_is_saved_with_the_episode(tmp_path):
    session = FakeSession(tmp_path)
    backend = SessionBackend(lambda: session)
    notices = Notices()
    backend.start(notices)

    def stopped(n: Notice) -> bool:
        return isinstance(n, Snapshot) and n.phase.startswith("stopped")

    try:
        notices.wait(ready)
        backend.submit("start task")
        notices.wait(lambda n: isinstance(n, Snapshot) and n.phase == "recording")
        backend.submit("stop")
        notices.wait(stopped)
        backend.submit("save succes")  # mistyped: refused, the episode stays stopped
        notices.wait(lambda n: isinstance(n, LogEvent) and "label must be" in n.text)
        assert session.saved == 0
        notices.wait(
            lambda n: (
                isinstance(n, Snapshot)
                and any(o.command == "save" and o.enabled for o in n.operations)
            )
        )
        backend.submit("save failure")
        notices.wait(
            lambda n: (
                isinstance(n, LogEvent)
                and "saved episode 0" in n.text
                and "labelled failure" in n.text
            )
        )
        assert session.saved == 1
    finally:
        backend.shutdown()


def test_stop_dropped_clears_the_episode_and_recording_state(tmp_path):
    session = FakeSession(tmp_path)

    def stop() -> EpisodeResult:
        raise SessionError(
            "stop: could not write spool images",
            {
                "command": "stop",
                "error": "could not write spool images",
                "dropped": True,
            },
        )

    session.stop = stop  # type: ignore[method-assign]
    backend = SessionBackend(lambda: session)
    notices = Notices()
    backend.start(notices)
    try:
        notices.wait(ready)
        backend.submit("start task")
        notices.wait(lambda n: isinstance(n, Snapshot) and n.phase == "recording")
        backend.submit("stop")
        notices.wait(
            lambda n: (
                isinstance(n, LogEvent) and "could not write spool images" in n.text
            )
        )
        # the episode is gone: Start is available again, Save/Discard/Stop are not
        snapshot = notices.wait(
            lambda n: (
                isinstance(n, Snapshot)
                and n.phase == "operation refused; retry when ready"
                and any(o.command == "start" and o.enabled for o in n.operations)
            )
        )
        assert isinstance(snapshot, Snapshot)
        assert not any(
            o.enabled
            for o in snapshot.operations
            if o.command in ("stop", "save", "discard")
        )
    finally:
        backend.shutdown()


@pytest.mark.parametrize("operation", ["save", "home"])
def test_monitor_and_emergency_bypass_blocked_operations(tmp_path, operation: str):
    session = FakeSession(tmp_path, home=True)
    backend = SessionBackend(lambda: session)
    notices = Notices()
    backend.start(notices)
    try:
        notices.wait(ready)
        if operation == "save":
            backend.submit("start task")
            notices.wait(lambda n: isinstance(n, Snapshot) and n.phase == "recording")
            backend.submit("stop")
            notices.wait(
                lambda n: isinstance(n, Snapshot) and n.phase.startswith("stopped")
            )
            session.save_gate.clear()
        else:
            session.home_gate.clear()
        backend.submit(operation)
        notices.wait(lambda n: isinstance(n, Snapshot) and n.phase == operation)
        before = session.polls
        notices.wait(lambda n: isinstance(n, Snapshot) and session.polls > before)
        assert session.polls > before
        backend.emergency()
        notices.wait(lambda n: isinstance(n, LogEvent) and "ESTOP sent" in n.text)
        notices.wait(lambda n: isinstance(n, LogEvent) and "ESTOP confirmed" in n.text)
        assert session.client.sent == ["estop"]
    finally:
        backend.shutdown()
    assert session.closed == [False]


def test_emergency_send_failure_is_not_reported_as_confirmed(tmp_path):
    session = FakeSession(tmp_path)
    session.client.fail = True
    backend = SessionBackend(lambda: session)
    notices = Notices()
    backend.start(notices)
    try:
        notices.wait(ready)
        backend.emergency()
        notices.wait(lambda n: isinstance(n, LogEvent) and "SEND FAILED" in n.text)
        assert not any(
            isinstance(n, LogEvent) and "confirmed" in n.text for n in notices.items
        )
    finally:
        backend.shutdown()


@pytest.mark.parametrize("save", [True, False])
def test_timed_recording_progress_and_policy_save_choice(tmp_path, save: bool):
    session = FakeSession(tmp_path)
    plan = RecordingPlan("task", 0.15, 2, save=save)
    backend = SessionBackend(lambda: session, mode="infer", recording=plan)
    notices = Notices()
    backend.start(notices)
    try:
        notices.wait(ready)
        backend.submit("start")
        notices.wait(
            lambda n: isinstance(n, Snapshot) and n.phase == "ready: episode 2/2"
        )
        backend.submit("start")
        notices.wait(lambda n: isinstance(n, Snapshot) and n.phase == "complete")
        assert session.saved == (2 if save else 0)
        assert session.discarded == (0 if save else 2)
        assert session.started == ["task", "task"]
        assert any(
            isinstance(n, Snapshot) and n.phase.startswith("episode 2/2  [")
            for n in notices.items
        )
        # the plan is a goal, not a limit: Start is still there and runs another
        notices.wait(
            lambda n: (
                isinstance(n, Snapshot)
                and n.phase == "complete"
                and any(o.command == "start" and o.enabled for o in n.operations)
            )
        )
        backend.submit("start")
        notices.wait(
            lambda n: (
                isinstance(n, Snapshot) and n.phase == "ready: episode 4 (2 planned)"
            )
        )
        assert session.started == ["task"] * 3
    finally:
        backend.shutdown()


def test_unsaved_inference_cannot_require_confirmation():
    with pytest.raises(ValueError, match="confirm requires a plan that saves"):
        RecordingPlan("inference", 1, save=False, confirm=True)


def test_confirm_stops_for_a_decision_and_counts_only_saves(tmp_path, monkeypatch):
    session = FakeSession(tmp_path, home=True)
    controller = next(iter(session.cfg.controllers.values()))
    monkeypatch.setattr(controller, "teleop", [controller], raising=False)
    plan = RecordingPlan("task", 30, 2, home=True, confirm=True)
    backend = SessionBackend(lambda: session, mode="record", recording=plan)
    notices = Notices()
    backend.start(notices)

    def stop_episode(number: str) -> None:
        since = len(notices.items)
        backend.submit("start")
        notices.wait(
            lambda n: isinstance(n, Snapshot) and n.phase.startswith(number + "  ["),
            since=since,
        )
        backend.submit("stop")
        stopped = notices.wait_phase(
            f"stopped: save or discard ({number})", "save", "discard", since=since
        )
        ops = {o.command: o for o in stopped.operations}
        assert not ops["stop"].enabled
        assert not ops["start"].enabled
        assert ops["start"].reason == "episode already open"
        assert not ops["teleop"].enabled
        assert ops["teleop"].reason == "stopped episode: save or discard first"

    try:
        notices.wait(ready)
        stop_episode("episode 1/2")
        assert session.stopped == session.homed == 1
        assert session.saved == session.discarded == 0
        since = len(notices.items)
        backend.submit("discard")
        notices.wait_phase("ready: episode 1/2", "start", since=since)
        assert (session.saved, session.discarded, session.homed) == (0, 1, 2)

        stop_episode("episode 1/2")
        backend.submit("save failure")
        notices.wait_phase("ready: episode 2/2", "start")
        assert session.saved == 1 and session.homed == 3
        notices.wait(lambda n: isinstance(n, LogEvent) and "labelled failure" in n.text)
        stop_episode("episode 2/2")
        backend.submit("save")
        notices.wait_phase("complete", "start")
        assert session.saved == 2
        stop_episode("episode 3 (2 planned)")
    finally:
        backend.shutdown()


def test_confirm_save_refusal_does_not_count_but_a_queued_retry_does(
    tmp_path, monkeypatch
):
    session = FakeSession(tmp_path)
    save = Mock(
        side_effect=[
            SessionError("try saving again"),
            EpisodeResult("task", False, 10, pending=True),
        ]
    )
    monkeypatch.setattr(session, "save", save)
    backend = SessionBackend(
        lambda: session,
        mode="record",
        recording=RecordingPlan("task", 0.01, confirm=True),
    )
    notices = Notices()
    backend.start(notices)

    try:
        notices.wait(ready)
        backend.submit("start")
        notices.wait_phase("stopped: save or discard (episode 1/1)", "save")
        backend.submit("save")
        notices.wait_phase("save failed; retry or discard", "save", "discard")
        assert not any(
            isinstance(n, Snapshot) and n.phase == "complete" for n in notices.items
        )
        backend.submit("save success")
        notices.wait_phase("complete")
        assert [call.kwargs for call in save.call_args_list] == [
            {"label": None},
            {"label": "success"},
        ]
    finally:
        backend.shutdown()


@pytest.mark.parametrize("decision", ["save", "discard"])
def test_confirm_decision_does_not_move_home_after_estop(tmp_path, decision):
    session = FakeSession(tmp_path, home=True)
    backend = SessionBackend(
        lambda: session,
        mode="record",
        recording=RecordingPlan("task", 0.01, 2, home=True, confirm=True),
    )
    notices = Notices()
    backend.start(notices)
    try:
        notices.wait(ready)
        backend.submit("start")
        notices.wait_phase("stopped: save or discard (episode 1/2)", decision)
        backend.emergency()
        backend.submit(decision)
        notices.wait_phase("ESTOP: restart required")
        assert session.homed == 1
        assert session.saved + session.discarded == 1
    finally:
        backend.shutdown()


@pytest.mark.parametrize(
    ("mode", "save", "confirm"),
    [("record", True, False), ("infer", True, True), ("infer", False, False)],
)
def test_discard_during_a_plan_stops_and_repeats_the_episode(
    tmp_path, mode, save, confirm
):
    session = FakeSession(tmp_path)
    plan = RecordingPlan("task", 30, save=save, confirm=confirm)
    backend = SessionBackend(lambda: session, mode=mode, recording=plan)
    notices = Notices()
    backend.start(notices)
    try:
        notices.wait(ready)
        backend.submit("start")
        notices.wait(
            lambda n: (
                isinstance(n, Snapshot)
                and n.phase.startswith("episode 1/1  [")
                and any(o.command == "discard" and o.enabled for o in n.operations)
            )
        )
        since = len(notices.items)
        backend.submit("discard")
        notices.wait_phase("ready: episode 1/1", "start", since=since)
        assert (session.stopped, session.discarded, session.saved) == (1, 1, 0)
        notices.wait(lambda n: isinstance(n, LogEvent) and "discarded 'task'" in n.text)
        since = len(notices.items)
        backend.submit("start")
        notices.wait(
            lambda n: isinstance(n, Snapshot) and n.phase.startswith("episode 1/1  ["),
            since=since,
        )
        backend.submit("stop")
        if confirm:
            notices.wait_phase("stopped: save or discard (episode 1/1)", "save")
            backend.submit("save")
        notices.wait_phase("complete")
        assert (session.stopped, session.discarded, session.saved) == (
            2,
            1 if save else 2,
            int(save),
        )
    finally:
        backend.shutdown()


def test_plain_confirm_reprompts_and_counts_only_saves(tmp_path, monkeypatch, capsys):
    session = FakeSession(tmp_path)
    session.screen = None
    failure = EpisodeResult("task", True, 10, 0, label="failure")
    unlabelled = EpisodeResult("task", True, 10, 1)
    save = Mock(
        side_effect=[EpisodeResult("task", False, 10, pending=True), unlabelled]
    )
    wait_saves = Mock(return_value=[failure])
    monkeypatch.setattr(session, "save", save)
    monkeypatch.setattr(session, "wait_saves", wait_saves)
    answers = iter(["unknown", " D ", " SAVE failure ", "s"])
    prompts = []

    def answer(prompt):
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("builtins.input", answer)
    discarded, first, second = record(session, "task", 0, 2, confirm=True)
    assert not discarded.saved and session.discarded == 1
    assert first is failure and second is unlabelled
    assert [call.kwargs["label"] for call in save.call_args_list] == ["failure", None]
    assert [p.split(":")[0] for p in prompts] == ["episode 1/2"] * 3 + ["episode 2/2"]
    assert capsys.readouterr().out.count("stopped 'task' (10 rows)") == 3
    wait_saves.assert_called_once_with()


@pytest.mark.parametrize("interrupt", [EOFError, KeyboardInterrupt])
def test_plain_confirm_discards_and_stops_on_interruption(
    tmp_path, monkeypatch, interrupt
):
    session = FakeSession(tmp_path)
    session.screen = None
    monkeypatch.setattr("builtins.input", Mock(side_effect=interrupt))
    with pytest.raises(Cancelled, match="stopped by the operator"):
        record(session, "task", 0, 2, confirm=True)
    assert (session.stopped, session.discarded, session.saved) == (1, 1, 0)
    assert session.started == ["task"]


def test_confirmation_is_refused_in_the_legacy_key_screen(tmp_path, monkeypatch):
    session = FakeSession(tmp_path)
    session.screen = Mock()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    with pytest.raises(ValueError, match="confirm is unavailable"):
        record(session, "task", 1, confirm=True)
    assert not session.started


def test_poll_listener_cannot_steal_operation_response(tmp_path):
    report = tmp_path / "report.jsonl"
    report.write_text("")
    process = Mock()
    process.poll.return_value = None
    with tempfile.TemporaryDirectory() as work:
        session = Session(
            load_config("examples/mock/config.yaml"),
            process,
            SessionClient(tmp_path / "fifo", report, tmp_path / "status.json"),
            tmp_path,
            tempfile.TemporaryDirectory(dir=work),
            tmp_path / "fifo",
        )
        heard: list[dict] = []
        session.listen(heard.append)
        report.write_text(
            json.dumps({"id": 7, "command": "save", "saved_frames": 42}) + "\n"
        )
        thread = threading.Thread(target=session.poll)
        thread.start()
        assert session.wait_report(7)["saved_frames"] == 42
        thread.join()
        assert len(heard) == 1
        cancelled = threading.Event()
        cancelled.set()
        with session._cancellable(cancelled), pytest.raises(Cancelled):
            session.wait_report(8)
        # Cancellation belongs to the worker's scope; cleanup remains available.
        report.write_text(report.read_text() + json.dumps({"id": 9}) + "\n")
        assert session.wait_report(9)["id"] == 9
        session._workdir.cleanup()


def tuning_factory(
    tmp_path: Path, sessions: list[TuningSession], ownership: list[str]
) -> Callable[[], TuningSession]:
    path = tmp_path / "tuning.yaml"
    path.write_text(
        "# preserve\njoints: {a: {gain: 1, hold_mA: 0}, b: {gain: 0, hold_mA: 0}}\n"
    )

    def open_session() -> TuningSession:
        ownership.append(threading.current_thread().name)
        dev, bus = device(
            [
                {**GRAVITY, "gravity_gain": [1.0, 0.0]},
                {"group": "c", "law": "free", "joints": ["c"]},
            ],
            [0, 0, 3],
            FlatGravity(),
        )
        law = dev.laws[0]
        assert isinstance(law, GravityComp)
        original = bus.set_torque

        def torque(indices: list[int], on: bool) -> None:
            ownership.append(threading.current_thread().name)
            original(indices, on)

        bus.set_torque = torque
        original_close = dev.close

        def close() -> None:
            ownership.append(threading.current_thread().name)
            original_close()

        dev.close = close
        session = TuningSession(dev, law, path, period_s=0.005)
        sessions.append(session)
        return session

    return open_session


def test_tuning_save_does_not_block_control_and_keeps_new_changes_dirty(
    tmp_path, monkeypatch
):
    sessions: list[TuningSession] = []
    ownership: list[str] = []
    started, finish = threading.Event(), threading.Event()
    original_write = TuningSave.write

    def blocked_write(saved: TuningSave) -> Path:
        started.set()
        assert finish.wait(5)
        return original_write(saved)

    monkeypatch.setattr(TuningSave, "write", blocked_write)
    backend = TuningBackend(tuning_factory(tmp_path, sessions, ownership), "tuning")
    notices = Notices()
    backend.start(notices)
    try:
        notices.wait(lambda n: isinstance(n, Snapshot) and n.phase == "running")
        backend.submit("gain +")
        notices.wait(lambda n: isinstance(n, Snapshot) and n.dirty)
        backend.submit("save")
        assert started.wait(5)
        backend.submit("gain +")
        notices.wait(
            lambda n: (
                isinstance(n, Snapshot)
                and bool(n.nodes)
                and n.nodes[0].fields["gain"] == 1.2
            )
        )
        backend.emergency()
        notices.wait(
            lambda n: isinstance(n, LogEvent) and "torque-off confirmed" in n.text
        )
        backend.submit("resume")
        notices.wait(
            lambda n: isinstance(n, LogEvent) and "resume is disabled" in n.text
        )
        finish.set()
        notices.wait(
            lambda n: (
                isinstance(n, LogEvent) and "newer changes remain unsaved" in n.text
            )
        )
        assert (
            yaml.safe_load((tmp_path / "tuning.yaml").read_text())["joints"]["a"][
                "gain"
            ]
            == 1.1
        )
        backend.request_close("discard")
        notices.wait(lambda n: isinstance(n, Closed))
    finally:
        finish.set()
        backend.shutdown()
    assert set(ownership) == {"gravity-control"}
    assert sessions[0].dirty and sessions[0].estopped


def test_tuning_failure_still_closes_device(tmp_path):
    sessions: list[TuningSession] = []
    ownership: list[str] = []
    factory = tuning_factory(tmp_path, sessions, ownership)

    def failing() -> TuningSession:
        session = factory()

        def step(now_ns: int | None = None) -> None:
            raise OSError("bus read failure")

        session.step = step
        return session

    backend = TuningBackend(failing, "tuning")
    notices = Notices()
    backend.start(notices)
    notices.wait(lambda n: isinstance(n, Closed))
    backend.shutdown()
    assert len(ownership) >= 3 and set(ownership) == {"gravity-control"}


def test_tuning_save_failure_preserves_dirty_values_and_allows_retry(
    tmp_path, monkeypatch
):
    sessions: list[TuningSession] = []
    ownership: list[str] = []
    original_write = TuningSave.write

    def failed_write(saved: TuningSave) -> Path:
        raise OSError("disk write refused")

    monkeypatch.setattr(TuningSave, "write", failed_write)
    backend = TuningBackend(tuning_factory(tmp_path, sessions, ownership), "tuning")
    notices = Notices()
    backend.start(notices)
    try:
        notices.wait(lambda n: isinstance(n, Snapshot) and n.phase == "running")
        backend.submit("hold +")
        notices.wait(lambda n: isinstance(n, Snapshot) and n.dirty)
        backend.request_close("save")
        notices.wait(
            lambda n: (
                isinstance(n, Snapshot) and n.phase == "save failed; retry or discard"
            )
        )
        assert sessions[0].dirty
        assert (
            yaml.safe_load((tmp_path / "tuning.yaml").read_text())["joints"]["a"][
                "hold_mA"
            ]
            == 0
        )
        monkeypatch.setattr(TuningSave, "write", original_write)
        backend.request_close("save")
        notices.wait(lambda n: isinstance(n, Closed) and n.outcome == "saved")
        assert (
            yaml.safe_load((tmp_path / "tuning.yaml").read_text())["joints"]["a"][
                "hold_mA"
            ]
            == 5
        )
    finally:
        backend.shutdown()


def test_no_home_or_follower_torque_is_a_capability_not_a_kind_check(tmp_path):
    session = FakeSession(tmp_path)
    for robot in session.cfg.followers.values():
        robot.torque = False
    backend = SessionBackend(lambda: session)
    notices = Notices()
    backend.start(notices)
    try:
        snapshot = notices.wait(ready)
        assert isinstance(snapshot, Snapshot)
        assert (
            not snapshot.capabilities.home
            and not snapshot.capabilities.hold
            and not snapshot.capabilities.gravity
        )
        assert not next(o for o in snapshot.operations if o.command == "home").enabled
        assert not next(
            o for o in snapshot.operations if o.command == "release"
        ).enabled
    finally:
        backend.shutdown()


def test_report_log_lines_keep_their_style():
    notices: list = []
    backend = SessionBackend(lambda: None)
    backend._publish = notices.append
    backend._report({"command": "home", "ok": True})
    assert notices[-1].style == "magenta"


@pytest.mark.parametrize("confirm", [False, True])
def test_an_episode_of_the_plan_ends_on_the_policys_steps(tmp_path, confirm):
    session = FakeSession(tmp_path)
    usual, since = session.status, [time.monotonic()]

    def status() -> dict:  # the policy executes 40 actions a second
        step = int((time.monotonic() - since[0]) * 40)
        return {**usual(), "policy": {"fields": {"step": step}}}

    session.status = status  # type: ignore[method-assign]
    plan = RecordingPlan("task", 30.0, 1, steps=10, confirm=confirm)
    backend = SessionBackend(lambda: session, mode="infer", recording=plan)
    notices = Notices()
    backend.start(notices)
    try:
        notices.wait(ready)
        began = since[0] = time.monotonic()
        backend.submit("start")
        if confirm:
            notices.wait_phase("stopped: save or discard (episode 1/1)", "save")
            assert session.saved == 0
            backend.submit("save")
        notices.wait_phase("complete")
        assert time.monotonic() - began < 10
        assert any(
            isinstance(n, Snapshot) and "  step " in n.phase and "/10  [" in n.phase
            for n in notices.items
        )
        assert not any(
            isinstance(n, LogEvent) and "ended by time" in n.text for n in notices.items
        )
    finally:
        backend.shutdown()
