from lerobot.datasets.lerobot_dataset import LeRobotDataset

from roboloom import Experiment
from roboloom.drivers.mock import MockBus


def create(output):
    return Experiment.from_components(
        robot_id="toy", robot=MockBus(dimension=2), joint_names=["a", "b"],
        limits=[{"name": name, "min": 0, "max": 4095, "max_step": 100} for name in ("a", "b")],
        controller=lambda obs: [2048, 2048], output=output, repo_id="local/toy",
        fps=5, control_hz=10,
    )


def test_python_interface_save_discard_resume_and_infer(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    root = tmp_path / "dataset"
    with create(root) as exp:
        exp.start_episode("first")
        exp.run(0.3)
        exp.stop_episode()
        assert exp.save_episode() >= 1
        exp.start_episode("discard")
        exp.run(0.2)
        exp.discard_episode()
        exp.start_inference()
        assert exp.step(policy=lambda obs: [2050, 2050])["action"]["valid"]
        exp.stop_inference()
    with create(root) as exp:
        exp.start_episode("second")
        exp.run(0.3)
        exp.stop_episode()
        assert exp.save_episode() >= 1
    dataset = LeRobotDataset(repo_id="local/toy", root=root)
    assert dataset.num_episodes == 2
    assert len(dataset) >= 2
    frame = dataset[0]
    assert isinstance(frame, dict)
    assert frame["observation.state"].shape[0] == 2
