"""`roboloom init`: a project directory for one robot, copied from the robot's template.

Each robot package ships `template/` (experiments, node files, calibration maps, a README
with the setup steps). Values measured on one physical robot are `SET_...` placeholders
until the operator fills them; `config.parse_experiment` refuses to run with any left.
"""

from __future__ import annotations

from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

from .config import PROJECT_ROOT
from .errors import ConfigError

# robot name -> package holding `template/`; a new robot adds one line
TEMPLATES = {"rakuda2": "roboloom.robots.rakuda2"}

GITIGNORE = """\
# roboloom: commit the YAML configuration; keep raw measurements, logs and data out
*.npz
logs/
datasets/
*.fifo
"""


def _copy(source: Traversable, target: Path) -> list[Path]:
    written = []
    for item in source.iterdir():
        if item.name == "__pycache__":
            continue
        out = target / item.name
        if item.is_dir():
            out.mkdir(parents=True, exist_ok=True)
            written += _copy(item, out)
        else:
            out.write_bytes(item.read_bytes())
            written.append(out)
    return written


def init_project(robot: str, root: str | Path = PROJECT_ROOT) -> str:
    if robot not in TEMPLATES:
        raise ConfigError(f"unknown robot {robot!r}; available: {', '.join(TEMPLATES)}")
    root = Path(root)
    target = root / robot
    if target.exists():
        raise ConfigError(f"{target} already exists; nothing was changed")
    target.mkdir(parents=True)
    files = _copy(resources.files(TEMPLATES[robot]).joinpath("template"), target)
    ignore = root / ".gitignore"
    if not ignore.exists():
        ignore.write_text(GITIGNORE)
    return (
        f"created {target} ({len(files)} files)\n"
        f"next: fill the SET_ values, following {target / 'README.md'}\n"
        f"then: roboloom validate {robot}"
    )
