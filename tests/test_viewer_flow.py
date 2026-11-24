"""The viewer in the dataflow: its node reads exactly the recorded streams (newest
only), the session sees its status, and the loop keeps the newest envelopes until quit."""

from __future__ import annotations

import sys

from conftest import mock_project

from roboloom.config import load_config
from roboloom.core.protocol import Envelope, Publisher
from roboloom.runtime import viewer
from roboloom.runtime.flow import build_flow


def test_viewer_off_leaves_the_flow_unchanged(tmp_path):
    project = mock_project(tmp_path / ".roboloom")
    path = project / "config.yaml"
    off = load_config(path, options=["digit"], mock=True)
    on = load_config(path, options=["digit", "viewer"], mock=True)
    assert off.viewer is None
    before = build_flow(off)
    assert not any(n["id"] == "viewer" for n in before["nodes"])
    session = next(n for n in before["nodes"] if n["id"] == "session")
    assert "viewer_status" not in session["inputs"]
    on.viewer = None  # the same configuration with the viewer turned off
    assert build_flow(on) == before


def test_the_viewer_node_reads_every_recorded_stream(tmp_path):
    project = mock_project(tmp_path / ".roboloom")
    cfg = load_config(project / "config.yaml", options=["digit", "viewer"], mock=True)
    nodes = {n["id"]: n for n in build_flow(cfg)["nodes"]}
    assert "viewer" in nodes
    seen = nodes["viewer"]
    assert seen["outputs"] == ["status"]
    assert seen["args"].split()[-2:] == ["viewer", cfg.path]
    assert seen["inputs"]["session"] == "session/control"
    assert seen["inputs"]["tick"] == "dora/timer/hz/10"
    # newest only: the view never holds a source back
    for eid, spec in seen["inputs"].items():
        if eid in ("session", "tick"):
            continue
        assert spec["queue_size"] == 1
        assert spec["queue_policy"] == "drop_oldest"
    # exactly the streams the recorder records
    recorder = nodes["recorder"]
    assert {
        k: v["source"]
        for k, v in seen["inputs"].items()
        if k not in ("session", "tick")
    } == {k: v["source"] for k, v in recorder["inputs"].items() if k != "session"}
    assert "action_follower" in seen["inputs"]
    # the session receives the viewer's status like every other node's
    status = nodes["session"]["inputs"]["viewer_status"]
    assert status["source"] == "viewer/status"
    assert status["queue_size"] == 2 and status["queue_policy"] == "drop_oldest"


def test_the_viewer_tick_follows_its_rate(tmp_path):
    project = mock_project(tmp_path / ".roboloom")
    (project / "nodes" / "viewer.yaml").write_text("rate_hz: 12.5\n")
    cfg = load_config(project / "config.yaml", options=["viewer"], mock=True)
    nodes = {n["id"]: n for n in build_flow(cfg)["nodes"]}
    assert nodes["viewer"]["inputs"]["tick"] == "dora/timer/millis/80"


def test_the_viewer_loop_keeps_the_newest_and_quits(monkeypatch):
    cfg = load_config("examples/mock/config.yaml")
    camera = Publisher("camera")
    quit_msg = Publisher("session").make("control", {"command": "quit"})
    events = iter(
        [
            {
                "type": "INPUT",
                "id": "camera",
                "value": camera.make("sample", {"frame": 1}).encode(),
            },
            {
                "type": "INPUT",
                "id": "camera",
                "value": camera.make("sample", {"frame": 2}).encode(),
            },
            {"type": "INPUT", "id": "tick", "value": b""},
            {"type": "INPUT", "id": "session", "value": quit_msg.encode()},
        ]
    )
    clock = {"ns": 1_000_000_000}

    class Node:
        def __init__(self) -> None:
            self.sent: list[tuple[str, Envelope]] = []

        def next(self, timeout=None):
            clock["ns"] += 600_000_000  # past the status period on every event
            return next(events)

        def drain(self):
            return []

        def send_output(self, output: str, value: bytes) -> None:
            self.sent.append((output, Envelope.decode(value)))

    drawn: list[dict] = []
    monkeypatch.setattr(viewer, "draw", lambda latest, cfg: drawn.append(dict(latest)))
    monkeypatch.setattr(viewer.time, "monotonic_ns", lambda: clock["ns"])
    node = Node()
    viewer.run(node, cfg)  # returns on the session's quit
    assert next(events, None) is None
    # one redraw on the tick, with the newest of the two samples
    assert len(drawn) == 1
    assert drawn[0]["camera"].payload["frame"] == 2
    assert "session" not in drawn[0]
    statuses = [msg for output, msg in node.sent if output == "status"]
    assert statuses
    assert statuses[-1].payload["role"] == "viewer"
    assert statuses[-1].payload["level"] == "ok"
    assert statuses[-1].payload["fields"] == {
        "state": "viewing",
        "streams": 1,
        "drawn": 1,
        "errors": 0,
        "target": None,  # examples/mock has no viewer; the loop still runs
    }


def test_main_dispatches_the_viewer(monkeypatch):
    import dora

    from roboloom.runtime import node as runtime

    cfg = load_config("examples/mock/config.yaml")
    seen = []
    monkeypatch.setattr(runtime, "config_from_env", lambda path, env: cfg)
    monkeypatch.setattr(dora, "Node", lambda: "the-node")
    monkeypatch.setattr(viewer, "run", lambda node, cfg: seen.append((node, cfg)))
    monkeypatch.setattr(sys, "argv", ["node.py", "viewer", cfg.path])
    runtime.main()
    assert seen == [("the-node", cfg)]
