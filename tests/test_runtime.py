import json
import os
from pathlib import Path

import pytest

from roboloom.config import load_experiment
from roboloom.core.protocol import Envelope, Publisher
from roboloom.runtime import node as runtime

S = 1_000_000_000


@pytest.mark.parametrize(
    ("state", "age_ns"),
    [
        ("following", S + 1),
        ("following", -1),
        ("waiting_input", 0),
        ("input_stale", 0),
        ("robot_fault", 0),
    ],
)
def test_start_requires_recent_following_status(state: str, age_ns: int) -> None:
    cfg = load_experiment("examples/mock/experiment.yaml")
    latest = {"controller": {"t_ns": S - age_ns, "fields": {"state": state}}}
    assert runtime.start_warning(cfg, latest, S) is not None
    assert runtime.start_warning(cfg, {}, S) is not None


def test_every_start_checks_the_follower_is_at_the_leader() -> None:
    cfg = load_experiment("examples/mock/experiment.yaml")
    fields = {"state": "following", "tolerance": 100, "worst_joint": "head_yaw"}
    latest = {"controller": {"t_ns": S, "fields": {**fields, "worst_diff": 140.0}}}
    warning = runtime.start_warning(cfg, latest, S)
    assert warning is not None and "head_yaw differs by 140.0" in warning
    latest["controller"]["fields"]["worst_diff"] = 60.0
    assert runtime.start_warning(cfg, latest, S) is None


def test_session_warns_without_starting_then_accepts_aligned_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = load_experiment("examples/mock/experiment.yaml")
    fifo = tmp_path / "session.fifo"
    report = tmp_path / "report.jsonl"
    status = tmp_path / "status.json"
    os.mkfifo(fifo)
    monkeypatch.setenv("ROBOLOOM_SESSION_FIFO", str(fifo))
    monkeypatch.setenv("ROBOLOOM_REPORT_PATH", str(report))
    monkeypatch.setenv("ROBOLOOM_STATUS_PATH", str(status))
    now = S
    reads = iter([b"", b"start rejected task\n", b"", b"start retry task\n", b"quit\n"])

    def read(fd: int, count: int) -> bytes:
        nonlocal now
        now += S // 4
        return next(reads)

    monkeypatch.setattr(runtime.os, "read", read)
    monkeypatch.setattr(runtime.time, "monotonic_ns", lambda: now)
    publisher = Publisher("controller")
    events = iter(
        [
            (
                "controller_status",
                {
                    "state": "aligning",
                    "worst_joint": "l_arm_wr_yaw",
                    "worst_diff": 380.0,
                    "tolerance": 150,
                },
            ),
            ("robot_status", {"mode": "HOLD", "armed": False}),
            ("controller_status", {"state": "following"}),
            (None, None),
        ]
    )

    def event(node: object) -> tuple[str | None, Envelope | None]:
        name, fields = next(events)
        msg = publisher.make("status", {"fields": fields}, now) if fields else None
        return name, msg

    monkeypatch.setattr(runtime, "_event", event)

    class Node:
        def __init__(self) -> None:
            self.sent: list[Envelope] = []

        def send_output(self, output: str, value: bytes) -> None:
            assert output == "control"
            self.sent.append(Envelope.decode(value))

    node = Node()
    runtime._session(node, cfg)

    # The rejected request reaches neither the robot nor the recorder. The same
    # session keeps consuming status and accepts a new start after alignment.
    assert [msg.payload for msg in node.sent] == [
        {"command": "start", "task": "retry task"},
        {"command": "quit", "task": ""},
    ]
    reports = [json.loads(line) for line in report.read_text().splitlines()]
    assert len(reports) == 1 and reports[0]["command"] == "start"
    assert "l_arm_wr_yaw differs by 380.0 (tolerance 150)" in reports[0]["warning"]
    assert "retry start" in reports[0]["warning"]
    latest = json.loads(status.read_text())["nodes"]
    assert latest["controller"]["fields"]["state"] == "following"
    assert latest["robot"]["fields"] == {"mode": "HOLD", "armed": False}
