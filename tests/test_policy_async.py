"""`inference: async`: the policy infers on a worker thread while the node keeps sending
the queued actions."""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest
from test_policy_interpolation import _state
from test_policy_observation import PERIOD_NS, _controller


class Gated:
    """Each infer waits for `go`, then returns [H, n] with value 100 * call + step."""

    def __init__(self, horizon: int = 4, fail: bool = False):
        self.horizon, self.fail = horizon, fail
        self.go = threading.Event()
        self.calls = 0
        self.inside = 0
        self.overlap = False
        self.resets = 0

    def reset(self) -> None:
        self.overlap |= self.inside > 0
        self.resets += 1

    def infer(self, observation: dict) -> np.ndarray:
        self.inside += 1
        self.calls += 1
        call = self.calls
        self.go.wait(5)
        self.inside -= 1
        if self.fail:
            raise ValueError("model broke")
        n = len(observation["observation.state"])
        steps = 100.0 * call + np.arange(self.horizon)
        return np.repeat(steps[:, None], n, axis=1)


def _async(tmp_path, policy, **settings):
    _, controller = _controller(
        tmp_path, inference="async", action_horizon=policy.horizon, **settings
    )
    controller.policy = policy
    controller.start("task")
    return controller


class Loop:
    def __init__(self, controller):
        self.controller, self.k = controller, 0
        self.pose = [2048.0] * len(controller.names)

    def tick(self) -> float | None:
        """One action period; the first joint's target, or None when nothing was sent."""
        t = 1_000_000_000 + self.k * PERIOD_NS
        self.k += 1
        self.controller.observe("follower", _state(t, self.pose, self.pose))
        sent = self.controller.tick(t)
        if not sent:
            return None
        self.pose = list(sent["follower"].payload["positions"])
        return self.pose[0]

    def until_done(self) -> None:
        job = self.controller.job
        assert job is not None and job.done.wait(5)


def test_queued_actions_go_on_while_the_next_chunk_is_computed(tmp_path):
    policy = Gated(horizon=4)
    loop = Loop(_async(tmp_path, policy))
    controller = loop.controller
    assert controller.replan_at == 2 and controller.status()["inference"] == "async"
    assert loop.tick() is None  # the first chunk is not there yet
    assert controller.status()["state"] == "waiting_inference"
    policy.go.set()
    loop.until_done()
    policy.go.clear()
    assert [loop.tick(), loop.tick()] == [100.0, 101.0]  # 2 left: the next one starts
    assert loop.tick() == 102.0 and policy.calls == 2  # sent while infer runs
    assert loop.tick() == 103.0
    policy.go.set()
    loop.until_done()
    policy.go.clear()
    # two actions went out since the observation of the second chunk: it starts at its
    # third action, so every action keeps its place in time
    assert loop.tick() == 202.0 and loop.tick() == 203.0
    assert controller.status()["dropped"] == 2
    assert "infer_ms" in controller.status()


def test_a_late_chunk_holds_the_followers(tmp_path):
    policy = Gated(horizon=2)
    loop = Loop(_async(tmp_path, policy))
    loop.tick()
    policy.go.set()
    loop.until_done()
    policy.go.clear()
    assert [loop.tick(), loop.tick()] == [100.0, 101.0]
    assert loop.tick() is None  # the queue ran out: nothing sent, the followers hold
    assert loop.controller.status()["state"] == "late_inference"
    policy.go.set()
    loop.until_done()
    assert loop.tick() == 201.0  # one action was executed since its observation


def test_a_result_from_before_a_restart_is_not_used(tmp_path):
    policy = Gated(horizon=4)
    loop = Loop(_async(tmp_path, policy))
    loop.tick()  # inference 1 running
    loop.controller.stop()
    policy.go.set()  # reset waits for it instead of overlapping
    loop.controller.start("task")
    assert not policy.overlap and policy.inside == 0
    assert loop.controller.job is None and not loop.controller.queue
    policy.go.clear()
    assert (
        loop.tick() is None and policy.calls == 2
    )  # a new inference, not the old chunk
    policy.go.set()
    loop.until_done()
    assert loop.tick() == 200.0


def test_a_failing_inference_fails_the_episode(tmp_path):
    policy = Gated(horizon=2, fail=True)
    loop = Loop(_async(tmp_path, policy))
    loop.tick()
    policy.go.set()
    loop.until_done()
    with pytest.raises(ValueError, match="model broke"):
        loop.tick()


def test_the_history_is_sampled_once_per_action_while_waiting(tmp_path):
    seen = []

    class Looking(Gated):
        def infer(self, observation):
            seen.append(observation["history"]["observation.state"][:, 0].copy())
            return super().infer(observation)

    policy = Looking(horizon=4)
    loop = Loop(_async(tmp_path, policy, observation_history=3))
    for _ in range(3):  # waiting for the first chunk: no extra frames
        assert loop.tick() is None
    policy.go.set()
    loop.until_done()
    for _ in range(3):
        loop.tick()
    loop.until_done()
    assert np.allclose(seen[0], 2048.0)
    assert np.allclose(seen[1], [2048.0, 100.0, 101.0])  # one frame per action


@pytest.mark.parametrize(
    ("settings", "message"),
    [({"inference": "thread"}, "sync or async"), ({"replan_at": -1}, "replan_at")],
)
def test_bad_async_settings_are_refused(tmp_path, settings, message):
    with pytest.raises(ValueError, match=message):
        _controller(tmp_path, **settings)


def test_a_slow_policy_leaves_no_gap_in_the_commands(tmp_path, monkeypatch):
    import os
    from pathlib import Path

    import yaml
    from conftest import mock_project

    from roboloom.runtime.session import Session

    project = mock_project(tmp_path / ".roboloom")
    node = project / "nodes" / "policy.yaml"
    settings = yaml.safe_load(node.read_text())
    settings.update(inference="async", action_horizon=8, observe=[])
    node.write_text(yaml.safe_dump(settings))
    monkeypatch.setenv(
        "PYTHONPATH",
        os.pathsep.join([str(Path(__file__).parent), os.environ.get("PYTHONPATH", "")]),
    )
    rates = []
    with Session.launch(
        project / "config.yaml",
        options=["policy"],
        policy="test_policy_async:slow",
        log_dir=tmp_path / "logs",
    ) as s:
        s.wait_ready(30)
        result = s.record(
            "slow",
            3.0,
            on_tick=lambda status: rates.append(
                status.get("policy", {}).get("fields", {}).get("command_hz", 0)
            ),
        )
        fields = s.status()["policy"]["fields"]
    assert result.saved and fields.get("inference") == "async", fields
    # 0.2 s per inference (3 actions at 15 Hz) would stop the commands when synchronous
    assert result.metrics["action_valid_rate"] > 0.8, result.metrics
    assert max(rates) > 100, rates


class Slow:
    def reset(self) -> None:
        pass

    def infer(self, observation: dict) -> np.ndarray:
        time.sleep(0.2)
        state = np.asarray(observation["observation.state"], dtype=float)
        return np.repeat(state[None, :], 8, axis=0)


def slow() -> Slow:
    return Slow()
