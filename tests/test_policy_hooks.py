"""Hooks run locally on action periods and policy teleop, before safety limits."""

from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path

import numpy as np
import pytest
import yaml
from test_policy_interpolation import _state
from test_policy_observation import PERIOD_NS, Recorder, _controller
from test_policy_takeover import OPTIONS, _intent
from test_policy_takeover import _project as _teleop_project
from test_policy_takeover import _state as _teleop_state

from roboloom.config import load_config
from roboloom.errors import ConfigError
from roboloom.hooks import Hook, Requirements
from roboloom.hooks.config import parse_hooks
from roboloom.recording.schema import FILTERED, features, records_filtered


class Gate(Hook):
    def __init__(self, value=1234.0, observe=(), sources=("policy",), on_error=None):
        self.value, self.observe, self.sources, self.on_error = (
            value,
            observe,
            sources,
            on_error,
        )
        self.calls = []
        self.events = []
        self.writes = ()

    def requirements(self):
        return Requirements(
            observe=self.observe,
            writes=self.writes,
            sources=self.sources,
            on_error=self.on_error,
            budget_ms=50,
        )

    def step(self, action, ctx):
        self.calls.append((action.copy(), ctx))
        if self.value == "error":
            raise RuntimeError("gate broke")
        action[0] = self.value
        return action

    def on_event(self, event):
        self.events.append(event)


class Policy(Recorder):
    def __init__(self, hooks=(), horizon=4):
        super().__init__(horizon=horizon)
        self.contributions = hooks

    def hooks(self):
        return self.contributions


def setup(tmp_path, gate=None, *, claim=True, **settings):
    cfg, c = _controller(tmp_path, action_horizon=4, **settings)
    if gate is not None:
        gate.writes = (c.names[0],)
    c.policy = Policy([gate] if gate is not None else [])
    entries = [{"from": "policy", "writes": [c.names[0]]}] if gate and claim else []
    c.cfg["hooks"] = entries
    c.hook_entries = parse_hooks(entries, c.names, teleop=bool(c.teleop))
    c._bind_hooks()
    c.dataset_root = "dataset"
    c.start("task", 7)
    return cfg, c


def tick(c, k=0, mode="ACTIVE"):
    t = 1_000_000_000 + k * PERIOD_NS // c.multiplier
    pose = [2048.0] * len(c.names)
    msg = _state(t, pose, pose)
    msg.payload["mode"] = mode
    c.observe("follower", msg)
    return c.tick(t)


def test_once_per_action_period_and_chunk_context(tmp_path):
    gate = Gate()
    _, c = setup(tmp_path, gate, interpolation_multiplier=2)
    sent = [tick(c, k)["follower"] for k in range(12)]
    assert len(gate.calls) == 6 and len(c.policy.seen) == 2
    assert all(x.payload["filtered"] for x in sent)
    assert all(sent[k].payload["positions"][0] == 1234.0 for k in (1, 3, 5, 7, 9, 11))
    chunks = [ctx.chunk for _, ctx in gate.calls]
    assert [x.position for x in chunks] == [0, 1, 2, 3, 0, 1]
    assert [x.id for x in chunks] == [1, 1, 1, 1, 2, 2]
    assert all(x.length == 4 for x in chunks)
    assert gate.calls[0][1].task == "task" and gate.calls[0][1].episode_index == 7
    assert c.status()["filtered"] == 6 and c.status()["hook_ms"] >= 0
    c.shutdown()
    assert gate.events[-1].filtered_steps == 6
    assert gate.events[-1].commands == 12 and gate.events[-1].steps == 6


def test_hold_substitution_then_hooks_then_speed_limit(tmp_path):
    gate = Gate(value=5000.0)
    _, initial = _controller(tmp_path / "names")
    held = initial.names[0]
    _, c = setup(tmp_path, gate, hold=[held], max_speed={"follower": 10})
    c.policy.bad = 0  # held NaN is legal from infer; hook sees a finite value
    sent = tick(c)["follower"]
    assert gate.calls[0][0][0] == 2048.0
    assert gate.calls[0][1].hold_mask[0]
    assert sent.payload["positions"][0] == 2049.0
    c.shutdown()


@pytest.mark.parametrize(
    "mode,value,state",
    [
        ("hold", 2048.0, "running"),
        ("pass", 2058.0, "running"),
        ("fail", None, "failed"),
    ],
)
def test_hook_errors_use_existing_failure_path(tmp_path, mode, value, state):
    gate = Gate(value="error", on_error=mode)
    _, c = setup(tmp_path, gate)
    sent = tick(c)
    assert c.state == state and c.status()["hook_errors"] == 1
    if value is None:
        assert sent == {} and not c.running
    else:
        assert sent["follower"].payload["positions"][0] == value
    c.shutdown()
    assert gate.events[-1].reason == ("failed" if value is None else "shutdown")


def test_pchip_lookahead_reuses_filtered_value_without_calling_hook(
    tmp_path, monkeypatch
):
    gate = Gate()
    _, c = setup(tmp_path, gate, interpolation="pchip", interpolation_multiplier=2)
    calls = []
    real = c.interpolator.add

    def add(action, *, previous, next):
        calls.append((action.copy(), next.copy()))
        return real(action, previous=previous, next=next)

    monkeypatch.setattr(c.interpolator, "add", add)
    tick(c)
    assert len(gate.calls) == 1
    assert calls[0][0][0] == calls[0][1][0] == 1234.0
    assert calls[0][1][1] == 2068.0  # untouched lookahead remains queued
    c.shutdown()


def test_no_hooks_preserves_commands_and_schema(tmp_path):
    cfg, c = setup(tmp_path)
    assert tick(c)["follower"].payload["positions"][0] == 2058.0
    assert not records_filtered(cfg) and FILTERED not in features(cfg)
    assert "hook_ms" not in c.status()
    c.shutdown()


def test_observation_only_declared_keys_once_per_period_no_image_decoding(
    tmp_path, monkeypatch
):
    from roboloom.core.protocol import Envelope
    from roboloom.recording import schema

    gate = Gate(observe=("observation.state",))
    _, c = setup(tmp_path, gate)
    original_step = gate.step
    read = []

    def step(action, ctx):
        assert list(ctx.observation) == ["observation.state"]
        with pytest.raises(KeyError, match="observe"):
            ctx.observation["observation.images.camera"]
        read.append(ctx.observation["observation.state"])
        assert not read[-1].flags.writeable
        return original_step(action, ctx)

    gate.step = step
    frame_calls = []
    real = schema.observation_frame

    def frame(*args, **kwargs):
        frame_calls.append((set(args[0]), kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(schema, "observation_frame", frame)
    for k in range(3):
        assert tick(c, k)
    assert len(frame_calls) == 3  # infer frame reused in first period, two lazy frames
    assert all(sources == {"follower"} for sources, _ in frame_calls)
    assert len(read) == 3

    # A declared but unread image remains lazy, too.
    class Image:
        def features(self, fps):
            return {"observation.images.unread": {"dtype": "uint8", "shape": (1, 1, 3)}}

        def frame(self, msg, fps):
            raise AssertionError("unread image was decoded")

    c.sources["image"] = Image()
    c.latest["image"] = Envelope("image", "image", "boot", 0, 1, 1, {})
    gate.observe = ("observation.state", "observation.images.unread")
    c.stop()
    c._bind_hooks()
    gate.step = lambda action, ctx: ctx.observation["observation.state"] * 0 + action
    c.start("again")
    # prequeue so infer does not request the full observation (which includes image)
    c._queue(np.full((4, len(c.names)), 2058.0), 0)
    assert tick(c, 4)
    c.shutdown()

    # An image offered to infer, but undeclared by every hook, must never be built
    # while consuming an already queued chunk.
    state_gate = Gate(observe=("observation.state",))
    _, only_state = setup(tmp_path / "state-only", state_gate, observe=["camera"])
    monkeypatch.setattr(
        only_state.sources["camera"],
        "frame",
        lambda *args: pytest.fail("undeclared camera image was decoded"),
    )
    only_state.observe(
        "camera", Envelope("image", "camera", "boot", 0, 10**9, 10**9, {})
    )
    only_state._queue(np.full((4, len(only_state.names)), 2058.0), 0)
    state_step = state_gate.step

    def read_state(action, ctx):
        assert not ctx.observation["observation.state"].flags.writeable
        return state_step(action, ctx)

    state_gate.step = read_state
    frame_calls.clear()
    assert tick(only_state)
    assert len(frame_calls) == 1 and frame_calls[0][0] == {"follower"}
    assert only_state.policy.seen == []
    only_state.shutdown()


@pytest.mark.parametrize(
    "reason",
    ["stopped", "discarded", "failed", "estop", "released", "interrupted", "shutdown"],
)
def test_episode_events_fields_and_exactly_once(tmp_path, reason):
    gate = Gate()
    _, c = setup(tmp_path, gate)
    tick(c)
    if reason == "failed":
        c.fail("failure")
    elif reason == "interrupted":
        c.reset("silent")
    elif reason == "shutdown":
        c.shutdown()
    else:
        c.stop(reason)
    c.stop()
    c.shutdown()
    start, end = gate.events
    assert start.kind == "episode_started" and end.kind == "episode_ended"
    assert end.reason == reason and end.steps == end.commands == 1
    assert end.task == start.task == "task"
    assert end.episode_index == start.episode_index == 7
    assert end.dataset_root == start.dataset_root == "dataset"
    assert end.started_at == start.started_at and end.duration_s >= 0
    assert end.filtered_steps == 1


@pytest.mark.parametrize("mode", ["FAULT", "ESTOP"])
def test_latched_followers_do_not_run_hooks(tmp_path, mode):
    gate = Gate()
    _, c = setup(tmp_path, gate)
    assert tick(c, mode=mode) == {} and gate.calls == []
    c.shutdown()


def test_stale_no_pop_single_event_and_recovery_restart(tmp_path):
    gate = Gate()
    _, c = setup(tmp_path, gate)
    tick(c)
    c.max_age_ms = {"follower": 1}
    assert c.tick(2_000_000_000) == c.tick(2_000_000_001) == {}
    assert len(gate.calls) == 1
    tick(c, 2)
    c.shutdown()
    assert [e.kind for e in gate.events] == [
        "episode_started",
        "observation_stale",
        "policy_restarted",
        "episode_ended",
    ]
    assert gate.events[2].reason == "stale_recovered"


def test_teleop_source_only_and_transition_order(tmp_path):
    cfg = load_config(_teleop_project(tmp_path), options=OPTIONS)
    c = cfg.controllers["policy"]
    gate = Gate(value=2100.0, sources=("policy", "teleop"))
    gate.writes = (c.names[0],)
    entries = [{"from": "policy", "writes": list(gate.writes), "sources": ["teleop"]}]
    c.hook_entries = parse_hooks(entries, c.names, teleop=True)
    c.policy = Policy([gate])
    c._bind_hooks()
    n = len(c.names)
    c.observe("follower", _teleop_state(time.monotonic_ns(), [2048.0] * n))
    c.begin_teleop()
    # The seam is disabled before start, even though the chain is wired.
    assert c.teleop_update(
        "leader", _intent(1, None, [2048.0] * len(cfg.inputs["leader"].joint_names))
    )
    assert gate.calls == []
    c.start("task")
    c.tick()
    assert gate.calls == []
    last_policy_command = c.last_commands["follower"].copy()
    c.begin_teleop()
    sent = c.teleop_update(
        "leader", _intent(2, None, [2048.0] * len(cfg.inputs["leader"].joint_names))
    )
    assert sent["follower"].payload["filtered"]
    ctx = gate.calls[0][1]
    assert ctx.source == "teleop" and ctx.chunk is None and ctx.names == tuple(c.names)
    assert ctx.previous.tolist() == last_policy_command
    c.resume_policy()
    c.shutdown()
    assert [e.kind for e in gate.events] == [
        "episode_started",
        "control_changed",
        "control_changed",
        "policy_restarted",
        "episode_ended",
    ]
    assert [e.reason for e in gate.events[1:4]] == ["takeover", "handback", "handback"]
    assert gate.events[-1].interventions == 1 and gate.events[-1].intervention_s >= 0


def test_missing_policy_write_claim_refused_at_load(tmp_path, monkeypatch):
    _, c = _controller(tmp_path)
    gate = Gate()
    gate.writes = (c.names[0],)
    monkeypatch.setattr("roboloom.policy.load_policy", lambda *a, **k: Policy([gate]))
    with pytest.raises(ConfigError, match="- from: policy\n  writes:"):
        c.load()


def test_records_filtered_is_yaml_only(tmp_path):
    cfg, c = _controller(tmp_path)
    assert not records_filtered(cfg)
    c.cfg["hooks"] = [{"factory": "nonexistent:do_not_import", "writes": [c.names[0]]}]
    assert records_filtered(cfg)
    assert features(cfg)[FILTERED] == {"dtype": "float32", "shape": (1,), "names": None}
    c.cfg["hooks"] = [{"from": "policy", "writes": [c.names[0]]}]
    assert records_filtered(cfg)


@pytest.mark.e2e
@pytest.mark.skipif(shutil.which("dora") is None, reason="needs dora")
def test_session_launch_records_filtered_rows(tmp_path, monkeypatch):
    import pyarrow.parquet as pq

    from roboloom.runtime.session import Session

    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent.resolve()))
    _, c = _controller(tmp_path)
    # mock_project has a robot directory; get the actual node path from config
    path = next(tmp_path.rglob("nodes/policy.yaml"))
    node = yaml.safe_load(path.read_text())
    node["hooks"] = [
        {
            "factory": "policies:gate",
            "kwargs": {"joint": c.names[0]},
            "writes": [c.names[0]],
        }
    ]
    node["factory"] = "roboloom.policy:hold"
    path.write_text(yaml.safe_dump(node))
    config = path.parent.parent / "config.yaml"
    with Session.launch(
        config, options=["policy"], log_dir=tmp_path / "logs", screen=False
    ) as session:
        session.wait_ready(30)
        session.start("hooks")
        time.sleep(1)
        session.stop()
        assert session.save(wait=True).saved
        output = session.cfg.output
    files = [p for p in (tmp_path / output).rglob("*.parquet") if "data" in p.parts]
    flags = np.concatenate(
        [np.asarray(pq.read_table(p)[FILTERED].to_pylist()).ravel() for p in files]
    )
    assert flags.size and flags.max() == 1 and set(flags) <= {0, 1}


def test_filtered_rows_or_all_commands_and_safety_only_marks_sent(tmp_path):
    from test_control import command, safety
    from test_recording import action

    from roboloom.recording import EpisodeRecorder

    ctl, _ = safety()
    now = time.monotonic_ns()
    candidate = command(0, [2060], now)
    candidate.payload["filtered"] = True
    ctl.accept(candidate)
    _, sent = ctl.tick(now)
    assert sent.payload["valid"] and sent.payload["filtered"]
    _, rejected = ctl.tick(now + 1)
    assert not rejected.payload["valid"] and not rejected.payload["filtered"]
    ctl.stop()
    cfg, c = _controller(tmp_path)
    c.cfg["hooks"] = [{"from": "policy", "writes": [c.names[0]]}]
    recorder = EpisodeRecorder(cfg)
    recorder.start("task", now, write=False)
    for k, flag in enumerate((False, True, False)):
        stamp = now + (k + 1) * 1_000_000
        msg = action(k, stamp)
        msg.payload["filtered"] = flag
        recorder.ingest("action_follower", msg)
    recorder.stop(now + 200_000_000)
    row = recorder.frames()[0]
    assert row[FILTERED].dtype == np.float32 and row[FILTERED].tolist() == [1.0]


def test_hooks_on_plain_joint_controller_refused(tmp_path):
    path = _teleop_project(tmp_path)
    node = next(tmp_path.rglob("nodes/controller.yaml"))
    raw = yaml.safe_load(node.read_text())
    raw["hooks"] = []
    node.write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError, match="only policy controllers take hooks yet"):
        load_config(path, options=OPTIONS)


def test_controller_refuses_start_behind_blocked_end_and_waits_before_reset(tmp_path):
    class Slow(Gate):
        def __init__(self):
            super().__init__()
            self.entered, self.release = threading.Event(), threading.Event()

        def on_event(self, event):
            if event.kind == "episode_ended":
                self.entered.set()
                assert self.release.wait(2)
            super().on_event(event)

    gate = Slow()
    _, c = setup(tmp_path, gate)
    c.stop()
    assert gate.entered.wait(1)
    c.hooks.start_timeout_s = 0.01
    resets = c.policy.resets
    with pytest.raises(RuntimeError, match="barrier timed out"):
        c.start("refused")
    assert not c.running and c.policy.resets == resets
    gate.release.set()
    c.hooks.start_timeout_s = 1
    c.start("again")
    assert c.policy.resets == resets + 1
    c.shutdown()


def test_episode_end_waits_for_orphaned_inference(tmp_path):
    from roboloom.controllers.policy import _Inference

    gate = Gate()
    _, c = setup(tmp_path, gate)
    entered, release = threading.Event(), threading.Event()

    class Blocked(Policy):
        def infer(self, observation):
            entered.set()
            assert release.wait(2)
            return np.ones(len(c.names))

    c.job = _Inference(Blocked(), {}, 0)
    assert entered.wait(1)
    c.stop()
    assert not any(e.kind == "episode_ended" for e in gate.events)
    release.set()
    c.shutdown()
    assert gate.events[-1].kind == "episode_ended"


def test_failed_hook_bind_cannot_leave_a_startable_policy(tmp_path, monkeypatch):
    _, c = _controller(tmp_path)
    gate = Gate()
    gate.writes = (c.names[0],)
    monkeypatch.setattr("roboloom.policy.load_policy", lambda *a, **k: Policy([gate]))
    with pytest.raises(ConfigError):
        c.load()
    assert c.policy is None
    with pytest.raises(RuntimeError, match="not loaded"):
        c.start("forbidden")
