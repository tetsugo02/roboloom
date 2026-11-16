"""Experiments (`configs/roboloom/<name>.yaml` of the project): the robot and options,
what the nodes are given on top of their files, where the episodes go, and how
`roboloom infer|record --experiment` runs."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml
from conftest import mock_project
from test_policy_remote import KEY, _free_address

from roboloom import cli
from roboloom.config import load_config, load_experiment
from roboloom.errors import ConfigError
from roboloom.policy import remote
from roboloom.recording import episodes
from roboloom.recording.manifest import snapshot
from roboloom.runtime.node import config_from_env
from roboloom.runtime.session import Session, config_env, steps_done, steps_timeout

TESTS = str(Path(__file__).resolve().parent)
needs_dora = pytest.mark.skipif(shutil.which("dora") is None, reason="needs dora")

EXPERIMENT = {
    "help": "the slow policy on the drawer task",
    "robot": "rakuda2",
    "options": ["policy"],
    "dataset": {"root": "data/drawer", "repo_id": "local/drawer"},
    "nodes": {
        "controllers.policy": {
            "factory": "policies:creep",
            "kwargs": {"step": 5.0},
            "rate_hz": 5,
        }
    },
    "task": "creep",
    "seconds": 1.5,
    "episodes": 2,
}


def _project(tmp_path: Path, monkeypatch, **changes) -> Path:
    """A project with a mock Rakuda2 and the experiment `drawer`, entered."""
    mock_project(tmp_path / ".roboloom")
    directory = tmp_path / "configs" / "roboloom"
    directory.mkdir(parents=True)
    experiment = {k: v for k, v in {**EXPERIMENT, **changes}.items() if v is not None}
    (directory / "drawer.yaml").write_text(yaml.safe_dump(experiment))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "PYTHONPATH", os.pathsep.join([TESTS, os.environ.get("PYTHONPATH", "")])
    )
    return directory / "drawer.yaml"


def _plans(monkeypatch) -> list:
    started: list = []
    monkeypatch.setattr(
        cli, "_start", lambda args, cfg, plan, **kw: started.append((cfg, plan))
    )
    return started


def test_an_experiment_lays_its_settings_over_the_robots(tmp_path, monkeypatch):
    file = _project(tmp_path, monkeypatch)
    run = load_experiment("drawer")
    assert run == load_experiment(file) == load_experiment(str(file))
    assert (run.name, run.robot, run.options) == ("drawer", "rakuda2", ("policy",))
    assert (run.task, run.seconds, run.episodes, run.home, run.steps) == (
        "creep",
        1.5,
        2,
        None,
        None,
    )
    assert run.dataset["root"] == str(tmp_path / "data" / "drawer")  # from the project
    cfg = load_config("rakuda2", options=run.options, experiment=run)
    policy = cfg.controllers["policy"]
    assert policy.rate_hz == 5 and policy.cfg["factory"] == "policies:creep"
    assert policy.cfg["kwargs"] == {"step": 5.0}
    assert policy.cfg["max_speed"] == {"follower": 1024}  # the robot's file, kept
    # the dataset is where the experiment says, without the options' names
    assert cfg.output == str(tmp_path / "data" / "drawer")
    assert cfg.repo_id == "local/drawer"
    # without it nothing changes; the nodes load it as the launching process did
    plain = load_config("rakuda2", options=["policy"])
    assert plain.controllers["policy"].rate_hz == 15
    assert plain.output.endswith("rakuda2-eval") and plain.experiment is None
    again = config_from_env(cfg.path, config_env(cfg))
    assert again.controllers["policy"].rate_hz == 5 and again.output == cfg.output
    saved = snapshot(cfg)
    assert saved is not None and saved["experiment"] == "drawer"
    assert saved["controllers"]["policy"]["rate_hz"] == 5


def test_a_node_may_be_given_another_file_of_the_robot(tmp_path, monkeypatch):
    nodes = {"controllers.policy": "nodes/policy_slow.yaml"}
    _project(tmp_path, monkeypatch, nodes=nodes, dataset=None)
    robot = tmp_path / ".roboloom" / "rakuda2" / "nodes"
    (robot / "policy_slow.yaml").write_text("extends: policy.yaml\nrate_hz: 3\n")
    run = load_experiment("drawer")
    cfg = load_config("rakuda2", options=run.options, experiment=run)
    assert cfg.controllers["policy"].rate_hz == 3
    assert cfg.output.endswith("rakuda2-eval")  # no dataset given: the robot's


def test_what_an_experiment_may_not_say_is_named(tmp_path, monkeypatch):
    file = _project(tmp_path, monkeypatch)
    for change, problem in (
        ({"secnds": 3}, "unknown keys secnds \\(did you mean seconds\\?\\)"),
        ({"seconds": 0}, "seconds: expected a positive number"),
        ({"episodes": 1.5}, "episodes: expected a whole number"),
        ({"home": "yes please"}, "home: expected true or false"),
        ({"steps": 0}, "steps: expected a whole number, at least 1"),
        ({"steps": 50}, "write seconds or steps"),
        ({"dataset": {"rooot": "x"}}, "unknown keys rooot"),
        ({"nodes": {"policy": {}}}, "expected <role>.<node>"),
        (
            {"nodes": {"followers.follower": {"limits": []}}},
            "an experiment does not change a follower",
        ),
        ({"nodes": {"controllers.policy": 3}}, "expected a node file of the robot"),
    ):
        with pytest.raises(ConfigError, match=problem):
            load_experiment({**EXPERIMENT, **change})
    with pytest.raises(ConfigError, match="no experiment 'drawr'.*drawer"):
        load_experiment("drawr")
    # what only the robot's configuration can tell
    for nodes, problem in (
        (
            {"controllers.polcy": {"rate_hz": 5}},
            "nodes.controllers.polcy is not a node",
        ),
        ({"controllers.policy": {"rate_hx": 5}}, "rate_hx"),
    ):
        run = load_experiment({**EXPERIMENT, "nodes": nodes})
        with pytest.raises(ConfigError, match=problem):
            load_config("rakuda2", options=run.options, experiment=run)
    assert file.is_file()


def test_infer_runs_as_the_experiment_says(tmp_path, monkeypatch):
    file = _project(tmp_path, monkeypatch)
    started = _plans(monkeypatch)
    cli.main(["infer", "--plain", "--experiment", "drawer"])
    cli.main(
        ["infer", "--plain", "--experiment", str(file), "--seconds", "3", "--home"]
    )
    cli.main(["infer", "rakuda2", "--plain", "--experiment", "drawer", "--task", "x"])
    cfg, plan = started[0]
    assert cfg.controllers["policy"].rate_hz == 5 and cfg.repo_id == "local/drawer"
    assert (plan.task, plan.seconds, plan.episodes, plan.home) == (
        "creep",
        1.5,
        2,
        False,
    )
    # words on the command line win
    assert started[1][1].seconds == 3 and started[1][1].home
    assert started[2][1].task == "x" and started[2][1].episodes == 2
    with pytest.raises(SystemExit, match="no experiment 'drawr'"):
        cli.main(["infer", "--plain", "--experiment", "drawr"])
    with pytest.raises(SystemExit, match="give --seconds or --steps, or `seconds:`"):
        cli.main(["infer", "--plain"])


def test_record_takes_an_experiment_too(tmp_path, monkeypatch):
    _project(
        tmp_path,
        monkeypatch,
        options=None,
        nodes=None,
        task="stack the cups",
        seconds=20,
        episodes=None,
        home=True,
    )
    started = _plans(monkeypatch)
    cli.main(["record", "--plain", "--experiment", "drawer"])
    cfg, plan = started[0]
    assert "policy" not in cfg.options and cfg.repo_id == "local/drawer"
    assert (plan.task, plan.seconds, plan.episodes, plan.home) == (
        "stack the cups",
        20,
        1,
        True,
    )
    with pytest.raises(SystemExit, match="record: give --task"):
        cli.main(["record", "--plain", "--seconds", "5"])


def test_an_episode_may_be_given_in_steps_of_the_policy(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch, seconds=None, steps=50)
    started = _plans(monkeypatch)
    cli.main(["infer", "--plain", "--experiment", "drawer"])
    cli.main(["infer", "--plain", "--experiment", "drawer", "--seconds", "4"])
    cli.main(["infer", "--plain", "--experiment", "drawer", "--steps", "10"])
    plans = [plan for _, plan in started]
    assert [p.steps for p in plans] == [50, 0, 10]  # the command line wins
    assert plans[1].seconds == 4
    with pytest.raises(SystemExit, match="give --seconds or --steps, not both"):
        cli.main(["infer", "--plain", "--seconds", "4", "--steps", "10"])
    with pytest.raises(SystemExit, match="steps, which count a policy's actions"):
        cli.main(["record", "--plain", "--experiment", "drawer", "--task", "x"])
    # the time is only the episode's limit: 50 actions at 5 Hz, half as long again + 5 s
    assert steps_timeout(started[0][0], 50) == pytest.approx(50 / 5 * 1.5 + 5)
    with pytest.raises(ConfigError, match="no controller here is a policy"):
        steps_timeout(load_config("rakuda2", options=[]), 50)


def test_the_progress_line_counts_steps_or_time():
    from roboloom.ui.record import progress

    by_time = progress(0, 2, 5.0, 20.0)
    assert by_time == "episode 1/2  [█████░░░░░░░░░░░░░░░] 25%  15.0 s left"
    by_steps = progress(1, 10, 30.0, 155.0, 137, 500)
    assert by_steps.startswith("episode 2/10  step 137/500  [█████░░░░░░░░░░░░░░░] 27%")
    assert by_steps.endswith("at most 125.0 s left")
    assert progress(2, 2, 0.0, 9.0, 600, 500).startswith(
        "episode 3 (2 planned)  step 500/500  [████████████████████] 100%"
    )


def test_the_policy_server_reads_the_same_experiment_file(tmp_path, monkeypatch):
    server = {"address": "127.0.0.1:19002", "timeout_s": 5}
    policy = {**EXPERIMENT["nodes"]["controllers.policy"], "server": server}
    file = _project(tmp_path, monkeypatch, nodes={"controllers.policy": policy})
    assert remote.served_by_experiment(str(file)) == (
        "policies:creep",
        {"step": 5.0},
        server,
    )
    with pytest.raises(SystemExit, match="give one of"):
        remote.main(["policies:creep", "--experiment", str(file)])
    served: list[tuple] = []
    monkeypatch.setattr(
        remote, "serve", lambda *a, **k: served.append((a, k["kwargs"]))
    )
    cli.main(["serve-policy", "--experiment", str(file)])  # the command, not the module
    assert served == [(("policies:creep", server["address"]), {"step": 5.0})]
    file.write_text(yaml.safe_dump({"nodes": {"inputs.leader": "nodes/leader.yaml"}}))
    with pytest.raises(ConfigError, match="expected one policy under nodes"):
        remote.served_by_experiment(str(file))


def test_what_an_experiment_changes_is_not_blamed_on_an_option(tmp_path, monkeypatch):
    """An option without a dataset of its own must not change the recorded features;
    the comparison is made with the experiment on both sides."""
    camera = {"width": 320, "height": 240}
    _project(tmp_path, monkeypatch, nodes={"sensors.camera": camera})
    config = tmp_path / ".roboloom" / "rakuda2" / "config.yaml"
    tree = yaml.safe_load(config.read_text())
    tree["options"]["quiet"] = {"help": "changes nothing that is recorded"}
    config.write_text(yaml.safe_dump(tree, sort_keys=False))
    run = load_experiment("drawer")
    cfg = load_config(run.robot, options=["quiet"], mock=True, experiment=run)
    assert "quiet" in cfg.options  # loaded: the camera size is the experiment's doing


@pytest.mark.e2e
@needs_dora
def test_an_episode_ends_when_the_policy_has_taken_its_steps(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    with Session.launch(experiment="drawer", mock=True) as s:  # robot and options: its
        s.wait_ready(30)
        seen: list[int] = []
        began = time.monotonic()
        result = s.record(
            "creep", 30.0, steps=10, on_tick=lambda st: seen.append(steps_done(st))
        )
        took = time.monotonic() - began
    assert result.saved
    assert max(seen) >= 10 and took < 10  # 10 actions at 5 Hz: about 2 s, not 30
    assert seen == sorted(seen)  # counted up from the start of the episode
    assert episodes.read(tmp_path / "data" / "drawer")[0]["task"] == "creep"


@pytest.mark.e2e
@needs_dora
def test_an_experiment_runs_with_its_server_and_saves_where_it_says(
    tmp_path, monkeypatch, capsys
):
    """One file for both sides: the policy server reads the policy it loads from it,
    the policy node connects to it, and the episodes go to the experiment's dataset."""
    monkeypatch.setenv(remote.AUTHKEY_ENV, KEY)
    server = {"address": _free_address(), "timeout_s": 5}
    policy = {
        **EXPERIMENT["nodes"]["controllers.policy"],
        "backend": "server",
        "server": server,
    }
    file = _project(tmp_path, monkeypatch, nodes={"controllers.policy": policy})
    command = [
        sys.executable,
        "-m",
        "roboloom.policy.remote",
        "--experiment",
        str(file),
    ]
    serving = subprocess.Popen(command, cwd=tmp_path)
    try:
        cli.main(["infer", "--plain", "--experiment", "drawer"])
    finally:
        serving.terminate()
        serving.wait(10)
    root = tmp_path / "data" / "drawer"
    records = episodes.read(root)
    assert [records[k]["task"] for k in (0, 1)] == ["creep"] * 2
    capsys.readouterr()
    cli.main(["check-dataset", "--experiment", "drawer"])
    assert f"dataset: {root}" in capsys.readouterr().out
    cli.main(["label", "--experiment", "drawer", "1", "success"])
    assert episodes.read(root)[1]["label"] == "success"
