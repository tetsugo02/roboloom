"""Experiment files (`experiments/<name>.yaml`): a launch option plus how
`roboloom infer|record --experiment <name>` runs it."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from conftest import mock_project

from roboloom import cli
from roboloom.config import declared_options, load_config, load_experiment
from roboloom.errors import ConfigError
from roboloom.recording import episodes
from roboloom.runtime.node import config_from_env
from roboloom.runtime.session import config_env

EXPERIMENT = """\
help: the slow policy on the drawer task
options: [policy]
policy: nodes/policy_slow.yaml
dataset: drawer
task: open the drawer
seconds: 1.5
episodes: 2
"""


def _project(tmp_path: Path, text: str = EXPERIMENT) -> Path:
    """A mock Rakuda2 with the experiment `drawer`; its policy runs at 5 Hz."""
    project = mock_project(tmp_path / ".roboloom")
    policy = (project / "nodes" / "policy.yaml").read_text()
    assert "rate_hz: 15" in policy
    slow = policy.replace("rate_hz: 15", "rate_hz: 5")
    (project / "nodes" / "policy_slow.yaml").write_text(slow)
    (project / "experiments").mkdir()
    (project / "experiments" / "drawer.yaml").write_text(text)
    return project


def _plans(monkeypatch) -> list:
    started: list = []
    monkeypatch.setattr(
        cli, "_start", lambda args, cfg, plan, **kw: started.append((cfg, plan))
    )
    return started


def test_an_experiment_is_an_option_with_its_policy_and_dataset(tmp_path):
    config = _project(tmp_path) / "config.yaml"
    option = declared_options(config)["drawer"]
    assert option.requires == ("policy",) and option.dataset == "drawer"
    assert option.set == {"controllers.policy": "nodes/policy_slow.yaml"}
    assert option.help == "the slow policy on the drawer task"
    run = load_experiment(config, "drawer")
    assert (run.task, run.seconds, run.episodes, run.home) == (
        "open the drawer",
        1.5,
        2,
        None,
    )
    cfg = load_config(config, options=["drawer"])
    assert cfg.options == ("policy", "drawer")
    assert cfg.controllers["policy"].rate_hz == 5
    assert cfg.repo_id.endswith("-eval-drawer") and cfg.output.endswith("-eval-drawer")
    # without it nothing changes; the nodes load it as the launching process did
    assert load_config(config, options=["policy"]).controllers["policy"].rate_hz == 15
    again = config_from_env(str(config), config_env(cfg))
    assert again.controllers["policy"].rate_hz == 5 and again.output == cfg.output


def test_infer_runs_as_the_experiment_says(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    started = _plans(monkeypatch)
    cli.main(["infer", "--plain", "--experiment", "drawer"])
    cli.main(["infer", "--plain", "--experiment", "drawer", "--seconds", "3", "--home"])
    cli.main(["infer", "rakuda2", "--plain", "--experiment", "drawer", "--task", "x"])
    cfg, plan = started[0]
    assert cfg.controllers["policy"].rate_hz == 5 and "drawer" in cfg.options
    assert (plan.task, plan.seconds, plan.episodes, plan.home) == (
        "open the drawer",
        1.5,
        2,
        False,
    )
    # words on the command line win
    assert started[1][1].seconds == 3 and started[1][1].home
    assert started[2][1].task == "x" and started[2][1].episodes == 2


def test_record_takes_an_experiment_too(tmp_path, monkeypatch):
    text = "task: stack the cups\nseconds: 20\nhome: true\n"
    _project(tmp_path, text)
    monkeypatch.chdir(tmp_path)
    started = _plans(monkeypatch)
    cli.main(["record", "--plain", "--experiment", "drawer"])
    cfg, plan = started[0]
    assert "policy" not in cfg.options and cfg.options[-1] == "drawer"
    assert (plan.task, plan.seconds, plan.episodes, plan.home) == (
        "stack the cups",
        20,
        1,
        True,
    )


def test_what_is_missing_or_mistyped_is_named(tmp_path, monkeypatch):
    project = _project(tmp_path, "options: [policy]\n")
    monkeypatch.chdir(tmp_path)
    _plans(monkeypatch)
    with pytest.raises(SystemExit, match="give --seconds, or `seconds:` in exp"):
        cli.main(["infer", "--plain", "--experiment", "drawer"])
    with pytest.raises(SystemExit, match="give --seconds, or `seconds:` in an exp"):
        cli.main(["infer", "--plain"])
    with pytest.raises(SystemExit, match="record: give --task"):
        cli.main(["record", "--plain", "--experiment", "drawer", "--seconds", "5"])
    with pytest.raises(SystemExit, match="no experiment 'drawr'.*available: drawer"):
        cli.main(["infer", "--plain", "--experiment", "drawr"])
    file = project / "experiments" / "drawer.yaml"
    config = project / "config.yaml"
    for text, problem in (
        ("secnds: 3\n", "unknown keys secnds \\(did you mean seconds\\?\\)"),
        ("seconds: 0\n", "seconds: expected a positive number"),
        ("episodes: 1.5\n", "episodes: expected a whole number"),
        ("home: yes please\n", "home: expected true or false"),
        ("options: [polcy]\n", "unknown option 'polcy'"),
        ("policy: nodes/a.yaml\nset: {controllers.policy: nodes/b.yaml}\n", "same"),
    ):
        file.write_text(text)
        with pytest.raises(ConfigError, match=problem):
            declared_options(config)
    file.rename(file.with_name("policy.yaml"))  # the name of an option of the robot
    with pytest.raises(ConfigError, match="already has an option 'policy'"):
        declared_options(config)


@pytest.mark.skipif(shutil.which("dora") is None, reason="needs dora")
def test_an_experiment_runs_and_saves_its_episodes(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    cli.main(["infer", "--plain", "--experiment", "drawer"])
    root = Path(load_config("rakuda2", options=["drawer"]).output)
    assert root.name.endswith("-eval-drawer")
    records = episodes.read(root)
    assert [records[k]["task"] for k in (0, 1)] == ["open the drawer"] * 2
