"""Launch options: node replacement, requirements and conflicts, dataset names, the CLI
words and the launcher."""

from __future__ import annotations

import shutil
import sys
from argparse import Namespace
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml
from conftest import mock_project, rakuda2_tree
from rich.console import Console
from textual.widgets import Button, Checkbox, Input, OptionList, Static

from roboloom.cli import _with_config
from roboloom.config import (
    load_config,
    option_changes,
    parse_config,
    parse_options,
    select_options,
)
from roboloom.errors import ConfigError
from roboloom.ui.launcher import LauncherApp, LaunchPlan, load_last, save_last

OPTIONS = {
    "a": {"set": {"inputs.leader": "a.yaml"}},
    "b": {"requires": ["a"], "set": {"inputs.leader": "b.yaml"}},
    "c": {"conflicts": ["b"], "default": True},
    "d": {"set": {"inputs.leader": "d.yaml"}},
}


def test_selection_adds_requirements_and_drops_conflicts():
    options = parse_options(OPTIONS)
    assert select_options(options) == ("c",)  # the defaults
    assert select_options(options, ["b"]) == ("a", "b")  # c conflicts with b
    assert select_options(options, ["b"], ["a"]) == ()  # b goes with a; c stays off
    with pytest.raises(ConfigError, match="cannot be used together"):
        select_options(options, ["b", "c"])
    with pytest.raises(ConfigError, match="unknown options"):
        select_options(options, ["nope"])


def test_dependent_option_refines_and_unrelated_ones_clash():
    options = parse_options(OPTIONS)
    assert option_changes(options, ["a", "b"]) == {"inputs.leader": "b.yaml"}
    with pytest.raises(ConfigError, match="both set inputs.leader"):
        option_changes(options, ["a", "d"])


@pytest.mark.parametrize(
    "bad",
    [
        {"x": {"set": {"nodes.leader": "x.yaml"}}},
        {"x": {"requires": ["missing"]}},
        {"x": {"colour": "red"}},
        {"x": {"dataset": "a b"}},
    ],
)
def test_bad_options_are_rejected(bad):
    with pytest.raises(ConfigError):
        parse_options(bad)


def test_template_options_replace_nodes_and_name_datasets():
    cfg = parse_config(rakuda2_tree())
    assert cfg.options == () and set(cfg.sensors) == {"camera"}
    assert cfg.repo_id == "local/rakuda2"
    cfg = parse_config(rakuda2_tree(["digit"]))
    assert set(cfg.sensors) == {"camera", "digit_left", "digit_right"}
    assert cfg.repo_id == "local/rakuda2-digit"
    assert cfg.output.endswith("datasets/rakuda2-digit")
    tree = rakuda2_tree(["policy"])
    assert tree["options"] == ("policy",)
    assert "leader" not in tree["inputs"] and set(tree["controllers"]) == {"policy"}
    cfg = parse_config(tree)
    assert set(cfg.sensors) == {"camera"}
    assert cfg.controllers["policy"].observes() == ["camera"]
    assert cfg.repo_id == "local/rakuda2-eval"
    cfg = parse_config(rakuda2_tree(["digit", "policy"]))
    assert set(cfg.sensors) == {"camera", "digit_left", "digit_right"}
    assert cfg.repo_id == "local/rakuda2-digit-eval"


def test_option_changing_features_needs_its_own_dataset(tmp_path):
    project = mock_project(tmp_path / ".roboloom")
    path = project / "config.yaml"
    text = path.read_text()
    path.write_text(text.replace("    dataset: digit\n", ""))
    with pytest.raises(ConfigError, match="options.digit changes the recorded"):
        load_config(path, options=["digit"])
    assert load_config(path).options == ()  # off: nothing to compare


def test_configuration_words_move_into_config(tmp_path, monkeypatch):
    mock_project(tmp_path / ".roboloom")
    monkeypatch.chdir(tmp_path)
    assert _with_config([]) == ["launch"]
    assert _with_config(["--mock"]) == ["launch", "--mock"]
    assert _with_config(["rakuda2"]) == ["launch", "--config", "rakuda2"]
    assert _with_config(["run", "rakuda2", "--mock"])[:3] == [
        "run",
        "--config",
        "rakuda2",
    ]
    assert _with_config(["commission", "follower"]) == ["commission", "follower"]
    assert _with_config(["commission", "rakuda2", "follower"]) == [
        "commission",
        "--config",
        "rakuda2",
        "follower",
    ]
    assert _with_config(["session", "home"]) == ["session", "home"]
    assert _with_config(["session", "rakuda2", "home"])[:3] == [
        "session",
        "--config",
        "rakuda2",
    ]


def test_the_hardware_flag_is_refused_with_a_hint(capsys):
    from roboloom.cli import main

    with pytest.raises(SystemExit):
        main(["run", "rakuda2", "--hardware"])
    assert "--mock" in capsys.readouterr().err


def test_validate_by_default_name_with_options(tmp_path, monkeypatch, capsys):
    if shutil.which("dora") is None:
        pytest.skip("needs dora")
    from roboloom.cli import main

    mock_project(tmp_path / ".roboloom")
    monkeypatch.chdir(tmp_path)
    main(["validate", "--with", "digit"])
    out = capsys.readouterr().out
    assert "options: digit" in out and "local/rakuda2-digit" in out


def _options_config(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"repo_id": "local/x", "options": OPTIONS}))
    return path


def test_last_choice_is_remembered(tmp_path):
    path = _options_config(tmp_path)
    options = parse_options(OPTIONS)
    assert load_last(path, options) is None
    save_last(path, LaunchPlan("record", ("a", "b"), True, "pick", 5.0, 2, True))
    plan = load_last(path, options)
    assert plan == LaunchPlan("record", ("a", "b"), True, "pick", 5.0, 2, True)


@pytest.mark.asyncio
async def test_confirm_toggle_is_for_recording_modes_and_is_remembered(tmp_path):
    path = _options_config(tmp_path)
    app = LauncherApp(path, LaunchPlan(seconds=3))
    async with app.run_test(size=(100, 50)) as pilot:
        confirm = app.query_one("#confirm", Checkbox)
        assert not confirm.display and not confirm.value
        app.query_one("#mode-record").value = True
        await pilot.pause()
        assert confirm.display
        await pilot.click("#confirm")
        assert confirm.value
        app.query_one("#mode-infer").value = True
        await pilot.pause()
        assert confirm.display
        assert app.query_one(
            "#launch", Button
        ).disabled  # infer needs a task with confirm
        app.query_one("#task").value = "pick"
        await pilot.pause()
        await pilot.click("#launch")
    plan = app.return_value
    assert isinstance(plan, LaunchPlan) and plan.mode == "infer" and plan.confirm
    save_last(path, plan)
    assert load_last(path, parse_options(OPTIONS)) == plan


@pytest.mark.asyncio
async def test_launcher_follows_requirements_and_conflicts(tmp_path: Path):
    path = _options_config(tmp_path)
    app = LauncherApp(path, LaunchPlan(options=("c",)))
    async with app.run_test(size=(100, 50)) as pilot:
        app.query_one("#opt-b", Checkbox).value = True  # b needs a, drops c
        await pilot.pause()
        assert app.chosen == {"a", "b"}
        assert app.query_one("#opt-a", Checkbox).value
        assert not app.query_one("#opt-c", Checkbox).value
        app.query_one("#opt-a", Checkbox).value = False  # b goes with it
        await pilot.pause()
        assert app.chosen == set()
        app.query_one("#mode-record").value = True
        await pilot.pause()
        assert app.query_one("#launch", Button).disabled  # record needs task/seconds
        app.query_one("#task").value = "pick"
        app.query_one("#seconds").value = "3"
        app.query_one("#mock", Checkbox).value = True
        await pilot.pause()
        assert not app.query_one("#launch", Button).disabled
        await pilot.click("#launch")
    assert app.return_value == LaunchPlan("record", (), True, "pick", 3.0, 1, False)


def test_launcher_summary_says_mock_when_the_yaml_declares_it(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"repo_id": "local/x", "mode": "mock"}))
    app = LauncherApp(path, LaunchPlan())
    assert app._summary(LaunchPlan()).startswith(
        "run · mock (mode: mock in config.yaml)"
    )
    assert app._summary(LaunchPlan(mock=True)).startswith("run · mock ·")
    path.write_text(yaml.safe_dump({"repo_id": "local/x"}))
    assert "HARDWARE" in LauncherApp(path, LaunchPlan())._summary(LaunchPlan())


def _two_robots(root: Path) -> None:
    for robot, repo in (("alpha", "local/a"), ("beta", "local/b")):
        (root / robot).mkdir(parents=True)
        (root / robot / "config.yaml").write_text(
            yaml.safe_dump({"repo_id": repo, "options": OPTIONS})
        )


@pytest.mark.asyncio
async def test_robot_list_selects_and_starts_at_the_last_one(tmp_path: Path):
    from textual.widgets import OptionList

    from roboloom.ui.launcher import RobotApp, robot_detail

    _two_robots(tmp_path)
    console = Console(record=True, width=100)
    console.print(robot_detail(tmp_path, "beta"))
    detail = console.export_text()
    assert (
        "local/b" in detail
        and "✓ c" in detail.replace("  ", " ")
        and "requires a" in detail
    )
    app = RobotApp(tmp_path, ["alpha", "beta"], initial="beta")
    async with app.run_test() as pilot:
        assert app.query_one("#robots", OptionList).highlighted == 1
        await pilot.press("up", "enter")
    assert app.return_value == "alpha"
    app = RobotApp(tmp_path, ["alpha", "beta"], initial="gone")
    async with app.run_test() as pilot:
        await pilot.press("escape")
    assert app.return_value is None


def test_choose_robot_remembers_the_choice(tmp_path, monkeypatch):
    from roboloom.ui import launcher

    _two_robots(tmp_path)
    seen = []

    def fake_run(self):
        seen.append(self.initial)
        return "beta"

    monkeypatch.setattr(launcher.RobotApp, "run", fake_run)
    assert launcher.choose_robot(tmp_path) == "beta"
    assert launcher.choose_robot(tmp_path) == "beta"
    assert seen == ["alpha", "beta"]  # first time the first robot, then the last one
    with pytest.raises(ConfigError, match="roboloom init"):
        launcher.choose_robot(tmp_path / "empty")


@pytest.mark.asyncio
async def test_options_screen_goes_back_to_the_robot_list(tmp_path: Path):
    from roboloom.ui.launcher import BACK

    path = _options_config(tmp_path)
    app = LauncherApp(path, LaunchPlan(), back=True)
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.press("escape")
    assert app.return_value == BACK
    app = LauncherApp(path, LaunchPlan())  # opened for a named robot: Esc cancels
    async with app.run_test(size=(100, 50)) as pilot:
        assert not app.query("#back")
        await pilot.press("escape")
    assert app.return_value is None


def test_launch_without_a_robot_starts_with_the_robot_list(tmp_path, monkeypatch):
    from roboloom import cli
    from roboloom.ui import launcher

    _two_robots(tmp_path / ".roboloom")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    robots = iter(["alpha", "beta", None])
    monkeypatch.setattr(launcher, "choose_robot", lambda *a: next(robots))
    shown = []

    def fake_choose(path, plan, *, back=False):
        shown.append((path.parent.name, back))
        return launcher.BACK

    monkeypatch.setattr(launcher, "choose", fake_choose)
    cli.main([])
    assert shown == [("alpha", True), ("beta", True)]  # Back twice, then Esc


@pytest.mark.parametrize("failure", ["load_config", "_start"])
def test_failed_launch_returns_to_the_same_plan(tmp_path, monkeypatch, failure):
    from roboloom import cli
    from roboloom.ui import launcher

    path = mock_project(tmp_path) / "config.yaml"
    selected = LaunchPlan(mode="infer", options=("policy",), mock=True, seconds=3)
    choose = Mock(side_effect=[selected, selected, None])
    error = ConfigError("launch failed in test")
    start = Mock(return_value="reselect")
    monkeypatch.setattr(launcher, "choose", choose)
    monkeypatch.setattr(cli, "_start", start)
    if failure == "load_config":
        cfg = load_config(path, options=selected.options)
        monkeypatch.setattr(cli, "load_config", Mock(side_effect=[error, cfg]))
    else:
        start.side_effect = [error, "reselect"]

    assert (
        cli._operate_robot(Namespace(command="launch", config=path), True, back=False)
        is None
    )

    first, retry, reselect = choose.call_args_list
    assert first.kwargs == {"back": False}
    assert retry.args[0] == path
    assert retry.args[1] is selected
    assert retry.kwargs == {"back": False, "launch_error": str(error)}
    assert reselect.kwargs == {"back": False}


@pytest.mark.asyncio
async def test_launcher_panes_resize_and_stack_when_narrow(tmp_path: Path):
    from roboloom.ui.launcher import RobotApp
    from roboloom.ui.splitter import Splitter

    path = _options_config(tmp_path)
    app = LauncherApp(path, LaunchPlan())
    async with app.run_test(size=(120, 40)) as pilot:
        left = app.query_one("#left").region.width
        app.query_one("#col-splitter", Splitter).focus()
        await pilot.press("right", "right", "right")
        await pilot.pause()
        assert app.query_one("#left").region.width == left + 3
        summary = app.query_one("#summary-pane").region.height
        app.query_one("#row-splitter", Splitter).focus()
        await pilot.press("up", "up")
        await pilot.pause()
        assert app.query_one("#summary-pane").region.height == summary + 2
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert app.query_one("#summary-pane").region.height == summary
    app = LauncherApp(path, LaunchPlan())
    async with app.run_test(size=(70, 40)) as pilot:  # stacked
        await pilot.pause()
        assert not app.query_one("#col-splitter").display
        assert app.query_one("#options").region.y > app.query_one("#left").region.y
    _two_robots(tmp_path / "robots")
    robots = RobotApp(tmp_path / "robots", ["alpha", "beta"])
    async with robots.run_test(size=(120, 30)) as pilot:
        width = robots.query_one("#robots").region.width
        robots.query_one("#col-splitter", Splitter).focus()
        await pilot.press("left", "left")
        await pilot.pause()
        assert robots.query_one("#robots").region.width == width - 2


@pytest.mark.asyncio
@pytest.mark.parametrize("via", ["mode", "option"])
async def test_launcher_loads_new_policy_observation_defaults(tmp_path, via):
    project = mock_project(tmp_path)
    path = project / "config.yaml"
    app = LauncherApp(path, LaunchPlan())
    async with app.run_test(size=(100, 50)) as pilot:
        camera = app.observation_names.index("camera")
        assert not app.query_one(f"#observe-{camera}", Checkbox).value
        if via == "mode":
            app.query_one("#mode-infer").value = True
        else:
            app.query_one("#opt-policy", Checkbox).value = True
        await pilot.pause()
        assert app.query_one(f"#observe-{camera}", Checkbox).value
        plan = app._read()
        assert plan.observe is None
        cfg = load_config(
            path, options=plan.options, sensors=plan.sensors, observe=plan.observe
        )
        assert cfg.controller_for("follower").observes() == ["camera"]
        # Default-derived observations remain defaults after saving/reopening.
        save_last(path, plan)
        assert load_last(path, app.options).observe is None
        app.query_one(
            f"#sensor-{app.sensor_names.index('camera')}", Checkbox
        ).value = False
        await pilot.pause()
        assert "inactive sensors" in app._problem(app._read())


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", ["initial_empty", "initial_other", "edited"])
async def test_launcher_preserves_explicit_observations(tmp_path, explicit):
    project = mock_project(tmp_path)
    initial = LaunchPlan(
        options=("policy",) if explicit == "edited" else (),
        observe=None
        if explicit == "edited"
        else ([] if explicit == "initial_empty" else ["digit_left"]),
    )
    app = LauncherApp(project / "config.yaml", initial)
    async with app.run_test(size=(100, 50)) as pilot:
        camera = app.observation_names.index("camera")
        if explicit == "edited":
            app.query_one(f"#observe-{camera}", Checkbox).value = False
            await pilot.pause()
            app.query_one("#opt-policy", Checkbox).value = False
            await pilot.pause()
        app.query_one("#mode-infer").value = True
        await pilot.pause()
        expected = ["digit_left"] if explicit == "initial_other" else []
        assert app._read().observe == expected
        assert not app.query_one(f"#observe-{camera}", Checkbox).value


@pytest.mark.asyncio
async def test_launcher_validates_config_before_infer(tmp_path, monkeypatch):
    from roboloom.ui import launcher

    path = mock_project(tmp_path) / "config.yaml"
    validate = Mock(wraps=load_config)
    monkeypatch.setattr(launcher, "load_config", validate)
    app = LauncherApp(
        path,
        LaunchPlan(mode="infer", options=("policy",), seconds=3),
        launch_error="session failed in test",
    )
    async with app.run_test(size=(100, 50)) as pilot:
        summary = app.query_one("#summary", Static)
        launch = app.query_one("#launch", Button)
        assert str(summary.render()).startswith(
            "last launch failed: session failed in test"
        )
        assert not launch.disabled
        assert validate.call_count == 1

        app.query_one("#task", Input).value = "pick"
        await pilot.pause()
        assert "last launch failed" not in str(summary.render())
        assert validate.call_count == 1

        leader = app.observation_names.index("leader")
        await pilot.click(f"#observe-{leader}")
        assert launch.disabled
        assert (
            f"cannot launch: {path}: controllers.policy observes unknown nodes ['leader']"
            in str(summary.render())
        )
        assert validate.call_count == 2
        await pilot.press("ctrl+s")
        await pilot.press("escape")
    assert app.return_value is None


@pytest.fixture
def home_config(tmp_path: Path) -> Path:
    from roboloom.setup import capture_pose

    project = mock_project(tmp_path)
    path = project / "config.yaml"
    capture_pose(path, "ready")
    poses = project / "poses" / "follower"
    shutil.copyfile(poses / "ready.yaml", poses / "camera_pose.yaml")
    (poses / "broken.yaml").write_text("pose: [")
    controller = project / "nodes" / "controller.yaml"
    controller.write_text(
        controller.read_text()
        + "home:\n  pose: ../poses/follower/ready.yaml\n  max_speed: 400\n  tolerance: 30\n"
    )
    return path


@pytest.mark.asyncio
async def test_launcher_selects_and_saves_home_pose(home_config: Path):
    app = LauncherApp(
        home_config, LaunchPlan(mode="record", task="pick", seconds=3, home=True)
    )
    async with app.run_test(size=(100, 50)) as pilot:
        poses = app.query_one("#home-pose", OptionList)
        summary = app.query_one("#summary", Static)
        assert app.query_one("#home").display and poses.display
        assert [option.id for option in poses.options] == [
            "ready",
            "camera_pose",
            "broken",
        ]
        assert "ready (default)" in str(poses.options[0].prompt)
        broken = poses.get_option("broken")
        assert broken.disabled
        reason = str(broken.prompt)
        assert reason.startswith("broken — unavailable: follower:")
        assert "expected the node content" in reason
        assert poses.highlighted == 0
        assert app._read().home_pose is None
        assert "home: ready" in str(summary.render())

        assert await pilot.click("#home-pose", offset=(2, 2))
        assert app._read().home_pose == "camera_pose"
        assert "home: camera_pose" in str(summary.render())
        poses.focus()
        await pilot.press("up")
        assert poses.highlighted == 0
        assert app._read().home_pose == "camera_pose"
        await pilot.press("enter")
        assert app._read().home_pose == "ready"
        await pilot.press("down", "enter")
        assert app._read().home_pose == "camera_pose"
        assert app._problem(replace(app._read(), home_pose="broken")) == (
            "home pose 'broken' is unavailable: "
            + reason.removeprefix("broken — unavailable: ")
        )
        assert app._problem(replace(app._read(), home_pose="missing")) == (
            "unknown home pose 'missing'"
        )

        await pilot.click("#opt-policy")
        assert not poses.display and not app.query_one("#home").display
        await pilot.click("#opt-policy")
        assert poses.display and poses.highlighted == 1
        await pilot.press("ctrl+s")
    plan = app.return_value
    assert isinstance(plan, LaunchPlan)
    assert plan.home_pose == "camera_pose"
    save_last(home_config, plan)
    assert load_last(home_config, app.options) == plan


@pytest.mark.asyncio
@pytest.mark.parametrize("full_config", [True, False])
async def test_launcher_without_home_poses(tmp_path: Path, full_config: bool):
    if full_config:
        path = mock_project(tmp_path) / "config.yaml"
    else:
        path = tmp_path / "config.yaml"
        path.write_text("options: {}\n")
    app = LauncherApp(
        path, LaunchPlan(mode="record", task="pick", seconds=3, home=True)
    )
    async with app.run_test(size=(100, 50)) as pilot:
        assert app.query_one("#home").display is not full_config
        assert not app.query_one("#home-pose").display
        await pilot.press("ctrl+s")
    assert isinstance(app.return_value, LaunchPlan)
    assert app.return_value.home is not full_config


@pytest.mark.parametrize(
    ("command", "args_home", "expected"),
    [
        ("launch", None, "camera_pose"),
        ("launch", "ready", "ready"),
        ("record", "ready", "ready"),
        ("record", True, True),
        ("record", False, False),
    ],
)
def test_operate_robot_passes_home_to_recording_plan(
    home_config: Path, monkeypatch, command, args_home, expected
):
    from roboloom import cli
    from roboloom.ui import app, launcher

    save_last(
        home_config,
        LaunchPlan(
            mode="record", task="pick", seconds=3, home=True, home_pose="camera_pose"
        ),
    )
    monkeypatch.setattr(launcher, "choose", lambda path, plan, *, back: plan)
    run_backend = Mock(return_value="done")
    monkeypatch.setattr(app, "run_backend", run_backend)
    args = Namespace(command=command, config=home_config, task="pick", seconds=3)
    if args_home is not None:
        args.home = args_home
    cli._operate_robot(args, True, back=False)
    recording = run_backend.call_args.args[0].recording
    assert recording is not None
    assert recording.home == expected


@pytest.mark.asyncio
async def test_launcher_uses_active_experiment_for_validation_and_homes(
    tmp_path: Path, monkeypatch
):
    from roboloom import cli
    from roboloom.config import Experiment
    from roboloom.ui import launcher

    project = mock_project(tmp_path)
    path = project / "config.yaml"
    poses = project / "poses" / "follower"
    poses.mkdir(parents=True)
    pose = {
        limit["name"]: 2048
        for limit in yaml.safe_load((project / "nodes" / "follower.yaml").read_text())[
            "limits"
        ]
    }
    (poses / "ready.yaml").write_text(
        yaml.safe_dump(
            {
                "follower": "follower",
                "model": "rakuda2",
                "unit": "dynamixel_count",
                "pose": pose,
            }
        )
    )
    experiment = Experiment(
        name="with-home",
        nodes={
            "controllers.controller": {
                "home": {
                    "pose": "../poses/follower/ready.yaml",
                    "max_speed": 200,
                    "tolerance": 30,
                }
            }
        },
    )

    app = LauncherApp(
        path,
        LaunchPlan(mode="record", task="pick", seconds=3, home=True),
        experiment=experiment,
    )
    async with app.run_test(size=(100, 50)) as pilot:
        assert app.query_one("#home").display
        assert app.query_one("#home-pose").display
        assert not app.query_one("#launch", Button).disabled
        await pilot.press("ctrl+s")
    assert isinstance(app.return_value, LaunchPlan)
    assert app.return_value.home is True

    choose = Mock(
        side_effect=[
            LaunchPlan(mode="record", task="pick", seconds=3, home=True),
            None,
        ]
    )
    monkeypatch.setattr(launcher, "choose", choose)
    monkeypatch.setattr(cli, "_start", Mock(return_value="reselect"))
    cli._operate_robot(
        Namespace(
            command="record",
            config=path,
            task="pick",
            seconds=3,
            home=True,
            experiment=experiment,
        ),
        True,
        back=False,
    )
    assert choose.call_args.kwargs["experiment"] is experiment


@pytest.mark.asyncio
async def test_launcher_shows_per_follower_defaults_when_defaults_differ(
    tmp_path: Path,
):
    from roboloom.ui.launcher import HOME_DEFAULT_ID

    project = mock_project(tmp_path)
    nodes = project / "nodes"
    follower_cfg = yaml.safe_load((nodes / "follower.yaml").read_text())
    leader_cfg = yaml.safe_load((nodes / "leader.yaml").read_text())
    recorder_cfg = yaml.safe_load((nodes / "recorder.yaml").read_text())
    recorder_cfg["max_age_ms"].update(
        {"left": 200, "right": 200, "leader_left": 200, "leader_right": 200}
    )
    (nodes / "recorder.yaml").write_text(yaml.safe_dump(recorder_cfg))
    joint_names = [limit["name"] for limit in follower_cfg["limits"]]
    (nodes / "left.yaml").write_text(
        yaml.safe_dump({**follower_cfg, "port": "/dev/mock-left"})
    )
    (nodes / "right.yaml").write_text(
        yaml.safe_dump({**follower_cfg, "port": "/dev/mock-right"})
    )
    (nodes / "leader_left.yaml").write_text(
        yaml.safe_dump({**leader_cfg, "port": "/dev/mock-leader-left"})
    )
    (nodes / "leader_right.yaml").write_text(
        yaml.safe_dump({**leader_cfg, "port": "/dev/mock-leader-right"})
    )

    for follower, default_pose in (("left", "ready"), ("right", "park")):
        pose_dir = project / "poses" / follower
        pose_dir.mkdir(parents=True)
        for name, value in (("ready", 2048), ("park", 2100)):
            (pose_dir / f"{name}.yaml").write_text(
                yaml.safe_dump(
                    {
                        "follower": follower,
                        "model": "rakuda2",
                        "unit": "dynamixel_count",
                        "pose": {joint: value for joint in joint_names},
                    }
                )
            )
        (nodes / f"ctrl_{follower}.yaml").write_text(
            yaml.safe_dump(
                {
                    "type": "joint",
                    "input": f"leader_{follower}",
                    "followers": [follower],
                    "alignment_tolerance": 300,
                    "max_speed": 2048,
                    "command_deadline_ms": 100,
                    "input_timeout_ms": 150,
                    "home": {
                        "pose": f"../poses/{follower}/{default_pose}.yaml",
                        "max_speed": 200,
                        "tolerance": 30,
                    },
                }
            )
        )

    path = project / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "repo_id": "local/dual",
                "output": str(tmp_path / "datasets"),
                "dataset_fps": 15,
                "mode": "mock",
                "inputs": {
                    "leader_left": "nodes/leader_left.yaml",
                    "leader_right": "nodes/leader_right.yaml",
                },
                "controllers": {
                    "ctrl_left": "nodes/ctrl_left.yaml",
                    "ctrl_right": "nodes/ctrl_right.yaml",
                },
                "followers": {
                    "left": "nodes/left.yaml",
                    "right": "nodes/right.yaml",
                },
                "sensors": {},
                "recorder": "nodes/recorder.yaml",
                "session": "nodes/session.yaml",
            }
        )
    )

    app = LauncherApp(
        path, LaunchPlan(mode="record", task="pick", seconds=3, home=True)
    )
    async with app.run_test(size=(100, 50)) as pilot:
        poses = app.query_one("#home-pose", OptionList)
        summary = app.query_one("#summary", Static)
        assert poses.option_count == 3
        assert poses.get_option_at_index(0).id == HOME_DEFAULT_ID
        assert "Each follower's default" in str(poses.get_option_at_index(0).prompt)
        assert poses.highlighted == 0
        assert "home: each follower's default" in str(summary.render())
        await pilot.press("ctrl+s")
    assert isinstance(app.return_value, LaunchPlan)
    assert app.return_value.home_pose is None

    app = LauncherApp(
        path, LaunchPlan(mode="record", task="pick", seconds=3, home=True)
    )
    async with app.run_test(size=(100, 50)) as pilot:
        poses = app.query_one("#home-pose", OptionList)
        poses.focus()
        await pilot.press("down", "enter")
        assert app._read().home_pose == "park"
        assert "home: park" in str(app.query_one("#summary", Static).render())
        await pilot.press("up", "enter")
        assert app._read().home_pose is None
        assert "home: each follower's default" in str(
            app.query_one("#summary", Static).render()
        )
        await pilot.press("ctrl+s")
    assert isinstance(app.return_value, LaunchPlan)
    assert app.return_value.home_pose is None
