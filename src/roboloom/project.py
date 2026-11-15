"""`roboloom init`: a project directory for one robot, copied from the robot's template.

Each robot package ships `template/` (config.yaml, node files, calibration maps, a README
with the setup steps). Values measured on one physical robot are `SET_...` placeholders
until the operator fills them; `config.parse_config` refuses to run with any left.

`roboloom init <robot> --update` brings an existing project up to the installed
template without touching what was measured or edited: it adds the files the project
lacks, replaces files nobody changed since they were copied, and for the others lists
what the template has that the project does not (`update_project`).
"""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

import yaml

from .config import CONFIG_FILE, PROJECT_ROOT
from .errors import ConfigError
from .version import version

# robot name -> package holding `template/`; a new robot adds one line
TEMPLATES = {"rakuda2": "roboloom.robots.rakuda2"}
# In the project: the roboloom that copied the template and each file's hash as it was
# copied, so `--update` can tell a file nobody touched from one that holds measurements.
RECORD = ".template.json"

GITIGNORE = """\
# roboloom: commit the YAML configuration; keep raw measurements, logs and data out
*.npz
logs/
datasets/
*.fifo
"""


def _template(robot: str) -> Traversable:
    if robot not in TEMPLATES:
        raise ConfigError(f"unknown robot {robot!r}; available: {', '.join(TEMPLATES)}")
    return resources.files(TEMPLATES[robot]).joinpath("template")


def _files(source: Traversable, prefix: str = "") -> dict[str, bytes]:
    """Every file of the template: path relative to it -> contents."""
    out: dict[str, bytes] = {}
    for item in sorted(source.iterdir(), key=lambda entry: entry.name):
        if item.name == "__pycache__":
            continue
        if item.is_dir():
            out.update(_files(item, f"{prefix}{item.name}/"))
        else:
            out[f"{prefix}{item.name}"] = item.read_bytes()
    return out


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record(target: Path, robot: str, files: dict[str, bytes]) -> None:
    note = {
        "roboloom": version(),
        "robot": robot,
        "files": {name: _sha(data) for name, data in files.items()},
    }
    (target / RECORD).write_text(json.dumps(note, indent=1) + "\n")


def init_project(robot: str, root: str | Path = PROJECT_ROOT) -> str:
    template = _files(_template(robot))
    root = Path(root)
    target = root / robot
    if target.exists():
        raise ConfigError(
            f"{target} already exists; nothing was changed (`roboloom init {robot} "
            "--update` adds what a newer template has)"
        )
    target.mkdir(parents=True)
    for name, data in template.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    _record(target, robot, template)
    ignore = root / ".gitignore"
    if not ignore.exists():
        ignore.write_text(GITIGNORE)
    return (
        f"created {target} ({len(template)} files)\n"
        f"next: fill the SET_ values, following {target / 'README.md'}\n"
        f"then: roboloom validate {robot} (`--mock` runs before anything is measured)"
    )


def _missing(template: object, project: object, where: str = "") -> list[str]:
    """Keys of the template's mappings (two levels deep) the project's file lacks."""
    if not isinstance(template, dict) or not isinstance(project, dict):
        return []
    out = []
    for key, value in template.items():
        name = f"{where}{key}"
        if key not in project:
            out.append(name)
        elif not where:  # one level down: options.<name>, max_age_ms.<node>, ...
            out += _missing(value, project[key], f"{name}.")
    return out


def update_project(robot: str, root: str | Path = PROJECT_ROOT) -> str:
    """Bring `root/robot` up to the installed template; returns what was done.

    - A file the project lacks is added.
    - A file that is still as it was copied (its hash in `.template.json`) and that the
      template changed is replaced.
    - Any other file is left alone: it was edited, or holds measured values. For a YAML
      file the keys the template has and the project lacks are listed, to copy by hand.

    A project made before `.template.json` existed has every file treated as edited."""
    template = _files(_template(robot))
    target = Path(root) / robot
    if not (target / CONFIG_FILE).is_file():
        raise ConfigError(
            f"{target} holds no {CONFIG_FILE}; create it with `roboloom init {robot}`"
        )
    record_path = target / RECORD
    copied = (
        json.loads(record_path.read_text())["files"] if record_path.exists() else {}
    )
    added, replaced, kept = [], [], []
    for name, data in template.items():
        path = target / name
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            added.append(name)
            continue
        current = _sha(path.read_bytes())
        if current == _sha(data):
            continue
        if copied.get(name) == current:  # nobody touched it since it was copied
            path.write_bytes(data)
            replaced.append(name)
        else:
            kept.append(name)
    # the hash a kept file was copied with stays: it is still not "as copied"
    note = {name: _sha(data) for name, data in template.items()}
    note.update({name: copied[name] for name in kept if name in copied})
    (target / RECORD).write_text(
        json.dumps({"roboloom": version(), "robot": robot, "files": note}, indent=1)
        + "\n"
    )

    lines = [f"{target}: compared with the template of roboloom {version()}"]
    for title, names in (("added", added), ("replaced (unchanged copies)", replaced)):
        if names:
            lines.append(f"{title}:")
            lines += [f"  {name}" for name in names]
    if kept:
        lines.append(
            "kept as they are (edited or measured); the template also has, to copy by "
            "hand:"
        )
        for name in kept:
            path = target / name
            extra: list[str] = []
            if path.suffix in (".yaml", ".yml"):
                try:
                    extra = _missing(
                        yaml.safe_load(template[name]), yaml.safe_load(path.read_text())
                    )
                except yaml.YAMLError:
                    extra = []
            lines.append(f"  {name}: {', '.join(extra) or 'other values or text'}")
        with resources.as_file(_template(robot)) as shipped:
            lines.append(f"the template's files: {shipped}")
    if not (added or replaced or kept):
        lines.append("nothing to do: every file is the template's")
    return "\n".join(lines)
