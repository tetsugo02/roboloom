from pathlib import Path

from roboloom.config import read_config

TEMPLATE = Path("src/roboloom/robots/rakuda2/template")


def rakuda2_tree(options: list[str] | None = None) -> dict:
    """The shipped Rakuda-2 template with these launch options (None: the defaults) and its
    device placeholders filled, as `init` users do."""
    tree = read_config(TEMPLATE / "config.yaml", options)
    if "leader" in tree["inputs"]:
        tree["inputs"]["leader"]["port"] = "/dev/serial/by-id/leader"
    tree["followers"]["follower"]["port"] = "/dev/serial/by-id/follower"
    for limit in tree["followers"]["follower"]["limits"]:
        limit["min"], limit["max"] = 1000, 3000
    serials = {"camera": "142122070848", "digit_left": "D1", "digit_right": "D2"}
    for sensor, serial in serials.items():
        if sensor in tree["sensors"]:
            tree["sensors"][sensor]["serial"] = serial
    return tree


def mock_project(root: Path) -> Path:
    """`roboloom init rakuda2` under `root`, filled and switched to mock mode, as files
    (the dora nodes read the configuration from disk). Returns the robot's project directory."""
    from roboloom.project import init_project

    init_project("rakuda2", root)
    filled = {
        "SET_LEADER_PORT": "/dev/leader",
        "SET_FOLLOWER_PORT": "/dev/follower",
        "SET_FOLLOWER_ARM_GOAL_CURRENT_mA": "1000",
        "SET_REALSENSE_SERIAL": "RS1",
        "SET_DIGIT_LEFT_SERIAL": "D1",
        "SET_DIGIT_RIGHT_SERIAL": "D2",
        "dataset_fps: 15": "mode: mock\ndataset_fps: 15",
        # the mock follower starts at 2048; a leader trigger resting there is aligned
        "rest: 2500": "rest: 2048",
    }
    used: set[str] = set()
    for path in (root / "rakuda2").rglob("*.yaml"):
        if path.name == "mock.yaml":
            continue  # the template's mock stand-ins are keyed by the SET_ names
        text = path.read_text()
        for old, new in filled.items():
            if old in text:
                used.add(old)
                text = text.replace(old, new)
        path.write_text(text)
    # a template edit must not silently leave a placeholder or the hardware mode in place
    assert used == set(filled), f"template no longer contains {set(filled) - used}"
    return root / "rakuda2"


def dual_mock(root: Path) -> Path:
    """examples/mock with a second leader, follower and joint controller (`left`), as
    files: two followers in one configuration. Returns the config.yaml path."""
    import shutil

    import yaml

    target = root / "dual"
    shutil.copytree("examples/mock", target, ignore=shutil.ignore_patterns("logs"))
    nodes = target / "nodes"
    for kind, name in (("leader", "left_leader"), ("follower", "left")):
        data = yaml.safe_load((nodes / f"{kind}.yaml").read_text())
        data["port"] = f"mock://{name}"
        (nodes / f"{name}.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    controller = yaml.safe_load((nodes / "controller.yaml").read_text())
    controller.update(input="left_leader", followers=["left"])
    (nodes / "left_controller.yaml").write_text(yaml.safe_dump(controller))
    recorder = yaml.safe_load((nodes / "recorder.yaml").read_text())
    recorder["max_age_ms"].update(left_leader=300, left=300)
    (nodes / "recorder.yaml").write_text(yaml.safe_dump(recorder))
    config = yaml.safe_load((target / "config.yaml").read_text())
    config["inputs"]["left_leader"] = "nodes/left_leader.yaml"
    config["controllers"]["left_controller"] = "nodes/left_controller.yaml"
    config["followers"]["left"] = "nodes/left.yaml"
    config["output"] = "datasets/dual"
    del config["options"]
    for sensor in ("digit_left", "digit_right", "audio"):
        del config["sensors"][sensor]
    path = target / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    return path
