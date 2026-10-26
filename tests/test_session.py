"""The dataflow end to end (dora run, mock devices), driven through `Session` and the CLI."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import mock_project

from roboloom.errors import HardwareError
from roboloom.runtime.session import EpisodeInfo, Session, SessionError

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


def test_policy_drives_the_follower_and_its_runs_are_recorded(tmp_path, monkeypatch):
    project = mock_project(tmp_path / ".roboloom")
    tests = str(Path(__file__).parent.resolve())
    monkeypatch.setenv(
        "PYTHONPATH", os.pathsep.join([tests, os.environ.get("PYTHONPATH", "")])
    )
    with Session.launch(
        project / "experiment_policy.yaml",
        policy="policies:creep",
        policy_kwargs={"step": 5.0},
    ) as s:
        s.wait_ready(30)  # the policy is loaded
        assert s.status()["policy"]["fields"]["state"] == "ready"
        result = s.record("creep", 1.5)
        policy = s.status()["policy"]["fields"]
    assert result.saved and result.metrics["action_valid_rate"] > 0.5, result.metrics
    assert policy["state"] == "ready" and "infer_ms" in policy, policy

    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    dataset = LeRobotDataset(
        "local/rakuda2_eval", root=project / "datasets" / "rakuda2_eval"
    )
    first = [float(dataset[i]["observation.state"][0]) for i in range(len(dataset))]
    assert first[-1] > first[0] + 20  # the policy moved joint 0 up


def test_a_policy_that_fails_to_load_blocks_start(tmp_path, monkeypatch):
    project = mock_project(tmp_path / ".roboloom")
    tests = str(Path(__file__).parent.resolve())
    monkeypatch.setenv("PYTHONPATH", tests)
    with Session.launch(
        project / "experiment_policy.yaml", policy="policies:broken"
    ) as s:
        with pytest.raises(SessionError, match="failed"):
            s.wait_ready(3)
        assert "reset() and infer()" in s.status()["policy"]["fields"]["error"]


def test_node_failures_are_read_from_the_dora_log(tmp_path):
    session = Session.__new__(Session)
    session.log_path = tmp_path / "dora.log"
    session.log_path.write_text("starting\n")
    assert session.node_errors() == []
    session.log_path.write_text(
        "\x1b[31mERROR\x1b[0m node_failure: node exited with error: ExitCode(1) node_id=recorder\n"
        "  File 'recorder.py', line 104\n"
        "ValueError: existing dataset schema or FPS differs from experiment: /data\n"
    )
    errors = session.node_errors()
    assert errors[0].startswith("ERROR node_failure") and errors[-1].startswith(
        "ValueError: existing dataset"
    )


def test_screen_and_the_question_before_the_leader_goes_limp(tmp_path, capsys):
    from roboloom.operator import ScriptedOperator

    project = mock_project(tmp_path / ".roboloom")
    operator = ScriptedOperator()
    with Session.launch(
        project / "experiment.yaml", screen=True, operator=operator
    ) as s:
        assert s.actuated == ["leader"]  # the trigger spring runs a control law
        s.wait_ready(30)
        s.record("wave", 0.5)
        print("from the script")
        messages = [m.plain for m in s.screen.messages]
    assert any("recording 'wave'" in m for m in messages), messages
    assert any("saved" in m for m in messages), messages
    assert "Support the arms of leader" in operator.log[-1]
    out = capsys.readouterr().out
    assert "from the script" in out and "nodes" in out  # printed above the screen


def test_no_screen_or_question_without_a_terminal(tmp_path):
    project = mock_project(tmp_path / ".roboloom")
    with Session.launch(project / "experiment_camera.yaml") as s:  # pytest: not a tty
        assert s.screen is None and s.operator is None


@pytest.mark.parametrize(("answer", "released"), [("", True), ("hold", False)])
def test_closing_releases_the_follower_unless_the_operator_says_hold(
    tmp_path, answer, released
):
    from roboloom.operator import ScriptedOperator

    project = mock_project(tmp_path / ".roboloom")
    operator = ScriptedOperator(prompts=[answer])
    sent: list[str] = []
    with Session.launch(
        project / "experiment.yaml", screen=False, operator=operator
    ) as s:
        assert s.held == ["robot"]
        s.wait_ready(30)
        send = s.client.send
        s.client.send = lambda line: (sent.append(line), send(line))[1]  # type: ignore[method-assign]
    assert "Enter ends with the follower torque off" in operator.log[-1]
    assert sent == (["release", "quit"] if released else ["quit"])


def test_release_while_following_stops_then_turns_the_torque_off(tmp_path):
    import time

    project = mock_project(tmp_path / ".roboloom")
    with Session.launch(project / "experiment.yaml", screen=False, operator=None) as s:
        s.wait_ready(30)
        s.start("released mid-episode")
        s.release(confirm=True)
        deadline = time.monotonic() + 5
        mode = None
        while time.monotonic() < deadline and mode != "RELEASED":
            mode = s.status().get("robot", {}).get("fields", {}).get("mode")
            time.sleep(0.1)
        assert mode == "RELEASED"


def test_live_quit_releases_the_follower_unless_hold(tmp_path):
    from roboloom.ui.live import LiveSession

    class Client:
        def __init__(self) -> None:
            self.sent: list[str] = []

        def send(self, line: str) -> None:
            self.sent.append(line)

    for answer, expected in (("", ["release", "quit"]), ("hold", ["quit"]), ("no", [])):
        client = Client()
        live = LiveSession(
            client,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            tmp_path / "dora.log",
            "test",
            limp_on_quit=["leader"],
            held=["robot"],
        )
        live.submit("quit")
        assert "follower torque off" in live.prompt().plain
        live.submit(answer)
        assert client.sent == expected
