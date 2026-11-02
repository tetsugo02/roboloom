"""Launch options: node replacement, requirements and conflicts, dataset names, the CLI
words and the launcher."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
import yaml
from conftest import TEMPLATE, mock_project, rakuda2_tree
from rich.console import Console
from textual.widgets import Button, Checkbox

from roboloom.cli import _with_config
from roboloom.config import (
    load_experiment,
    option_changes,
    parse_experiment,
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
    cfg = parse_experiment(rakuda2_tree())
    assert cfg.options == () and set(cfg.sensors) == {"camera"}
    assert cfg.repo_id == "local/rakuda2"
    cfg = parse_experiment(rakuda2_tree(["digit"]))
    assert set(cfg.sensors) == {"camera", "digit_left", "digit_right"}
    assert cfg.repo_id == "local/rakuda2-digit"
    assert cfg.output.endswith("datasets/rakuda2-digit")
    tree = rakuda2_tree(["policy"])
    assert tree["options"] == ("digit", "policy")  # policy observes the DIGIT
    assert "leader" not in tree["inputs"] and set(tree["controllers"]) == {"policy"}


def test_option_changing_features_needs_its_own_dataset(tmp_path):
    project = mock_project(tmp_path / ".roboloom")
    path = project / "config.yaml"
    text = path.read_text()
    path.write_text(text.replace("    dataset: digit\n", ""))
    with pytest.raises(ConfigError, match="options.digit changes the recorded"):
        load_experiment(path, options=["digit"])
    assert load_experiment(path).options == ()  # off: nothing to compare


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
    assert _with_config(["commission", "robot"]) == ["commission", "robot"]
    assert _with_config(["commission", "rakuda2", "robot"]) == [
        "commission",
        "--config",
        "rakuda2",
        "robot",
    ]
    assert _with_config(["session", "home"]) == ["session", "home"]
    assert _with_config(["session", "rakuda2", "home"])[:3] == [
        "session",
        "--config",
        "rakuda2",
    ]


def test_the_hardware_flag_is_refused_with_a_hint(monkeypatch, capsys):
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


def test_last_choice_is_remembered(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"options": OPTIONS}))
    options = parse_options(OPTIONS)
    assert load_last(path, options) is None
    save_last(path, LaunchPlan("record", ("a", "b"), True, "pick", 5.0, 2, True))
    plan = load_last(path, options)
    assert plan == LaunchPlan("record", ("a", "b"), True, "pick", 5.0, 2, True)


@pytest.mark.asyncio
async def test_launcher_follows_requirements_and_conflicts(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"repo_id": "local/x", "options": OPTIONS}))
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


def test_template_declares_no_stale_experiment_files():
    assert not list(TEMPLATE.glob("experiment*.yaml"))


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

    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"repo_id": "local/x", "options": OPTIONS}))
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


@pytest.mark.asyncio
async def test_launcher_panes_resize_and_stack_when_narrow(tmp_path: Path):
    from roboloom.ui.launcher import RobotApp
    from roboloom.ui.splitter import Splitter

    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"repo_id": "local/x", "options": OPTIONS}))
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
