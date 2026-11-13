"""A policy served from another process (`roboloom.policy.remote`)."""

from __future__ import annotations

import socket
import subprocess
import sys
import threading

import numpy as np
import pytest
from conftest import mock_project

from roboloom.errors import ConfigError
from roboloom.policy import PolicySpec
from roboloom.policy import remote as R

KEY = "test-secret"


def _free_address() -> str:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return f"127.0.0.1:{s.getsockname()[1]}"


class Echo:
    """Keeps what it was given; adds 1 to the state."""

    def __init__(self) -> None:
        self.spec: PolicySpec | None = None
        self.resets = 0
        self.seen: list[dict] = []

    def options(self) -> dict:
        return {"observation_history": 2, "hold": ["a.j1"]}

    def bind(self, spec: PolicySpec) -> None:
        self.spec = spec

    def reset(self) -> None:
        self.resets += 1

    def infer(self, observation: dict) -> np.ndarray:
        if observation.get("task") == "fail":
            raise ValueError("no such task")
        self.seen.append(observation)
        return np.asarray(observation["observation.state"], dtype=np.float64) + 1


@pytest.fixture
def served(monkeypatch):
    monkeypatch.setenv(R.AUTHKEY_ENV, KEY)
    address, policy, up = _free_address(), Echo(), threading.Event()
    thread = threading.Thread(
        target=R.serve,
        args=(policy, address),
        kwargs={"authkey": KEY, "clients": 2, "ready": up.set},
        daemon=True,
    )
    thread.start()
    assert up.wait(5)
    return address, policy


def test_messages_keep_arrays_and_plain_values():
    message = {
        "image": np.arange(24, dtype=np.uint8).reshape(2, 4, 3),
        "state": np.asarray([1.5, -2.0], dtype=np.float32),
        "nested": {"history": [np.zeros((0, 3)), np.int64(7)], "task": "pick"},
        "none": None,
        "flag": True,
    }
    back = R.decode(R.encode(message))
    assert back["image"].dtype == np.uint8 and back["image"].shape == (2, 4, 3)
    assert np.array_equal(back["image"], message["image"])
    assert back["state"].dtype == np.float32
    assert back["nested"]["history"][0].shape == (0, 3)
    assert back["nested"]["history"][1] == 7 and back["nested"]["task"] == "pick"
    assert back["none"] is None and back["flag"] is True
    with pytest.raises(TypeError):
        R.encode({"bad": object()})


def test_calls_reach_the_served_policy(served):
    address, policy = served
    client = R.connect(address)
    assert client.options() == {"observation_history": 2, "hold": ["a.j1"]}
    spec = PolicySpec(
        observation={"observation.state": {"dtype": "float32", "shape": (2,)}},
        action=("a.j1", "a.j2"),
        rate_hz=5.0,
        dataset_fps=15.0,
        history=2,
        hold=("a.j1",),
        units=("rad", "rad"),
    )
    client.bind(spec)
    assert policy.spec is not None
    assert policy.spec.action == ("a.j1", "a.j2") and policy.spec.history == 2
    assert policy.spec.hold == ("a.j1",) and policy.spec.units == ("rad", "rad")
    client.reset()
    assert policy.resets == 1
    observation = {
        "observation.state": np.asarray([1.0, 2.0], dtype=np.float32),
        "observation.images.camera": np.full((4, 6, 3), 9, dtype=np.uint8),
        "history": {"action": np.ones((2, 2), dtype=np.float32)},
        "task": "pick",
    }
    out = client.infer(observation)
    assert out.dtype == np.float64 and np.allclose(out, [2.0, 3.0])
    got = policy.seen[0]
    assert got["observation.images.camera"].dtype == np.uint8
    assert got["history"]["action"].shape == (2, 2) and got["task"] == "pick"
    client.close()


def test_an_error_of_the_policy_is_raised_at_the_caller(served):
    address, policy = served
    client = R.connect(address)
    with pytest.raises(R.RemotePolicyError, match="ValueError: no such task"):
        client.infer({"observation.state": np.zeros(2), "task": "fail"})
    assert np.allclose(client.infer({"observation.state": np.zeros(2)}), 1.0)
    client.close()
    again = R.connect(address)  # the server waits for the next policy node
    again.reset()
    assert policy.resets == 1
    again.close()


def test_the_key_is_required_and_checked(served, monkeypatch):
    address, _ = served
    monkeypatch.setenv(R.AUTHKEY_ENV, "wrong")
    with pytest.raises(Exception, match="digest|authentic|challenge"):
        R.connect(address)
    monkeypatch.delenv(R.AUTHKEY_ENV)
    with pytest.raises(ConfigError, match=R.AUTHKEY_ENV):
        R.connect(address)


def test_no_server_is_reported(monkeypatch):
    monkeypatch.setenv(R.AUTHKEY_ENV, KEY)
    with pytest.raises(ConfigError, match="no server"):
        R.connect(_free_address(), connect_timeout_s=0.3)


def test_a_slow_answer_times_out(monkeypatch):
    monkeypatch.setenv(R.AUTHKEY_ENV, KEY)
    address, up, release = _free_address(), threading.Event(), threading.Event()

    class Slow(Echo):
        def reset(self) -> None:
            release.wait(5)

    threading.Thread(
        target=R.serve,
        args=(Slow(), address),
        kwargs={"authkey": KEY, "clients": 1, "ready": up.set},
        daemon=True,
    ).start()
    assert up.wait(5)
    client = R.connect(address, timeout_s=0.2)
    with pytest.raises(TimeoutError):
        client.reset()
    release.set()


def test_the_server_side_needs_no_dataflow_or_learning_packages():
    code = (
        "import sys, roboloom.policy.remote\n"
        "heavy = [m for m in ('dora', 'torch', 'lerobot', 'cv2', 'textual') "
        "if m in sys.modules]\n"
        "assert not heavy, heavy\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_a_served_policy_drives_the_mock_robot(tmp_path, monkeypatch):
    from policies import Creep

    from roboloom.runtime.session import Session

    monkeypatch.setenv(R.AUTHKEY_ENV, KEY)
    address, up = _free_address(), threading.Event()
    threading.Thread(
        target=R.serve,
        args=(Creep(step=5.0), address),
        kwargs={"authkey": KEY, "clients": 1, "ready": up.set},
        daemon=True,
    ).start()
    assert up.wait(5)
    project = mock_project(tmp_path / ".roboloom")
    with Session.launch(
        project / "config.yaml",
        options=["policy"],
        policy="roboloom.policy.remote:connect",
        policy_kwargs={"address": address},
    ) as s:
        s.wait_ready(30)
        result = s.record("creep", 1.5)
        policy = s.status()["policy"]["fields"]
    assert result.saved and result.metrics["action_valid_rate"] > 0.5, result.metrics
    assert policy["state"] in ("ready", "running") and "infer_ms" in policy, policy
