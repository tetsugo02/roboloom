"""The dataflow end to end (dora run, mock devices), driven through `Session` and the CLI."""

import os
import shutil
import subprocess
import sys

import pytest
from conftest import mock_project

from roboloom.errors import HardwareError
from roboloom.runtime.session import EpisodeInfo, Session

pytestmark = pytest.mark.skipif(shutil.which("dora") is None, reason="needs dora")


def test_session_records_episodes_named_by_a_function(tmp_path):
    project = mock_project(tmp_path / ".roboloom")
    names: list[EpisodeInfo] = []

    def task(info: EpisodeInfo) -> str:
        names.append(info)
        return f"pick #{info.index}"

    with Session.launch(project / "experiment.yaml") as s:
        s.wait_ready(30)
        first = s.record(task, 1.0)
        dropped = s.record("drop me", 0.5, keep=lambda ep: False)
        second = s.record(task, 1.0)
        assert s.episodes == 2
    assert (first.task, first.index, first.saved) == ("pick #0", 0, True)
    assert (second.task, second.index) == ("pick #1", 1)
    assert not dropped.saved and dropped.frames > 0 and "rows" in dropped.metrics
    # the first rows of an episode wait for the robot to go HOLD -> ACTIVE
    assert first.frames > 5 and first.metrics["action_valid_rate"] > 0.5
    assert [i.number for i in names] == [0, 1] and names[1].previous == ["pick #0"]
    assert not (project / "datasets" / "rakuda2.fifo").exists()

    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    dataset = LeRobotDataset("local/rakuda2", root=project / "datasets" / "rakuda2")
    assert dataset.num_episodes == 2
    tasks = {dataset[i]["task"] for i in range(len(dataset))}
    assert tasks == {"pick #0", "pick #1"}


def test_hardware_experiments_need_an_explicit_flag(tmp_path):
    project = mock_project(tmp_path / ".roboloom")
    path = project / "experiment.yaml"
    path.write_text(path.read_text().replace("mode: mock", "mode: hardware"))
    with pytest.raises(HardwareError, match="hardware=True"):
        Session.launch(path)


def test_cli_records_one_episode_by_name(tmp_path):
    mock_project(tmp_path / ".roboloom")
    result = subprocess.run(
        [sys.executable, "-m", "roboloom.cli", "record", "rakuda2"]
        + ["--task", "wave", "--seconds", "1"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "saved episode 0: 'wave'" in result.stdout


def test_quality_limits_become_warnings():
    from roboloom.recording import assess

    metrics = {
        "missing_rate": {"camera": 0.2, "leader": 0.0},
        "action_valid_rate": 0.95,
        "control_interval_ms": {"max": 130.0},
    }
    warnings = assess(metrics, {})
    assert len(warnings) == 2 and "camera" in warnings[0] and "130 ms" in warnings[1]
    assert assess(metrics, {"max_missing_rate": 0.5, "max_interval_ms": 200}) == []
