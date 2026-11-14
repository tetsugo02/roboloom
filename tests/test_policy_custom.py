"""From a recording to a policy without LeRobot's policy classes: replaying recorded
actions, and the example model in examples/policies (record -> train -> infer)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest
from conftest import mock_project

from roboloom.errors import ConfigError
from roboloom.policy import PolicySpec
from roboloom.policy.replay import Replay, load
from roboloom.runtime.session import Session

EXAMPLES = str(Path(__file__).resolve().parents[1] / "examples" / "policies")


def _spec(names: tuple[str, ...], rate_hz: float = 10.0) -> PolicySpec:
    return PolicySpec(observation={}, action=names, rate_hz=rate_hz, dataset_fps=30.0)


def test_actions_of_a_file_come_out_in_order_then_stay(tmp_path):
    actions = np.arange(10, dtype=float).reshape(5, 2)
    np.save(tmp_path / "actions.npy", actions)
    policy = load(str(tmp_path / "actions.npy"), horizon=2)
    assert policy.options() == {"action_horizon": 2}
    policy.bind(_spec(("a.x", "a.y")))
    policy.reset()
    out = [policy.infer({}) for _ in range(4)]
    assert np.array_equal(np.concatenate(out[:3]), actions)
    assert np.array_equal(out[3], actions[-1:])  # past the end: the last action
    policy.reset()
    assert np.array_equal(policy.infer({}), actions[:2])
    thinned = load(str(tmp_path / "actions.npy"), horizon=8, stride=2)
    assert np.array_equal(thinned.infer({}), actions[::2])


def test_actions_that_do_not_fit_are_refused(tmp_path):
    with pytest.raises(ConfigError, match="2 values per action"):
        Replay(np.zeros((3, 2))).bind(_spec(("a.x",)))
    with pytest.raises(ConfigError, match="its action is"):
        Replay(np.zeros((3, 2)), names=("b.x", "b.y")).bind(_spec(("a.x", "a.y")))
    with pytest.raises(ConfigError, match="rate_hz"):
        Replay(np.zeros((3, 1)), rate_hz=5.0).bind(_spec(("a.x",), rate_hz=10.0))
    with pytest.raises(ConfigError, match="finite actions"):
        Replay(np.full((3, 1), np.nan))
    with pytest.raises(ConfigError, match="not a LeRobot dataset"):
        load(str(tmp_path))
    with pytest.raises(ConfigError, match="stride"):
        load(str(tmp_path / "x.npy"), stride=0)


@pytest.fixture
def recorded(tmp_path, monkeypatch):
    """A Rakuda2 mock project with one teleoperated episode recorded."""
    project = mock_project(tmp_path / ".roboloom")
    monkeypatch.setenv(
        "PYTHONPATH", os.pathsep.join([EXAMPLES, os.environ.get("PYTHONPATH", "")])
    )
    with Session.launch(project / "config.yaml", log_dir=tmp_path / "logs") as s:
        s.wait_ready(60)
        assert s.record("pick", 3.0).saved
        root = Path(s.cfg.output)
    return project, root


def _column(root: Path, key: str) -> np.ndarray:
    from lerobot.datasets import LeRobotDataset

    dataset = LeRobotDataset(f"local/{root.name}", root=root)
    return np.stack(dataset.hf_dataset[key]).astype(float)


def test_a_recorded_episode_replays_through_the_policy_path(recorded, tmp_path):
    project, root = recorded
    recorded_actions = _column(root, "action")
    with Session.launch(
        project / "config.yaml",
        options=["policy"],
        policy="roboloom.policy.replay:load",
        policy_kwargs={"path": str(root), "horizon": 4},
        log_dir=tmp_path / "logs2",
    ) as s:
        s.wait_ready(60)
        result = s.record("replay", 2.0)
        replayed = Path(s.cfg.output)
        fields = s.status()["policy"]["fields"]
    assert result.saved and result.metrics["action_valid_rate"] > 0.5, result.metrics
    assert fields["state"] in ("ready", "running"), fields
    sent = _column(replayed, "action")
    # the mock leader stands still, so the replay commands the recorded pose
    assert np.allclose(sent[-1], recorded_actions[-1], atol=1.0)


def test_the_example_model_trains_on_a_recording_and_runs(recorded, tmp_path):
    pytest.importorskip("torch")
    project, root = recorded
    sys.path.insert(0, EXAMPLES)
    try:
        import chunk_mlp
    finally:
        sys.path.remove(EXAMPLES)
    with pytest.raises(ValueError, match="at least 2"):  # no history, no past actions
        chunk_mlp.train(str(root), str(tmp_path / "single.pt"), history=1)
    checkpoint = chunk_mlp.train(
        str(root),
        str(tmp_path / "model.pt"),
        history=3,
        horizon=4,
        stride=3,  # 15 fps -> 5 Hz
        exclude=("torso_yaw", "head_yaw", "head_pitch"),
        delta=True,
        steps=20,
    )
    policy = chunk_mlp.load(str(checkpoint))
    options = policy.options()
    assert options["observation_history"] == 3 and options["action_horizon"] == 4
    assert options["hold"] == [
        "follower.torso_yaw",
        "follower.head_yaw",
        "follower.head_pitch",
    ]

    import yaml

    node = project / "nodes" / "policy.yaml"
    settings = yaml.safe_load(node.read_text())
    settings.update(rate_hz=5, observe=[])
    node.write_text(yaml.safe_dump(settings))
    with Session.launch(
        project / "config.yaml",
        options=["policy"],
        policy="chunk_mlp:load",
        policy_kwargs={"checkpoint": str(checkpoint)},
        log_dir=tmp_path / "logs3",
    ) as s:
        s.wait_ready(60)
        result = s.record("pick", 2.0)
        fields = s.status()["policy"]["fields"]
    assert fields["state"] in ("ready", "running") and "infer_ms" in fields, fields
    assert result.saved and result.metrics["action_valid_rate"] > 0.5, result.metrics
