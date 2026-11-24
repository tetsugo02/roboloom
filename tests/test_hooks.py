"""Hook declarations, write enforcement and ordered per-hook event workers."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict

import numpy as np
import pytest

from roboloom.errors import ConfigError
from roboloom.hooks import (
    HOOKS_API,
    ControlChanged,
    EpisodeEnded,
    EpisodeStarted,
    Hook,
    HookChain,
    HookError,
    HookSpec,
    Requirements,
    StepContext,
)
from roboloom.hooks.config import build_hooks, parse_hooks

NAMES = ("a.arm", "b.grip")
SPEC = HookSpec(
    NAMES,
    ("rad", "m"),
    ("b.grip",),
    {"observation.state": {}},
    10,
    100,
    30,
    ("policy", "teleop"),
)


class Change:
    def __init__(self, req=None, function=None):
        self.req, self.function = (
            req if req is not None else Requirements(writes=("b.grip",)),
            function,
        )
        self.contexts = []

    def requirements(self):
        return self.req

    def step(self, action, ctx):
        self.contexts.append(ctx)
        if self.function is not None:
            return self.function(action, ctx)
        action[ctx.index("b.grip")] += 2
        return action


def context(source="policy"):
    return StepContext(
        source,
        0,
        100,
        10,
        "task",
        3,
        NAMES,
        _held=lambda: np.array([10.0, 20.0]),
        _previous=lambda: np.array([9.0, 19.0]),
        _state=lambda: np.array([8.0, 18.0]),
        _hold=("b.grip",),
        _observation=lambda: {"observation.state": np.ones(2), "secret": np.zeros(1)},
    )


def chain(hooks, entries=None, **kwargs):
    entries = (
        entries if entries is not None else [{"from": "policy", "writes": list(NAMES)}]
    )
    return HookChain(
        build_hooks(parse_hooks(entries, NAMES, teleop=True), hooks, SPEC), **kwargs
    )


def test_order_overlap_and_held_entries_are_writable(caplog):
    first, second = Change(), Change(function=lambda a, ctx: a * [1, 3])
    c = chain([first, second])
    assert c.run(np.array([1.0, 2.0]), context()).tolist() == [1.0, 12.0]
    ctx = first.contexts[0]
    assert ctx.held.tolist() == [10, 20] and ctx.previous.tolist() == [9, 19]
    assert ctx.state.tolist() == [8, 18]
    assert ctx.hold_mask.tolist() == [False, True]
    assert ctx.writable_mask.tolist() == [False, True]
    assert not ctx.held.flags.writeable
    assert "overlap" in caplog.text
    assert c.filtered == 1 and all(e.stats.changed == 1 for e in c.entries)
    c.close()


@pytest.mark.parametrize(
    "mode,expected", [("hold", [1.0, 20.0]), ("pass", [1.0, 2.0]), ("fail", None)]
)
@pytest.mark.parametrize(
    "failure", ["raise", "shape", "finite", "outside", "signed_zero"]
)
def test_on_error_and_bit_identical_writes(mode, expected, failure):
    def broken(action, ctx):
        if failure == "raise":
            raise RuntimeError("broken")
        if failure == "shape":
            return action[:1]
        if failure == "finite":
            action[1] = np.nan
        if failure == "outside":
            action[0] += 1
        if failure == "signed_zero":
            action[0] = -0.0
        return action

    c = chain([Change(Requirements(writes=("b.grip",), on_error=mode), broken)])
    action = np.array([0.0 if failure == "signed_zero" else 1.0, 2.0])
    if expected is None:
        with pytest.raises(HookError):
            c.run(action, context())
    else:
        expected[0] = action[0]
        assert c.run(action, context()).tolist() == expected
    assert c.status()["hook_errors"] == 1
    c.close()


def test_defaults_and_none_mean_unchanged():
    c = chain([Change(Requirements(), lambda a, ctx: None)], entries=[])
    assert c.entries[0].bound.requirements.on_error == "pass"
    assert np.array_equal(c.run(np.array([1.0, 2.0]), context()), [1, 2])
    assert c.filtered == 0
    c.close()


def test_observation_is_restricted_lazy_and_read_only():
    called = []

    def read(action, ctx):
        assert list(ctx.observation) == ["observation.state"]
        with pytest.raises(KeyError, match="observe"):
            ctx.observation["secret"]
        with pytest.raises(ValueError):
            ctx.observation["observation.state"][0] = 7
        ctx.note(open=False, probability=0.3)

    h = Change(Requirements(observe=("observation.state",)), read)
    c = chain([h], [])
    ctx = context()
    ctx._observation = lambda: called.append(True) or {"observation.state": np.ones(2)}
    assert not called
    c.run(np.ones(2), ctx)
    assert called == [True] and c.entries[0].stats.notes["probability"] == 0.3
    with pytest.raises(ValueError, match="scalar"):
        h.contexts[0].note(large="x" * 257)
    c.close()


@pytest.mark.parametrize(
    ("entry", "match"),
    [
        ({"factory": "m:f", "from": "policy"}, None),
        ({}, None),
        ({"from": "other"}, None),
        ({"factory": "missing"}, None),
        ({"factory": "m:f", "writes": ["a.unknown"]}, None),
        ({"factory": "m:f", "writes": ["a.arm", "a.arm"]}, None),
        ({"factory": "m:f", "sources": ["other"]}, None),
        ({"factory": "m:f", "on_error": "fallback"}, None),
        ({"factory": "m:f", "on_overrun": "fail"}, None),
        ({"from": "policy", "kwargs": {}}, None),
        ({"factory": "m:f", "kwargs": []}, None),
        ({"factory": "m:f", "name": 4}, None),
        ({"factory": "m:f", "budget_ms": 0}, "positive"),
        ({"factory": "m:f", "budget_ms": -1}, "positive"),
        ({"factory": "m:f", "budget_ms": float("inf")}, "positive"),
        ({"factory": "m:f", "budget_ms": float("nan")}, "positive"),
        ({"factory": "m:f", "budget_ms": True}, "positive"),
        ({"factory": "m:f", "budget_ms": "1"}, "positive"),
    ],
)
def test_invalid_yaml(entry, match):
    with pytest.raises(ConfigError, match=match):
        parse_hooks([entry], NAMES)


def test_policy_claim_and_new_api_refused():
    with pytest.raises(ConfigError, match="exceed YAML"):
        chain([Change()], [{"from": "policy"}])
    with pytest.raises(ConfigError, match="API"):
        chain([Change(Requirements(api=HOOKS_API + 1))], [])
    with pytest.raises(ConfigError, match="at most once"):
        parse_hooks([{"from": "policy"}, {"from": "policy"}], NAMES)
    with pytest.raises(ConfigError, match="backend: process"):
        parse_hooks([{"from": "policy", "writes": ["b.grip"]}], NAMES, backend="server")
    with pytest.raises(ConfigError, match="requires teleop"):
        parse_hooks([{"factory": "m:f", "sources": ["teleop"]}], NAMES)


def test_narrowed_sources_and_budget(caplog):
    c = chain(
        [Change(Requirements(writes=("b.grip",), sources=("policy", "teleop")))],
        [
            {
                "from": "policy",
                "writes": ["b.grip"],
                "sources": ["teleop"],
                "budget_ms": 1e-12,
            }
        ],
    )
    assert c.run(np.ones(2), context()).tolist() == [1.0, 1.0]
    assert c.run(np.ones(2), context("teleop")).tolist() == [1.0, 3.0]
    assert c.entries[0].stats.over == 1 and "over budget" in caplog.text
    c.close()
    # A fast hook must not count as over budget by default (0.5 / rate_hz s).
    caplog.clear()
    default_c = chain(
        [Change(Requirements(writes=("b.grip",), sources=("teleop",)))],
        [{"from": "policy", "writes": ["b.grip"]}],
    )
    default_c.run(np.ones(2), context("teleop"))
    assert default_c.entries[0].stats.over == 0 and "over budget" not in caplog.text
    default_c.close()


class Events(Hook):
    def __init__(self):
        self.seen = []
        self.block = threading.Event()
        self.entered = threading.Event()
        self.closed = False

    def requirements(self):
        return Requirements(on_error="pass", budget_ms=50)

    def on_episode_ended(self, event):
        self.entered.set()
        assert self.block.wait(2)
        self.seen.append(event.kind)

    def on_episode_started(self, event):
        self.seen.append(event.kind)

    def step(self, action, ctx):
        return None

    def close(self):
        self.closed = True


def ended():
    return EpisodeEnded("task", "stopped", "", 0, "out", 1, 4, 0, 0.0, 1, 1.0, 2.0)


def test_start_barrier_sits_behind_end_and_refuses_blocked_start():
    h = Events()
    c = chain([h], [], start_timeout_s=0.01)
    c.emit(ended())
    assert h.entered.wait(1)
    with pytest.raises(HookError, match="barrier timed out"):
        c.emit(EpisodeStarted("next", 1, "out", 3.0))
    h.block.set()
    c.emit(EpisodeStarted("retry", 1, "out", 4.0))
    assert h.seen == ["episode_ended", "episode_started", "episode_started"]
    assert c.close() and h.closed


def test_event_only_hook_never_blocks_and_close_drains():
    class EventOnly(Events):
        step = None

    h = EventOnly()
    c = chain([h], [], start_timeout_s=0.001)
    c.emit(ended())
    assert h.entered.wait(1)
    c.emit(EpisodeStarted("next", 1, None, 3.0))
    assert h.seen == []
    assert not c.close(timeout=0.001)
    assert not h.closed
    h.block.set()
    c.entries[0].thread.join(1)
    assert h.closed and h.seen == ["episode_ended", "episode_started"]


def test_no_concurrent_methods_and_barrier_timeout_uses_on_error():
    h = Events()
    h.requirements = lambda: Requirements(
        writes=("b.grip",), on_error="hold", budget_ms=0.001
    )
    c = chain([h])
    c.emit(ended())
    assert h.entered.wait(1)
    c.emit(ControlChanged("policy", "teleop", "takeover"))
    assert c.run(np.ones(2), context()).tolist() == [1.0, 20.0]
    assert c.entries[0].stats.errors == 1
    h.block.set()
    c.close()


def test_event_errors_logged_and_settle_precedes_end(caplog):
    order = []

    class Bad(Hook):
        def on_episode_ended(self, event):
            order.append("end")
            raise RuntimeError("event broke")

    c = chain([Bad()], [])
    c.emit(ended(), settle=lambda: order.append("settle"))
    c.close()
    assert order == ["settle", "end"] and "event broke" in caplog.text
    assert json.loads(json.dumps(asdict(ended())))["kind"] == "episode_ended"


def test_policy_slot_order_and_factory_claim(monkeypatch):
    first, policy, last = Change(), Change(), Change()
    factories = {"local:first": lambda: first, "local:last": lambda: last}
    monkeypatch.setattr(
        "roboloom.hooks.config.load_reference", lambda ref, *args: factories[ref]
    )
    entries = [
        {"factory": "local:first", "writes": ["b.grip"]},
        {"from": "policy", "writes": ["b.grip"]},
        {"factory": "local:last", "writes": ["b.grip"]},
    ]
    c = chain([policy], entries)
    assert [e.bound.hook for e in c.entries] == [first, policy, last]
    c.close()
    with pytest.raises(ConfigError, match="exceed YAML"):
        chain([], [{"factory": "local:first"}])


def test_source_declaration_can_be_narrowed_to_node_offer():
    hook = Change(Requirements(sources=("policy", "teleop")), lambda a, c: None)
    spec = HookSpec(NAMES, ("rad", "m"), (), {}, 10, 10, 30, ("policy",))
    bound = build_hooks(
        parse_hooks([{"from": "policy", "sources": ["policy"]}], NAMES), [hook], spec
    )
    assert bound[0].requirements.sources == ("policy",)


def test_bind_spec_and_unknown_observations_refuse():
    class Bound(Change):
        def bind(self, spec):
            assert spec is SPEC and spec.api == HOOKS_API
            raise ConfigError("model mismatch")

    with pytest.raises(ConfigError, match="model mismatch"):
        chain([Bound()])
    with pytest.raises(ConfigError, match="observe"):
        chain([Change(Requirements(observe=("observation.images.undeclared",)))], [])


def test_missing_claim_lists_union_of_policy_writes():
    hooks = [Change(Requirements(writes=("a.arm",))), Change()]
    with pytest.raises(
        ConfigError, match=r"- from: policy\n  writes: \[a.arm, b.grip\]"
    ):
        chain(hooks, [])


def test_failed_factory_closes_already_created_hooks_without_masking_error(
    monkeypatch, caplog
):
    closed = []

    class Resource(Change):
        def close(self):
            closed.append(True)
            raise RuntimeError("close broke")

    def factory(ref, *args):
        if ref == "local:bad":
            raise ConfigError("factory broke")
        return Resource

    monkeypatch.setattr("roboloom.hooks.config.load_reference", factory)
    with pytest.raises(ConfigError, match="factory broke"):
        chain(
            [],
            [
                {"factory": "local:resource", "writes": ["b.grip"]},
                {"factory": "local:bad"},
            ],
        )
    assert closed == [True] and "close broke" in caplog.text
