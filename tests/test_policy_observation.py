"""What a policy is given besides the latest frame: the observation history, the joints
it leaves alone (`hold`) and fresh sensor samples only."""

from __future__ import annotations

import numpy as np
import pytest
from test_policy_interpolation import _project, _state

from roboloom.config import load_config
from roboloom.core.protocol import Envelope

PERIOD_NS = 100_000_000  # rate_hz 10, one command per action


class Recorder:
    """Returns the state plus `step` on every joint; keeps what it was given."""

    def __init__(self, horizon: int = 1, step: float = 10.0, bad: int | None = None):
        self.horizon, self.step, self.bad = horizon, step, bad
        self.seen: list[dict] = []
        self.resets = 0

    def reset(self) -> None:
        self.resets += 1

    def infer(self, observation: dict) -> np.ndarray:
        self.seen.append(observation)
        state = np.asarray(observation["observation.state"], dtype=float)
        chunk = state[None, :] + self.step * np.arange(1, self.horizon + 1)[:, None]
        if self.bad is not None:
            chunk[:, self.bad] = np.nan
        return chunk


def _controller(tmp_path, **policy):
    settings = {
        "rate_hz": 10,
        "interpolation_multiplier": 1,
        "action_horizon": 1,
        "observe": [],
        "max_speed": {"follower": 1e6},
        **policy,
    }
    cfg = load_config(_project(tmp_path, **settings), options=["policy"])
    return cfg, cfg.controllers["policy"]


def _run(controller, ticks: int, start: float = 2048.0) -> list[list[float]]:
    """The follower reaches every target; returns the targets sent."""
    n = len(controller.names)
    pose = [start] * n
    sent = []
    for k in range(ticks):
        t = 1_000_000_000 + k * PERIOD_NS
        controller.observe("follower", _state(t, pose, pose))
        pose = list(controller.tick(t)["follower"].payload["positions"])
        sent.append(pose)
    return sent


def test_without_history_the_observation_is_as_before(tmp_path):
    _, controller = _controller(tmp_path)
    controller.policy = policy = Recorder()
    controller.start("task")
    _run(controller, 3)
    assert all("history" not in seen for seen in policy.seen)
    assert controller.spec().history == 1 and controller.spec().hold == ()
    assert controller.spec().units == ("dynamixel_count",) * 17


def test_the_history_holds_the_last_frames_oldest_first(tmp_path):
    _, controller = _controller(tmp_path, observation_history=3)
    controller.policy = policy = Recorder()
    controller.start("task")
    sent = _run(controller, 4)
    first = policy.seen[0]["history"]
    # the first frame fills the history; no action yet, so the held target stands in
    assert first["observation.state"].shape == (3, 17)
    assert np.allclose(first["observation.state"], 2048.0)
    assert np.allclose(first["action"], 2048.0) and first["action"].dtype == np.float32
    last = policy.seen[3]["history"]
    assert np.allclose(last["observation.state"][:, 0], [2058.0, 2068.0, 2078.0])
    # the current frame is the last one; its action is what was executed before it
    assert np.allclose(
        last["observation.state"][-1], policy.seen[3]["observation.state"]
    )
    assert np.allclose(last["action"][:, 0], [2058.0, 2068.0, 2078.0])
    assert sent[3][0] == pytest.approx(2088.0)
    assert controller.spec().history == 3


def test_the_history_is_sampled_once_per_action(tmp_path):
    _, controller = _controller(
        tmp_path, observation_history=2, action_horizon=2, interpolation_multiplier=4
    )
    controller.policy = policy = Recorder(horizon=2)
    controller.start("task")
    n = len(controller.names)
    pose = [2048.0] * n
    for k in range(16):  # 4 actions of 4 commands each: 2 inferences
        t = 1_000_000_000 + k * 25_000_000
        controller.observe("follower", _state(t, pose, pose))
        pose = list(controller.tick(t)["follower"].payload["positions"])
    assert len(policy.seen) == 2
    # frames one action apart (the action in between was not inferred, yet sampled)
    states = policy.seen[1]["history"]["observation.state"][:, 0]
    assert np.allclose(states, [2058.0, 2068.0])


def test_a_new_episode_starts_with_an_empty_history(tmp_path):
    _, controller = _controller(tmp_path, observation_history=2)
    controller.policy = policy = Recorder()
    controller.start("task")
    _run(controller, 3)
    controller.stop()
    controller.start("task")
    _run(controller, 1, start=1000.0)
    assert np.allclose(policy.seen[-1]["history"]["observation.state"], 1000.0)
    assert np.allclose(policy.seen[-1]["history"]["action"], 1000.0)


def test_held_joints_keep_their_target_whatever_the_policy_returns(tmp_path):
    hold = ["follower.torso_yaw", "follower.head_pitch"]
    _, controller = _controller(tmp_path, hold=hold)
    controller.policy = Recorder(bad=0)  # NaN where the policy does not drive
    controller.start("task")
    sent = _run(controller, 3)
    assert [row[0] for row in sent] == [2048.0] * 3  # torso_yaw held
    assert [row[2] for row in sent] == [2048.0] * 3  # head_pitch held, though finite
    assert sent[2][1] == pytest.approx(2078.0)
    assert controller.spec().hold == tuple(hold)


def test_a_non_finite_target_outside_hold_fails(tmp_path):
    _, controller = _controller(tmp_path, hold=["follower.torso_yaw"])
    controller.policy = Recorder(bad=1)
    controller.start("task")
    with pytest.raises(ValueError, match="non-finite"):
        _run(controller, 1)


@pytest.mark.parametrize(
    ("policy", "message"),
    [
        ({"hold": ["follower.elbow"]}, "hold"),
        ({"hold": "follower.torso_yaw"}, "hold must be a list"),
        ({"observation_history": 0}, "observation_history"),
        ({"observation_history": 1.5}, "observation_history"),
    ],
)
def test_bad_history_and_hold_are_refused(tmp_path, policy, message):
    with pytest.raises(ValueError, match=message):
        _controller(tmp_path, **policy)


class Declaring(Recorder):
    def options(self) -> dict:
        return {
            "observation_history": 4,
            "hold": ["follower.head_yaw"],
            "action_horizon": 3,
        }


def declaring() -> Declaring:
    return Declaring(horizon=3)


def test_a_policy_states_what_it_needs(tmp_path):
    _, controller = _controller(tmp_path)
    controller.load("test_policy_observation:declaring", {})
    spec = controller.spec()
    assert spec.history == 4 and spec.hold == ("follower.head_yaw",)
    assert controller.horizon == 3
    controller.start("task")
    _run(controller, 1)
    assert controller.policy.seen[0]["history"]["observation.state"].shape == (4, 17)


def test_unknown_policy_options_are_refused(tmp_path):
    _, controller = _controller(tmp_path)

    class Odd(Recorder):
        def options(self):
            return {"rate_hz": 5}

    import test_policy_observation as module

    module.odd = lambda: Odd()  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match=r"options\(\)"):
        controller.load("test_policy_observation:odd", {})


def _image(cfg, t_ns: int) -> Envelope:
    camera = cfg.sensors["camera"]
    frame = camera.open(True, cfg.dataset_fps).read()
    assert frame is not None
    return Envelope("image", "camera", "boot", 0, t_ns, t_ns, camera.encode(frame))


def test_a_stale_sensor_stops_the_policy_until_it_is_fresh_again(tmp_path):
    cfg, controller = _controller(tmp_path, observe=["camera"])
    assert controller.max_age_ms == {"camera": 200}
    controller.policy = policy = Recorder()
    controller.start("task")
    pose = [2048.0] * 17
    t0 = 1_000_000_000

    def tick(k: int) -> dict:
        t = t0 + k * PERIOD_NS
        controller.observe("follower", _state(t, pose, pose))
        return controller.tick(t)

    controller.observe("camera", _image(cfg, t0))
    assert tick(0) and tick(2)  # 200 ms old: still within max_age_ms
    assert tick(3) == {}  # 300 ms: nothing sent, the follower holds
    assert controller.status()["state"] == "stale_observation"
    assert "camera" in controller.status()["error"]
    inferred, resets = len(policy.seen), policy.resets
    assert tick(4) == {} and len(policy.seen) == inferred
    controller.observe("camera", _image(cfg, t0 + 5 * PERIOD_NS))
    assert tick(5)  # fresh again: the policy starts over
    assert policy.resets == resets + 1
    assert (
        controller.status()["state"] == "running" and "error" not in controller.status()
    )


def test_the_history_holds_the_commands_sent_not_the_policy_output(tmp_path):
    # 10 counts per action asked, 40 counts/s allowed at 10 Hz: 4 counts are sent
    _, controller = _controller(
        tmp_path, observation_history=2, max_speed={"follower": 40.0}
    )
    controller.policy = policy = Recorder()
    controller.start("task")
    sent = _run(controller, 3)
    assert sent[0][0] == pytest.approx(2052.0)
    actions = policy.seen[2]["history"]["action"][:, 0]
    assert np.allclose(actions, [sent[0][0], sent[1][0]])


def test_a_sensor_going_stale_stops_the_steps_between_two_actions(tmp_path):
    cfg, controller = _controller(
        tmp_path, observe=["camera"], rate_hz=1, interpolation_multiplier=10
    )
    controller.policy = Recorder()
    controller.start("task")
    pose = [2048.0] * 17
    t0 = 1_000_000_000
    controller.observe("camera", _image(cfg, t0))
    out = []
    for k in range(5):  # 100 ms apart; the camera is 200 ms fresh
        t = t0 + k * PERIOD_NS
        controller.observe("follower", _state(t, pose, pose))
        out.append(bool(controller.tick(t)))
    assert out == [True, True, True, False, False]
    assert controller.status()["state"] == "stale_observation"
