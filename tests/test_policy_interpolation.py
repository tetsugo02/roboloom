"""`interpolation_multiplier`: policy actions sent at a multiple of their rate as the
straight line between consecutive actions (LeRobot's scheme)."""

from __future__ import annotations

import numpy as np
import pytest
import yaml
from conftest import mock_project

from roboloom.config import load_config
from roboloom.control.interpolation import ActionInterpolator, auto_multiplier
from roboloom.core.protocol import Envelope

# -- the interpolator --------------------------------------------------------------


def _drain(interp: ActionInterpolator) -> list[np.ndarray]:
    out = []
    while (step := interp.get()) is not None:
        out.append(step)
    return out


def test_steps_split_the_line_between_actions():
    interp = ActionInterpolator(4)
    interp.add(np.array([0.0, 10.0]), previous=np.array([4.0, 6.0]))
    first = _drain(interp)  # after a reset: from the held pose
    assert np.allclose(first, [[3, 7], [2, 8], [1, 9], [0, 10]])
    assert interp.needs_new_action()
    interp.add(np.array([8.0, 2.0]), previous=np.array([99.0, 99.0]))  # ignored now
    assert np.allclose(_drain(interp), [[2, 8], [4, 6], [6, 4], [8, 2]])
    interp.reset()
    interp.add(np.array([1.0, 1.0]))  # no previous: the action itself, once
    assert np.allclose(_drain(interp), [[1, 1]])


def test_a_multiplier_of_one_sends_each_action():
    interp = ActionInterpolator(1)
    for value in (1.0, 5.0, -2.0):
        interp.add(np.array([value]), previous=np.array([0.0]))
        assert np.allclose(_drain(interp), [[value]])


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, "2"])
def test_the_multiplier_is_a_positive_integer(bad):
    with pytest.raises((TypeError, ValueError)):
        ActionInterpolator(bad)


def test_the_same_steps_as_lerobot():
    pytest.importorskip("torch")
    lerobot = pytest.importorskip("lerobot.utils.action_interpolator")
    import torch

    actions = np.random.default_rng(0).normal(size=(6, 3))
    ours, theirs = ActionInterpolator(5), lerobot.ActionInterpolator(multiplier=5)
    got, want = [], []
    for action in actions:
        assert ours.needs_new_action() == theirs.needs_new_action()
        ours.add(action)  # no held pose given: exactly LeRobot's behaviour
        theirs.add(torch.tensor(action))
        got += _drain(ours)
        while (step := theirs.get()) is not None:
            want.append(step.numpy())
    assert np.allclose(got, want)


# -- the policy controller ---------------------------------------------------------


def _project(tmp_path, **policy):
    project = mock_project(tmp_path / ".roboloom")
    path = project / "nodes" / "policy.yaml"
    node = yaml.safe_load(path.read_text())
    node.update(policy)
    path.write_text(yaml.safe_dump(node))
    return project / "config.yaml"


class Ramp:
    """Each infer returns a chunk moving every joint by +10 per action."""

    def __init__(self, horizon: int):
        self.horizon, self.calls = horizon, 0

    def reset(self) -> None:
        pass

    def infer(self, observation: dict) -> np.ndarray:
        self.calls += 1
        state = np.asarray(observation["observation.state"], dtype=float)
        return state[None, :] + 10.0 * np.arange(1, self.horizon + 1)[:, None]


def _state(t_ns: int, positions: list[float], target: list[float]) -> Envelope:
    payload = {"positions": positions, "target": target, "mode": "ACTIVE"}
    return Envelope("follower_state", "follower", "boot", 0, t_ns, t_ns, payload)


def test_actions_keep_their_rate_at_a_higher_command_rate(tmp_path):
    cfg = load_config(
        _project(
            tmp_path,
            rate_hz=5,
            interpolation_multiplier=20,
            action_horizon=4,
            observe=[],
        ),
        options=["policy"],
    )
    controller = cfg.controllers["policy"]
    assert controller.command_hz == 100
    policy = Ramp(4)
    controller.policy = policy
    controller.start("ramp")
    n = len(cfg.followers["follower"].joint_names)
    pose = [2048.0] * n
    period_ns = 10_000_000  # 100 Hz
    sent = []
    for k in range(160):  # 1.6 s: 8 actions
        t = 1_000_000_000 + k * period_ns
        controller.observe("follower", _state(t, pose, pose))
        command = controller.tick(t)["follower"]
        pose = list(command.payload["positions"])  # the follower reaches its target
        sent.append(pose[0])
    # one action per 20 ticks, so a chunk of 4 lasts 80 ticks: 2 infers in 160 ticks
    assert policy.calls == 2
    steps = np.diff([2048.0, *sent])
    # within a chunk every tick moves 10 / 20 counts; the second chunk starts from the
    # pose reached, so the line continues without a jump
    assert np.allclose(steps, 0.5)
    assert sent[19] == pytest.approx(2058.0) and sent[79] == pytest.approx(2088.0)


def test_steps_stay_within_max_speed(tmp_path):
    cfg = load_config(
        _project(
            tmp_path,
            rate_hz=5,
            interpolation_multiplier=10,
            action_horizon=1,
            observe=[],
            max_speed={"follower": 100},
        ),
        options=["policy"],
    )
    controller = cfg.controllers["policy"]

    class Jump(Ramp):
        def infer(self, observation):
            return np.asarray(observation["observation.state"], dtype=float) + 500

    controller.policy = Jump(1)
    controller.start("jump")
    n = len(cfg.followers["follower"].joint_names)
    pose = [2048.0] * n
    t = 1_000_000_000
    controller.observe("follower", _state(t, pose, pose))
    first = controller.tick(t)["follower"].payload["positions"][0]
    # the line wants +50 per tick (50 Hz); max_speed allows 100 counts/s * 20 ms
    assert first == pytest.approx(2048.0 + 100 * 0.02)


@pytest.mark.parametrize(
    ("rate_hz", "multiplier", "message"),
    [
        (5, 0, "auto or an integer >= 1"),
        (5, 1.5, "auto or an integer >= 1"),
        (5, "fast", "auto or an integer >= 1"),
        (7.5, 3, "whole Hz"),
        (15, 10, "exceeds the follower control_hz"),
    ],
)
def test_bad_multipliers_are_refused(tmp_path, rate_hz, multiplier, message):
    path = _project(tmp_path, rate_hz=rate_hz, interpolation_multiplier=multiplier)
    with pytest.raises(ValueError, match=message):
        load_config(path, options=["policy"])


@pytest.mark.parametrize(
    ("rate_hz", "control_hz", "expected"),
    [
        (15, 120, 8),
        (5, 120, 24),
        (7.5, 120, 16),
        (7.3, 120, 10),
        (7.33, 120, 1),
        (15, 100, 6),
        (30, 30, 1),
        (40, 30, 1),
    ],
)
def test_the_multiplier_is_computed_from_the_rates(rate_hz, control_hz, expected):
    assert auto_multiplier(rate_hz, control_hz) == expected


@pytest.mark.parametrize("given", [None, "auto"])
def test_without_a_multiplier_commands_follow_the_control_rate(tmp_path, given):
    policy = (
        {"rate_hz": 5}
        if given is None
        else {"rate_hz": 5, "interpolation_multiplier": given}
    )
    controller = load_config(
        _project(tmp_path, **policy), options=["policy"]
    ).controllers["policy"]
    assert (
        controller.multiplier == 24 and controller.command_hz == 120
    )  # control_hz 120
    assert controller.status()["interpolation"] == 24


def test_a_given_multiplier_wins(tmp_path):
    for n in (1, 6):
        cfg = load_config(
            _project(tmp_path / str(n), rate_hz=5, interpolation_multiplier=n),
            options=["policy"],
        )
        assert cfg.controllers["policy"].command_hz == 5 * n


def test_a_rate_that_is_not_whole_hz_keeps_one_action_per_command(tmp_path):
    cfg = load_config(_project(tmp_path, rate_hz=7.33), options=["policy"])
    assert cfg.controllers["policy"].multiplier == 1


def test_the_node_commands_at_the_interpolated_rate(tmp_path):
    from roboloom.runtime.flow import build_flow
    from roboloom.runtime.session import Session

    path = _project(tmp_path, rate_hz=5, interpolation_multiplier=12, observe=[])
    cfg = load_config(path, options=["policy"])
    (policy,) = [n for n in build_flow(cfg)["nodes"] if n["id"] == "policy"]
    assert policy["inputs"]["tick"] == "dora/timer/hz/60"
    with Session.launch(
        path, options=["policy"], log_dir=tmp_path / "logs", screen=False
    ) as session:
        session.wait_ready()
        result = session.record("hold", seconds=2)
        status = session.status()["policy"]["fields"]
    assert result.saved
    assert 40 <= status["command_hz"] <= 65, status
