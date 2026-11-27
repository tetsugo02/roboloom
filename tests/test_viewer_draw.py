"""The viewer draws in Rerun: a real .rrd recording of the mock rakuda2 sources, the
action only when every follower sent a valid one, and a view that never stops the flow."""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path

import numpy as np
import pytest
import yaml
from conftest import mock_project, requires_rerun

from roboloom.config import RobotConfig, load_config
from roboloom.core.protocol import Envelope, Publisher
from roboloom.recording import action_stream
from roboloom.recording.schema import state_names
from roboloom.robots.safety import FollowerSafety
from roboloom.runtime import viewer

pytestmark = requires_rerun


def _config(tmp_path: Path, **settings) -> RobotConfig:
    """A mock rakuda2 with digit and the viewer saving to a .rrd in tmp_path."""
    project = mock_project(tmp_path / ".roboloom")
    given = {"serve": False, "save": str(tmp_path / "view.rrd"), **settings}
    (project / "nodes" / "viewer.yaml").write_text(yaml.safe_dump(given))
    return load_config(project / "config.yaml", options=["digit", "viewer"], mock=True)


def _latest(cfg: RobotConfig) -> dict[str, Envelope]:
    """One real envelope per source, as the nodes publish them: the mock readers for
    the inputs and sensors, a mock follower's safety tick for its state, and a valid
    action per follower."""
    latest: dict[str, Envelope] = {}
    for name, source in cfg.sources.items():
        if name in cfg.followers:
            continue
        reader = source.open(True, cfg.dataset_fps)
        try:
            sample = reader.read()
        finally:
            reader.close()
        assert sample is not None
        latest[name] = Publisher(name).make(
            source.kind, source.encode(sample), sample.capture_ns
        )
    for name, follower in cfg.followers.items():
        bus = follower.open_device(True)
        safety = FollowerSafety(follower.safety_config(), bus)
        safety.start()
        try:
            state, _ = safety.tick()
        finally:
            bus.close()
        latest[name] = state
        latest[action_stream(name)] = Publisher(name).make(
            "action",
            {
                "positions": list(state.payload["positions"]),
                "valid": True,
                "clamped": False,
                "command_seq": 0,
                "t_sent_ns": time.monotonic_ns(),
            },
        )
    return latest


def _shutdown() -> None:
    import rerun as rr

    rr.rerun_shutdown()


def _reader(cfg: RobotConfig):
    from rerun.experimental import RrdReader

    return RrdReader(cfg.viewer["save"])


def test_the_view_is_recorded_to_the_rrd(tmp_path):
    cfg = _config(tmp_path)
    latest = _latest(cfg)
    viewer.start(cfg)
    try:
        viewer.draw(latest, cfg)
        viewer.draw(latest, cfg)
    finally:
        _shutdown()
    reader = _reader(cfg)
    assert len(reader.blueprints()) == 1
    views = Counter()
    for chunk in reader.stream(store=reader.blueprints()[0]):
        batch = chunk.to_record_batch()
        column = "ViewBlueprint:class_identifier"
        if column in batch.schema.names:
            views.update(
                value for row in batch.column(column).to_pylist() for value in row
            )
    assert views == {"2D": 3, "TimeSeries": 3, "TextLog": 1}
    store = reader.store()
    paths = {c.entity_path for c in store.schema().component_columns()}
    assert {
        "/observation.images.camera",
        "/observation.images.digit_left",
        "/observation.images.digit_right",
        "/observation.state",
        "/observation.leader",
        "/action.follower",
        "/meta/digit_left/capture_age_ms",
    } <= paths
    dim = len(state_names(cfg.followers))
    rows: dict[str, int] = {}
    vectors: dict[str, list] = {}
    for chunk in store.stream():
        if chunk.entity_path == "/__properties":
            continue  # Rerun's own recording properties
        rows[chunk.entity_path] = rows.get(chunk.entity_path, 0) + chunk.num_rows
        assert not chunk.is_static
        assert "roboloom" in chunk.timeline_names
        if chunk.entity_path in (
            "/observation.state",
            "/action.follower",
            "/meta/digit_left/capture_age_ms",
        ):
            assert "roboloom" in chunk.timeline_names
            batch = chunk.to_record_batch()
            vectors.setdefault(chunk.entity_path, []).extend(
                batch.column("Scalars:scalars").to_pylist()
            )
    assert set(rows.values()) == {2}  # both draws are kept for every entity
    assert all(len(v) == dim for v in vectors["/observation.state"])
    assert all(len(v) == dim for v in vectors["/action.follower"])
    assert all(
        len(v) == 1 and v[0] >= 0 for v in vectors["/meta/digit_left/capture_age_ms"]
    )


def test_the_blueprint_grows_when_an_image_appears(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    frame = {"joint": 2.0, "observation.value": np.array(3.0)}
    monkeypatch.setattr(viewer, "observation_frame", lambda *args: frame)
    viewer.start(cfg)
    try:
        viewer.draw({}, cfg)
        frame["observation.images.depth"] = np.ones((1, 5, 6), dtype=np.uint16)
        viewer.draw({}, cfg)
        viewer.draw({}, cfg)
    finally:
        _shutdown()
    reader = _reader(cfg)
    assert len(reader.blueprints()) == 2
    chunks = {
        chunk.entity_path: chunk.to_record_batch() for chunk in reader.store().stream()
    }
    assert (
        chunks["/observation.joint"].column("Scalars:scalars").to_pylist()
        == [[2.0]] * 3
    )
    assert (
        chunks["/observation.value"].column("Scalars:scalars").to_pylist()
        == [[3.0]] * 3
    )
    assert chunks["/observation.images.depth"].column(
        "DepthImage:meter"
    ).to_pylist() == [
        [1000.0],
        [1000.0],
    ]


def test_draw_without_samples_does_not_raise(tmp_path):
    cfg = _config(tmp_path)
    viewer.start(cfg)
    try:
        viewer.draw({}, cfg)
    finally:
        _shutdown()


@pytest.mark.parametrize("missing", ["action", "invalid", "short", "state"])
def test_the_action_waits_for_every_follower(tmp_path, missing):
    cfg = _config(tmp_path)
    latest = _latest(cfg)
    if missing == "action":
        del latest[action_stream("follower")]
    elif missing == "invalid":
        latest[action_stream("follower")].payload["valid"] = False
    elif missing == "short":
        latest[action_stream("follower")].payload["positions"] = [0.0]
    else:
        del latest["follower"]  # the joined state cannot be built; the action can
    viewer.start(cfg)
    try:
        viewer.draw(latest, cfg)
    finally:
        _shutdown()
    paths = {c.entity_path for c in _reader(cfg).store().schema().component_columns()}
    assert ("/action.follower" in paths) == (missing == "state")
    assert ("/observation.state" in paths) == (missing != "state")
    assert "/observation.images.camera" in paths  # the rest is still drawn


class _Node:
    """A fake dora node: one event per next(), nothing buffered, outputs collected."""

    def __init__(self, events: list[dict]) -> None:
        self.events = iter(events)
        self.sent: list[tuple[str, Envelope]] = []
        self.clock = {"ns": 1_000_000_000}

    def next(self, timeout=None):
        self.clock["ns"] += 600_000_000  # past the status period on every event
        return next(self.events)

    def drain(self):
        return []

    def send_output(self, output: str, value: bytes) -> None:
        self.sent.append((output, Envelope.decode(value)))

    def statuses(self) -> list[Envelope]:
        return [msg for output, msg in self.sent if output == "status"]


def _quit_event() -> dict:
    quit_msg = Publisher("session").make("control", {"command": "quit"})
    return {"type": "INPUT", "id": "session", "value": quit_msg.encode()}


def test_run_survives_a_failed_start(tmp_path, monkeypatch):
    cfg = _config(tmp_path)

    def boom(cfg):
        raise RuntimeError("no display here")

    monkeypatch.setattr(viewer, "start", boom)
    node = _Node([{"type": "INPUT", "id": "tick", "value": b""}, _quit_event()])
    monkeypatch.setattr(viewer.time, "monotonic_ns", lambda: node.clock["ns"])
    viewer.run(node, cfg)  # returns on quit although the view never opened
    statuses = node.statuses()
    assert statuses
    last = statuses[-1].payload
    assert last["level"] == "error"
    assert last["fields"]["state"] == "failed"
    assert last["fields"]["drawn"] == 0
    assert last["fields"]["url"] is last["fields"]["local_url"] is None
    assert "no display here" in last["fields"]["error"]


def test_run_reports_a_failing_draw_and_goes_on(tmp_path, monkeypatch):
    cfg = _config(tmp_path)

    def boom(latest, cfg):
        raise RuntimeError("sink gone")

    monkeypatch.setattr(viewer, "draw", boom)
    node = _Node(
        [
            {"type": "INPUT", "id": "tick", "value": b""},
            {"type": "INPUT", "id": "tick", "value": b""},
            _quit_event(),
        ]
    )
    monkeypatch.setattr(viewer.time, "monotonic_ns", lambda: node.clock["ns"])
    viewer.run(node, cfg)
    last = node.statuses()[-1].payload
    assert last["level"] == "warn"
    assert last["fields"]["state"] == "viewing"
    assert last["fields"]["errors"] == 2
    assert last["fields"]["drawn"] == 0
    assert "sink gone" in last["fields"]["error"]


def test_run_reports_a_browser_failure_without_failing_start(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    url = "http://robot:9090/"
    local_url = "http://localhost:9090/"
    monkeypatch.setattr(
        viewer, "start", lambda cfg: (url, local_url, "could not open browser")
    )
    node = _Node([_quit_event()])
    monkeypatch.setattr(viewer.time, "monotonic_ns", lambda: node.clock["ns"])
    viewer.run(node, cfg)
    last = node.statuses()[-1].payload
    assert last["level"] == "warn"
    assert last["fields"]["state"] == "viewing"
    assert last["fields"]["url"] == url
    assert last["fields"]["local_url"] == local_url
    assert last["fields"]["browser_error"] == "could not open browser"


def test_run_logs_session_events(tmp_path):
    cfg = _config(tmp_path)
    start_msg = Publisher("session").make(
        "control", {"command": "start", "task": "pick"}
    )
    node = _Node(
        [
            {"type": "INPUT", "id": "session", "value": start_msg.encode()},
            _quit_event(),
        ]
    )
    viewer.run(node, cfg)  # start() and the guarded shutdown happen inside
    store = _reader(cfg).store()
    (chunk,) = (c for c in store.stream() if c.entity_path == "/session/events")
    assert not chunk.is_static and "roboloom" in chunk.timeline_names
    assert chunk.to_record_batch().column("TextLog:text").to_pylist() == [
        ["start pick"]
    ]
