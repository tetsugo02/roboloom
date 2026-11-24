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


def _serve(monkeypatch, policy, clients: int = 1) -> tuple[str, threading.Thread]:
    monkeypatch.setenv(R.AUTHKEY_ENV, KEY)
    address, up = _free_address(), threading.Event()
    thread = threading.Thread(
        target=R.serve,
        args=(policy, address),
        kwargs={"authkey": KEY, "clients": clients, "ready": up.set},
        daemon=True,
    )
    thread.start()
    assert up.wait(5)
    return address, thread


@pytest.fixture
def served(monkeypatch):
    policy = Echo()
    address, _ = _serve(monkeypatch, policy, clients=2)
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
    release = threading.Event()

    class Slow(Echo):
        def reset(self) -> None:
            release.wait(5)

    address, _ = _serve(monkeypatch, Slow(), clients=1)
    client = R.connect(address, timeout_s=0.1)
    with pytest.raises(TimeoutError):
        client.reset()
    release.set()


def test_an_answer_that_comes_after_its_call_timed_out_is_not_the_next_ones(
    monkeypatch,
):
    release = threading.Event()

    class NumberedSlow:
        def __init__(self) -> None:
            self.calls = 0

        def reset(self) -> None:
            pass

        def infer(self, observation: dict) -> np.ndarray:
            self.calls += 1
            number = self.calls
            if number == 1:
                release.wait(5)
            return np.asarray([[float(number)]])

    address, _ = _serve(monkeypatch, NumberedSlow(), clients=1)
    client = R.RemotePolicy(address, timeout_s=0.05)
    try:
        with pytest.raises(TimeoutError, match="no answer to infer within 0.05 s"):
            client.infer({})
        release.set()
        client.timeout_s = 10.0
        # the late answer (1) is on the connection before this call's (2)
        assert client.infer({}).tolist() == [[2.0]]
        assert client.infer({}).tolist() == [[3.0]]
    finally:
        release.set()
        client.close()


def test_a_second_policy_node_is_told_the_server_is_busy(monkeypatch):
    address, _ = _serve(monkeypatch, Echo(), clients=3)
    first = R.RemotePolicy(address, timeout_s=10)
    try:
        first.reset()
        second = R.RemotePolicy(address, timeout_s=5)  # it used to wait here for ever
        try:
            with pytest.raises(
                R.RemotePolicyError, match="serving another policy node"
            ):
                second.reset()
        finally:
            second.close()
        first.reset()  # the first one is still served
    finally:
        first.close()
    third = R.RemotePolicy(address, timeout_s=5)  # and once it left, the next one is
    try:
        third.reset()
    finally:
        third.close()


def test_a_client_from_before_calls_had_numbers_is_still_answered(monkeypatch):
    from multiprocessing.connection import Client

    address, _ = _serve(monkeypatch, Echo(), clients=1)
    host, _, port = address.rpartition(":")
    with Client((host, int(port)), authkey=KEY.encode()) as connection:
        connection.send_bytes(R.encode(["reset"]))  # the old form: no number
        assert R.decode(connection.recv_bytes()) == ["ok", None]


def test_the_server_side_needs_no_dataflow_or_learning_packages():
    code = (
        "import sys, roboloom.policy.remote\n"
        "heavy = [m for m in ('dora', 'torch', 'lerobot', 'cv2', 'textual') "
        "if m in sys.modules]\n"
        "assert not heavy, heavy\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_policy_controller_loads_remote_connect_by_reference(tmp_path, monkeypatch):
    from policies import Creep

    from roboloom.config import load_config

    address, thread = _serve(monkeypatch, Creep(step=5.0), clients=1)
    project = mock_project(tmp_path / ".roboloom")
    controller = load_config(project / "config.yaml", options=["policy"]).controllers[
        "policy"
    ]
    controller.load("roboloom.policy.remote:connect", {"address": address})
    assert controller.state == "ready"
    controller.policy.close()
    thread.join(3)


# -- backend: server ------------------------------------------------------------------

NODE = """\
type: policy
followers: [follower]
factory: policies:creep
kwargs: {step: 5.0}
backend: server
server: {address: "ADDRESS", timeout_s: 5}
observe: [camera]
rate_hz: 15
action_horizon: 1
max_speed: {follower: 1024}
command_deadline_ms: 300
"""


def test_the_node_file_says_what_the_server_loads_and_where(tmp_path):
    file = tmp_path / "policy.yaml"
    file.write_text(NODE.replace("ADDRESS", "127.0.0.1:19001"))
    factory, kwargs, server = R.served(str(file))
    assert (factory, kwargs) == ("policies:creep", {"step": 5.0})
    assert server == {"address": "127.0.0.1:19001", "timeout_s": 5}
    with pytest.raises(ConfigError, match="unknown keys adress"):
        R.server_settings({"adress": "127.0.0.1:1"})
    with pytest.raises(ConfigError, match="expected host:port"):
        R.server_settings({"address": "localhost"})
    file.write_text("factory: roboloom.policy.remote:connect\n")
    with pytest.raises(ConfigError, match="write the policy's own factory"):
        R.served(str(file))
    with pytest.raises(SystemExit, match="give one of"):
        R.main(["policies:creep", "--from", str(file)])
    with pytest.raises(SystemExit, match="give module:callable, --from"):
        R.main([])


def test_the_backend_is_the_process_unless_the_file_says_server(tmp_path):
    from roboloom.config import load_config

    project = mock_project(tmp_path / ".roboloom")
    node = project / "nodes" / "policy.yaml"
    cfg = load_config(project / "config.yaml", options=["policy"])
    assert cfg.controllers["policy"].backend == "process"
    node.write_text(node.read_text() + "backend: sever\n")
    with pytest.raises(ConfigError, match="backend must be one of process, server"):
        load_config(project / "config.yaml", options=["policy"])
    node.write_text(NODE.replace("ADDRESS", "127.0.0.1:19001"))
    controller = load_config(project / "config.yaml", options=["policy"]).controllers[
        "policy"
    ]
    assert controller.backend == "server"
    with pytest.raises(ConfigError, match="the policy server loads the policy"):
        controller.load("policies:creep")


@pytest.mark.e2e
def test_one_file_starts_the_server_and_the_node_that_connects(tmp_path, monkeypatch):
    import os
    from pathlib import Path

    from roboloom.runtime.session import Session

    monkeypatch.setenv(R.AUTHKEY_ENV, KEY)
    project = mock_project(tmp_path / ".roboloom")
    node = project / "nodes" / "policy.yaml"
    node.write_text(NODE.replace("ADDRESS", _free_address()))
    tests = str(Path(__file__).resolve().parent)
    env = {**os.environ, "PYTHONPATH": tests}
    command = [sys.executable, "-m", "roboloom.policy.remote", "--from", str(node)]
    server = subprocess.Popen(command, env=env, cwd=tmp_path)
    try:
        with Session.launch(project / "config.yaml", options=["policy"]) as s:
            s.wait_ready(30)
            s.record("creep", 1.5)
            (result,) = s.wait_saves()
            policy = s.status()["policy"]["fields"]
    finally:
        server.terminate()
        server.wait(10)
    assert result.saved and result.metrics["action_valid_rate"] > 0.5, result.metrics
    assert policy["state"] in ("ready", "running") and "infer_ms" in policy, policy


class EventPolicy(Echo):
    def __init__(self, step=False):
        super().__init__()
        from roboloom.hooks import Hook

        class Events(Hook):
            def on_episode_started(inner, event):
                self.events.append(event)

        self.events = []
        self.handler = Events()
        if step:
            self.handler.step = lambda a, ctx: a

    def hooks(self):
        return [self.handler]


@pytest.mark.parametrize("step", [False, True])
def test_hook_capabilities_events_and_step_refusal(monkeypatch, step):
    from roboloom.hooks import EpisodeStarted

    policy = EventPolicy(step)
    address, thread = _serve(monkeypatch, policy, clients=1)
    if step:
        with pytest.raises(ConfigError, match="local factory.*backend: process"):
            R.connect(address)
    else:
        client = R.connect(address)
        caps = client._call("capabilities")
        assert caps["protocol"] == 2 and caps["step_hooks"] == []
        assert "episode_started" in caps["events"]
        assert not hasattr(client.hooks()[0], "step")
        event = EpisodeStarted("task", 9, "out", 123.0)
        client.hooks()[0].on_event(event)
        assert policy.events == [event]
        assert client._call("infer", {"observation.state": np.ones(2)}) is not None
        client.close()
    thread.join(3)
    assert not thread.is_alive()


def test_old_policy_server_has_no_event_hooks(monkeypatch):
    class Old(Echo):
        pass

    original = R._answer

    def answer(policy, method, arguments, hooks=None):
        if method == "capabilities":
            raise ValueError("unknown call 'capabilities'")
        return original(policy, method, arguments, hooks)

    monkeypatch.setattr(R, "_answer", answer)
    address, thread = _serve(monkeypatch, Old(), clients=1)
    client = R.connect(address)
    assert client.hooks() == []
    assert client.infer({"observation.state": np.ones(2)}).tolist() == [2.0, 2.0]
    client.close()
    thread.join(3)


def test_remote_event_forwarding_uses_call_lock(served):
    from roboloom.hooks import EpisodeStarted

    address, _ = served
    client = R.connect(address)
    client.events = ("episode_started",)
    hook = R.RemoteEvents(client)
    entered, sent = threading.Event(), threading.Event()

    def send():
        entered.set()
        try:
            hook.on_event(EpisodeStarted("task", None, None, 1.0))
        finally:
            sent.set()

    with client.lock:
        thread = threading.Thread(target=send, daemon=True)
        thread.start()
        assert entered.wait(1) and not sent.wait(0.01)
    assert sent.wait(2)
    thread.join()
    client.close()
