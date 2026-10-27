"""Thread ownership, cancellation, and saves tested with fake Session / MockBus."""

from __future__ import annotations

import json
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

from roboloom.config import load_experiment, parse_experiment
from roboloom.control.laws import GravityComp
from roboloom.control.tuning import TuningSave, TuningSession
from roboloom.errors import Cancelled
from roboloom.runtime.session import EpisodeResult, Session, SessionError
from roboloom.ui.backend import RecordingPlan, SessionBackend
from roboloom.ui.client import SessionClient
from roboloom.ui.models import Closed, LogEvent, Notice, Snapshot
from roboloom.ui.tuning_backend import TuningBackend


class Notices:
    def __init__(self) -> None:
        self.items: list[Notice] = []
        self.condition = threading.Condition()

    def __call__(self, notice: Notice) -> None:
        with self.condition:
            self.items.append(notice)
            self.condition.notify_all()

    def wait(self, predicate: Callable[[Notice], bool], timeout: float = 5) -> Notice:
        end = time.monotonic() + timeout
        with self.condition:
            while True:
                found = next(
                    (item for item in reversed(self.items) if predicate(item)), None
                )
                if found is not None:
                    return found
                remaining = end - time.monotonic()
                assert remaining > 0, self.items[-4:]
                self.condition.wait(remaining)


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
            parse_experiment(home_tree(tmp_path))
            if home
            else load_experiment("examples/mock/experiment.yaml")
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
            ("robot", self.cfg.robots),
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
                if role == "robot":
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

    def stop(self) -> EpisodeResult:
        self._check_cancelled()
        return EpisodeResult(self.started[-1], False, 10)

    def save(self, timeout: float = 300) -> EpisodeResult:
        while not self.save_gate.wait(0.01):
            self._check_cancelled()
        self.saved += 1
        return EpisodeResult(self.started[-1], True, 10, self.saved - 1)

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
        time.sleep(0.15)
        backend.submit("start second")
        notices.wait(lambda n: isinstance(n, Snapshot) and n.phase == "recording")
        assert session.started == ["second"]
        backend.request_close("release")
    finally:
        backend.shutdown()
        backend.shutdown()
    assert session.closed == [True]


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
        time.sleep(0.25)
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
    finally:
        backend.shutdown()


def test_poll_listener_cannot_steal_operation_response(tmp_path):
    report = tmp_path / "report.jsonl"
    report.write_text("")
    process = Mock()
    process.poll.return_value = None
    with tempfile.TemporaryDirectory() as work:
        session = Session(
            load_experiment("examples/mock/experiment.yaml"),
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
    for robot in session.cfg.robots.values():
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


def test_tuning_close_releases_position_groups_before_closing_the_bus(tmp_path):
    path = tmp_path / "tuning.yaml"
    path.write_text("joints: {}\n")
    dev, bus = device(
        [GRAVITY, {"group": "c", "law": "position", "joints": ["c"]}],
        [0, 0, 3],
        FlatGravity(),
    )
    law = dev.laws[0]
    assert isinstance(law, GravityComp)
    session = TuningSession(dev, law, path)
    session.start()
    assert bus.torque[2]
    torque_at_close: list[list[bool]] = []

    def close_bus() -> None:
        torque_at_close.append(list(bus.torque))

    bus.close = close_bus
    session.close()
    assert torque_at_close == [[False, False, False]]
