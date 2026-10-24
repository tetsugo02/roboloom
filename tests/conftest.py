from pathlib import Path

from roboloom.config import read_experiment

TEMPLATE = Path("src/roboloom/robots/rakuda2/template")


def rakuda2_tree(name: str = "experiment") -> dict:
    """The shipped Rakuda-2 template with its device placeholders filled, as `init` users do."""
    tree = read_experiment(TEMPLATE / f"{name}.yaml")
    tree["inputs"]["leader"]["port"] = "/dev/serial/by-id/leader"
    tree["robots"]["robot"]["port"] = "/dev/serial/by-id/follower"
    for limit in tree["robots"]["robot"]["limits"]:
        limit["min"], limit["max"] = 1000, 3000
    serials = {"camera": "142122070848", "digit_left": "D1", "digit_right": "D2"}
    for sensor, serial in serials.items():
        if sensor in tree["sensors"]:
            tree["sensors"][sensor]["serial"] = serial
    return tree
