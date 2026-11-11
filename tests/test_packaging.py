"""Dependency layout: one OpenCV distribution (headless, as LeRobot), DIGIT in its own extra."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str) -> dict:
    return tomllib.loads((ROOT / name).read_text())


def test_only_headless_opencv_is_required():
    project = load("pyproject.toml")["project"]
    requirements = [
        *project["dependencies"],
        *(r for extra in project["optional-dependencies"].values() for r in extra),
    ]
    assert "opencv-python-headless>=4.9,<4.14" in [
        r.split("#")[0].strip() for r in requirements
    ]
    # opencv-python and opencv-python-headless both install cv2/
    locked = {p["name"] for p in load("uv.lock")["package"]}
    assert "opencv-python-headless" in locked and "opencv-python" not in locked


def test_digit_extra_uses_the_headless_fork():
    extras = load("pyproject.toml")["project"]["optional-dependencies"]
    (digit,) = extras["digit"]
    assert digit.startswith(
        "digit-interface @ https://github.com/tetsugo02/digit-interface/releases/"
    )
    assert not any("digit-interface" in r for r in extras["hardware"])
    locked = {p["name"]: p for p in load("uv.lock")["package"]}
    deps = {d["name"] for d in locked["digit-interface"]["dependencies"]}
    assert deps == {"numpy", "opencv-python-headless", "pyudev"}
