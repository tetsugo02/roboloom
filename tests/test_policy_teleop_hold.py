"""The operator's Teleop toggle reports runtime refusals while the robot holds."""

from __future__ import annotations

import time

from test_operator_backends import FakeSession

from roboloom.ui.backend import SessionBackend
from roboloom.ui.models import LogEvent, Operation


def test_teleop_toggle_checks_alignment_and_fault_before_submission(
    tmp_path, monkeypatch
):
    session = FakeSession(tmp_path)
    backend = SessionBackend(lambda: session)
    backend.session = session
    backend._busy = False
    report = session.status
    controller = {
        "state": "aligning",
        "worst_joint": "head_yaw",
        "worst_diff": 42,
        "tolerance": 10,
    }
    follower = {"mode": "HOLD"}

    def status():
        live = report()
        live["controller"]["fields"].update(controller)
        live["follower"]["fields"].update(follower)
        return live

    monkeypatch.setattr(session, "status", status)

    def operations(snapshot):
        assert (
            sum(
                o.command in {"teleop", "stop_teleop", "policy"}
                for o in snapshot.operations
            )
            == 1
        )
        return {o.command: o for o in snapshot.operations}

    snapshot = backend._snapshot()
    ops = operations(snapshot)
    assert snapshot.warning == ""
    assert snapshot.alignment == "head_yaw 42/10"
    assert not ops["start"].enabled and "align the leader" in ops["start"].reason
    assert ops["teleop"].label == "TELEOP: OFF"
    assert not ops["teleop"].enabled and "align the leader" in ops["teleop"].reason

    follower.update(mode="FAULT", reason="bus error")
    snapshot = backend._snapshot()
    ops = operations(snapshot)
    assert snapshot.warning == "follower: FAULT: bus error"
    assert ops["teleop"].label == "TELEOP: OFF"
    assert not ops["teleop"].enabled and "FAULT" in ops["teleop"].reason
    notices = []
    backend._publish = notices.append
    backend.submit("teleop")
    assert notices == [LogEvent(ops["teleop"].reason, "warn")]

    follower.update(mode="HOLD", reason="")
    controller.update(state="following", worst_diff=0)
    assert operations(backend._snapshot())["teleop"] == Operation(
        "teleop", "TELEOP: OFF"
    )

    follower["armed"] = True
    assert operations(backend._snapshot())["stop_teleop"] == Operation(
        "stop_teleop", "TELEOP: ON"
    )

    backend._recording = backend._episode = True
    assert operations(backend._snapshot())["teleop"] == Operation(
        "teleop", "TELEOP: ON", False, "the input already drives the episode"
    )


def test_stale_and_failed_nodes_report_problems(tmp_path, monkeypatch):
    session = FakeSession(tmp_path)
    backend = SessionBackend(lambda: session)
    backend.session = session
    report = session.status

    def status():
        live = report()
        live["follower"]["t_ns"] = time.monotonic_ns() - 3_000_000_000
        live["controller"]["fields"].update(state="failed", error="checkpoint missing")
        return live

    monkeypatch.setattr(session, "status", status)
    assert backend._snapshot().warning == (
        "follower: no status for 3 s; controller: controller failed: checkpoint missing"
    )
