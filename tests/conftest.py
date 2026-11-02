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
    (the dora nodes read the experiment from disk). Returns the robot's project directory."""
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
    for path in (root / "rakuda2").rglob("*.yaml"):
        text = path.read_text()
        for old, new in filled.items():
            text = text.replace(old, new)
        path.write_text(text)
    return root / "rakuda2"
