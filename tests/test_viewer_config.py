"""The optional viewer service: the option and the config.yaml key that turn it on,
its node file's validated settings, and the round trip the dora nodes reload it with."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml
from conftest import mock_project

from roboloom.config import load_config, parse_options, read_config
from roboloom.errors import ConfigError
from roboloom.runtime.node import config_from_env
from roboloom.runtime.session import config_env

DEFAULTS = {
    "rate_hz": 10,
    "compress_images": True,
    "serve": True,
    "ip": None,
    "port": None,
    "web_port": 9090,
    "bind": "0.0.0.0",
    "public_host": None,
    "cors_allow_origins": [],
    "server_memory_limit": "25%",
    "open_browser": False,
    "save": None,
    "memory_limit": "10%",
}


def _viewer_file(project: Path, **settings) -> None:
    (project / "nodes" / "viewer.yaml").write_text(yaml.safe_dump(settings))


def test_the_viewer_is_off_without_the_option(tmp_path):
    project = mock_project(tmp_path / ".roboloom")
    path = project / "config.yaml"
    assert load_config(path, mock=True).viewer is None
    assert read_config(path, mock=True)["viewer"] is None


@pytest.mark.usefixtures("rerun_present")
def test_the_option_turns_the_viewer_on_with_the_defaults(tmp_path):
    project = mock_project(tmp_path / ".roboloom")
    cfg = load_config(project / "config.yaml", options=["viewer"], mock=True)
    assert cfg.viewer == DEFAULTS
    assert cfg.options == ("viewer",)
    # no `dataset:` on the option: the dataset name stays as it was
    assert cfg.repo_id == "local/rakuda2"
    assert cfg.output.endswith("datasets/rakuda2")


@pytest.mark.usefixtures("rerun_present")
def test_the_viewer_combines_with_other_options(tmp_path):
    project = mock_project(tmp_path / ".roboloom")
    cfg = load_config(project / "config.yaml", options=["digit", "viewer"], mock=True)
    assert cfg.viewer == DEFAULTS
    assert cfg.repo_id == "local/rakuda2-digit"
    assert set(cfg.sensors) == {"camera", "digit_left", "digit_right"}


@pytest.mark.usefixtures("rerun_present")
def test_the_node_file_overrides_the_defaults(tmp_path):
    project = mock_project(tmp_path / ".roboloom")
    _viewer_file(
        project,
        rate_hz=5,
        compress_images=False,
        serve=False,
        ip="127.0.0.1",
        port=9876,
        web_port=9877,
        bind="127.0.0.1",
        public_host="robot.example",
        cors_allow_origins=["https://*.example.org", "http://viewer.example:9090"],
        server_memory_limit="256MiB",
        open_browser=True,
        save="view.rrd",
        memory_limit="25%",
    )
    cfg = load_config(project / "config.yaml", options=["viewer"], mock=True)
    assert cfg.viewer == {
        "rate_hz": 5,
        "compress_images": False,
        "serve": False,
        "ip": "127.0.0.1",
        "port": 9876,
        "web_port": 9877,
        "bind": "127.0.0.1",
        "public_host": "robot.example",
        "cors_allow_origins": ["https://*.example.org", "http://viewer.example:9090"],
        "server_memory_limit": "256MiB",
        "open_browser": True,
        # a relative save path resolves against the node file's directory
        "save": str((project / "nodes" / "view.rrd").resolve()),
        "memory_limit": "25%",
    }
    absolute = str(tmp_path / "elsewhere.rrd")
    _viewer_file(project, save=absolute)
    cfg = load_config(project / "config.yaml", options=["viewer"], mock=True)
    assert cfg.viewer == {**DEFAULTS, "save": absolute}
    _viewer_file(project, port=5555)
    cfg = load_config(project / "config.yaml", options=["viewer"], mock=True)
    assert cfg.viewer == {**DEFAULTS, "port": 5555}


@pytest.mark.usefixtures("rerun_present")
@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"rate_hzz": 10}, "unknown keys"),
        ({"rate_hz": 0}, "rate_hz"),
        ({"rate_hz": -5}, "rate_hz"),
        ({"rate_hz": "fast"}, "rate_hz"),
        ({"compress_images": "yes"}, "compress_images"),
        ({"serve": "yes"}, "serve"),
        ({"ip": "127.0.0.1"}, "ip and port together"),
        ({"serve": False, "port": 9876}, "ip and port together"),
        ({"port": 0}, "port"),
        ({"port": True}, "port"),
        ({"ip": "127.0.0.1", "port": 65536}, "port"),
        ({"ip": 127}, "ip"),
        ({"web_port": 0}, "web_port"),
        ({"web_port": 65536}, "web_port"),
        ({"web_port": True}, "web_port"),
        ({"web_port": None}, "web_port"),
        ({"bind": 0}, "bind"),
        ({"public_host": 123}, "public_host"),
        ({"cors_allow_origins": "http://viewer.example:9090"}, "cors_allow_origins"),
        ({"cors_allow_origins": None}, "cors_allow_origins"),
        ({"cors_allow_origins": [1]}, "cors_allow_origins"),
        ({"cors_allow_origins": [""]}, "cors_allow_origins"),
        ({"cors_allow_origins": ["   "]}, "cors_allow_origins"),
        ({"server_memory_limit": 25}, "server_memory_limit"),
        ({"open_browser": "yes"}, "open_browser"),
        ({"save": 3}, "save"),
        ({"memory_limit": 10}, "memory_limit"),
    ],
)
def test_bad_viewer_settings_are_refused(tmp_path, settings, message):
    project = mock_project(tmp_path / ".roboloom")
    _viewer_file(project, **settings)
    with pytest.raises(ConfigError, match=message):
        load_config(project / "config.yaml", options=["viewer"], mock=True)


def test_a_node_named_viewer_is_refused(tmp_path):
    from roboloom.config import parse_config

    project = mock_project(tmp_path / ".roboloom")
    tree = read_config(project / "config.yaml", mock=True)
    tree["followers"]["viewer"] = tree["followers"].pop("follower")
    with pytest.raises(ValueError, match="invalid node name 'viewer'"):
        parse_config(tree)


def test_the_viewer_needs_the_viz_extra(tmp_path, monkeypatch):
    project = mock_project(tmp_path / ".roboloom")
    real_find_spec = importlib.util.find_spec

    def find_spec(name, *args, **kwargs):
        if name == "rerun":
            return None
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr("roboloom.config.importlib.util.find_spec", find_spec)
    with pytest.raises(ConfigError, match="viz"):
        load_config(project / "config.yaml", options=["viewer"], mock=True)
    # off: Rerun is not needed at all
    assert load_config(project / "config.yaml", mock=True).viewer is None


@pytest.mark.usefixtures("rerun_present")
@pytest.mark.parametrize("robot", ["rakuda2", "piper-pika"])
def test_the_template_loads_with_the_viewer_in_mock(tmp_path, robot):
    from roboloom.project import init_project

    root = tmp_path / ".roboloom"
    init_project(robot, root)
    path = root / robot / "config.yaml"
    option_sets = (
        (["viewer"], ["policy", "viewer"]) if robot == "rakuda2" else (["viewer"],)
    )
    for options in option_sets:
        cfg = load_config(path, options=options, mock=True)
        assert cfg.mock and cfg.viewer == DEFAULTS


@pytest.mark.usefixtures("rerun_present")
def test_the_nodes_reload_the_viewer_the_option_turned_on(tmp_path):
    project = mock_project(tmp_path / ".roboloom")
    _viewer_file(project, rate_hz=5, save="view.rrd")
    cfg = load_config(project / "config.yaml", options=["viewer"], mock=True)
    child = config_from_env(cfg.path, config_env(cfg))
    assert child.options == cfg.options
    assert cfg.viewer is not None
    assert child.viewer == cfg.viewer


@pytest.mark.usefixtures("rerun_present")
def test_a_viewer_in_the_yaml_survives_the_round_trip(tmp_path):
    project = mock_project(tmp_path / ".roboloom")
    path = project / "config.yaml"
    config = yaml.safe_load(path.read_text())
    config["viewer"] = "nodes/viewer.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    _viewer_file(project, rate_hz=12.5, memory_limit="20%")
    cfg = load_config(path, options=[], mock=True)
    assert cfg.viewer == {**DEFAULTS, "rate_hz": 12.5, "memory_limit": "20%"}
    child = config_from_env(cfg.path, config_env(cfg))
    assert child.viewer == cfg.viewer


@pytest.mark.usefixtures("rerun_present")
def test_an_option_can_turn_a_configured_viewer_off(tmp_path):
    project = mock_project(tmp_path / ".roboloom")
    path = project / "config.yaml"
    config = yaml.safe_load(path.read_text())
    config["viewer"] = "nodes/viewer.yaml"
    config["options"]["no_view"] = {"set": {"viewer": None}}
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    assert load_config(path, mock=True).viewer == DEFAULTS
    assert load_config(path, options=["no_view"], mock=True).viewer is None


@pytest.mark.usefixtures("rerun_present")
def test_two_options_setting_the_viewer_differently_clash(tmp_path):
    project = mock_project(tmp_path / ".roboloom")
    path = project / "config.yaml"
    config = yaml.safe_load(path.read_text())
    config["options"]["a"] = {"set": {"viewer": "nodes/viewer.yaml"}}
    config["options"]["b"] = {"set": {"viewer": "nodes/viewer_other.yaml"}}
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    with pytest.raises(ConfigError, match="both set viewer"):
        load_config(path, options=["a", "b"], mock=True)
    # a dependent option refines the one it requires
    config["options"]["b"]["requires"] = ["a"]
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    (project / "nodes" / "viewer_other.yaml").write_text("rate_hz: 5\n")
    cfg = load_config(path, options=["b"], mock=True)
    assert cfg.viewer == {**DEFAULTS, "rate_hz": 5}


@pytest.mark.parametrize("set_", [{"viewer": 123}, {"viewer.other": "x.yaml"}])
def test_bad_viewer_option_keys_are_refused(set_):
    with pytest.raises(ConfigError):
        parse_options({"x": {"set": set_}})


@pytest.mark.usefixtures("rerun_present")
def test_mock_stand_ins_fill_the_viewer_too(tmp_path):
    project = mock_project(tmp_path / ".roboloom")
    _viewer_file(project, memory_limit="SET_RERUN_MEMORY")
    mock_yaml = project / "mock.yaml"
    mock_yaml.write_text(mock_yaml.read_text() + "SET_RERUN_MEMORY: 20%\n")
    cfg = load_config(project / "config.yaml", options=["viewer"], mock=True)
    assert cfg.viewer == {**DEFAULTS, "memory_limit": "20%"}


def test_viewer_is_an_allowed_top_level_key(tmp_path):
    project = mock_project(tmp_path / ".roboloom")
    path = project / "config.yaml"
    path.write_text("colour: red\n" + path.read_text())
    with pytest.raises(ConfigError, match=r"allowed: .*viewer"):
        read_config(path)
