import json
import threading
import time
from argparse import Namespace
from types import SimpleNamespace

import pytest
from rich.console import Console

from roboloom import cli
from roboloom.config import load_config
from roboloom.controllers.joint import JointController
from roboloom.core.protocol import Envelope, Publisher
from roboloom.core.status import StatusReporter
from roboloom.runtime.session import Session
from roboloom.ui import record
from roboloom.ui.client import SessionClient
from roboloom.ui.launcher import LaunchPlan
from roboloom.ui.live import LineEditor
from roboloom.ui.render import RENDERERS, describe_report, render

S = 1_000_000_000


def text_of(renderable) -> str:
    console = Console(record=True, width=160)
    console.print(renderable)
    return console.export_text()


def test_status_reporter_is_throttled():
    reporter = StatusReporter(Publisher("follower"), "follower", period_s=0.25)
    assert reporter.maybe({"mode": "HOLD"}, now_ns=S) is not None
    assert reporter.maybe({"mode": "HOLD"}, now_ns=S + S // 10) is None
    msg = reporter.maybe({"mode": "ACTIVE"}, "ok", now_ns=S + S // 2)
    assert msg is not None
    assert msg.payload == {
        "role": "follower",
        "level": "ok",
        "fields": {"mode": "ACTIVE"},
    }


def test_controller_reports_why_it_is_not_following():
    ctl = load_config("examples/mock/config.yaml").controllers["controller"]
    assert isinstance(ctl, JointController)
    now = time.monotonic_ns()
    far = [2048] * 17
    far[2] = 2400  # head_pitch 352 counts away
    ctl.step(
        Envelope("joint_intent", "leader", "boot", 0, now, now, {"positions": far}),
        [2048] * 17,
        now,
    )
    status = ctl.status()
    assert (
        status["state"] == "aligning"
        and status["worst_joint"] == "head_pitch"
        and status["worst_diff"] == 352
    )
    ctl.step(
        Envelope(
            "joint_intent", "leader", "boot", 1, now, now, {"positions": [2048] * 17}
        ),
        [2048] * 17,
        now,
    )
    assert ctl.status()["state"] == "following"
    old = now - 2 * S
    ctl.step(
        Envelope(
            "joint_intent", "leader", "boot", 2, old, old, {"positions": [2048] * 17}
        ),
        [2048] * 17,
        now,
    )
    assert ctl.status()["state"] == "input_stale"


def test_render_known_unknown_and_stale_nodes():
    now = 100 * S
    status = {
        "experiment": "/x/experiment.yaml",
        "mode": "hardware",
        "nodes": {
            "follower": {
                "role": "follower",
                "level": "error",
                "t_ns": now,
                "fields": {
                    "mode": "FAULT",
                    "reason": "hardware error [0, 4]",
                    "armed": False,
                },
            },
            "controller": {
                "role": "controller",
                "level": "warn",
                "t_ns": now,
                "fields": {
                    "state": "aligning",
                    "worst_joint": "head_pitch",
                    "worst_diff": 310,
                    "tolerance": 150,
                },
            },
            "gripper_ft": {
                "role": "force_sensor",
                "level": "ok",
                "t_ns": now,
                "fields": {"state": "ok", "fz_N": 1.5},
            },
            "camera": {
                "role": "sensor",
                "level": "ok",
                "t_ns": now - 5 * S,
                "fields": {"rate_hz": 30},
            },
        },
    }
    text = text_of(render(status, ["saved"], "roboloom> ", now_ns=now))
    assert "FAULT" in text and "hardware error" in text
    assert "head_pitch differs by 310" in text
    assert "fz_N=1.5" in text  # unregistered role falls back to key=value
    assert "no status 5 s" in text
    assert text.index("follower") < text.index("controller") < text.index("camera")
    assert "sensor" in RENDERERS and "follower" in RENDERERS


def test_report_lines():
    warning = describe_report(
        {"command": "start", "warning": "l_arm_wr_yaw differs by 380.0 (tolerance 150)"}
    )
    assert warning.style == "bold yellow"
    assert warning.plain == (
        "start not started: l_arm_wr_yaw differs by 380.0 (tolerance 150)"
    )
    assert (
        "saved 10 frames"
        in describe_report(
            {
                "saved_frames": 10,
                "episodes": 2,
                "metrics": {"missing_rate": {"camera": 0.1}},
            }
        ).plain
    )
    assert (
        describe_report({"follower_mode": "FAULT", "reason": "bus"}).style == "bold red"
    )
    assert (
        "save failed"
        in describe_report({"command": "save", "error": "empty episode"}).plain
    )


def test_line_editor_and_client_files(tmp_path):
    editor = LineEditor()
    assert [editor.feed(c) for c in "stoq\x7fp"] == [None] * 6 and editor.feed(
        "\r"
    ) == "stop"
    assert (
        editor.feed("x") is None and editor.feed("\x15") is None and editor.buffer == ""
    )
    assert editor.feed("\x03") == "quit"
    report, status = tmp_path / "report.jsonl", tmp_path / "status.json"
    report.write_text(json.dumps({"saved_frames": 1}) + "\n" + '{"partial"')
    client = SessionClient(tmp_path / "fifo", report, status)
    assert client.new_reports() == [{"saved_frames": 1}]
    with open(report, "a") as f:
        f.write(": 1}\n")
    assert client.new_reports() == [{"partial": 1}]
    assert client.status() is None
    status.write_text(json.dumps({"nodes": {}}))
    assert client.status() == {"nodes": {}}


@pytest.mark.parametrize("mode", ["run", "record", "infer"])
def test_plain_commands_announce_viewer_urls_once_per_change(
    mode, tmp_path, monkeypatch, capsys
):
    def viewer_status(url, local_url):
        return {"nodes": {"viewer": {"fields": {"url": url, "local_url": local_url}}}}

    url = "http://robot.example:9090/"
    updated = "http://other.example:9090/"
    local_url = "http://localhost:9090/"
    external = viewer_status(None, None)
    first = viewer_status(url, local_url)
    changed = viewer_status(updated, local_url)
    statuses = iter([{}, external, first, first, {}, first, changed, changed])
    finished = threading.Event()

    def status():
        item = next(statuses, None)
        if item is None:
            finished.set()
            return changed
        return item

    def wait_for_status_updates(*args, **kwargs):
        assert finished.wait(5)

    session = SimpleNamespace(
        client=SimpleNamespace(status=status),
        process=SimpleNamespace(returncode=0),
        log_dir=tmp_path,
        release_note=lambda: "",
        close=lambda: None,
    )
    cfg = load_config("examples/mock/config.yaml")
    cfg.viewer = {"serve": True, "ip": None}
    monkeypatch.setattr(Session, "launch", lambda *args, **kwargs: session)
    monkeypatch.setattr(cli, "_plain_loop", wait_for_status_updates)
    monkeypatch.setattr(record, "record", wait_for_status_updates)
    cli._start(Namespace(), cfg, LaunchPlan(mode=mode), live=False, reselect=False)

    lines = [
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("viewer:")
    ]
    assert lines == [
        f"viewer: open Rerun in a browser: {url}",
        f"viewer: through SSH port forwarding: {local_url}",
        f"viewer: open Rerun in a browser: {updated}",
        f"viewer: through SSH port forwarding: {local_url}",
    ]


def styles_of(text) -> dict[str, str]:
    """Plain substring -> style of each styled span of a rich Text."""
    return {text.plain[s.start : s.end]: str(s.style) for s in text.spans}


def test_home_pose_and_problems_stand_out_in_the_detail():
    _, detail = RENDERERS["controller"]({"state": "following", "home": "ready"})
    assert "home pose: ready.yaml" in detail.plain
    assert styles_of(detail)["ready.yaml"] == "bold magenta"
    _, detail = RENDERERS["follower"](
        {
            "mode": "HOMING",
            "armed": False,
            "home": "ready",
            "home_state": "moving",
            "home_progress": 0.4,
            "error": "bus failed",
        }
    )
    spans = styles_of(detail)
    assert spans["ready"] == "bold magenta" and spans["moving 40%"] == "yellow"
    assert spans["last error: bus failed"] == "bold red"
    _, detail = RENDERERS["input"](
        {
            "rate_hz": 120,
            "age_ms": 0,
            "home": "ready",
            "home_state": "short",
            "home_far": {"r_arm_sh_roll": -42},
            "work_ms": 7.5,
            "work_max_ms": 7.5,
        }
    )
    spans = styles_of(detail)
    assert spans["short"] == "yellow" and "r_arm_sh_roll -42" in detail.plain
    assert spans["work 7.5 ms (max 7.5)"] == "yellow"  # 7.5 of 8.3 ms: little room


def test_home_is_inactive_without_a_saved_pose():
    without = {"nodes": {"controller": {"role": "controller", "fields": {}}}}
    with_home = {
        "nodes": {"controller": {"role": "controller", "fields": {"home": "ready"}}}
    }
    off = text_of(render(without, [], "> ", now_ns=0))
    on = text_of(render(with_home, [], "> ", now_ns=0))
    assert "home (no home pose)" in off and "(no home pose)" not in on
    from roboloom.ui.render import command_line

    line = command_line(False, ("Enter: start", "h: home"))
    assert styles_of(line)["h: home"] == "strike"
