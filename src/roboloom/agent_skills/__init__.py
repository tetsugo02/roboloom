"""Agent Skills shipped with roboloom, for coding agents in projects that depend on it.

The `roboloom/` directory next to this file is an Agent Skill (agentskills.io: a
`SKILL.md` with YAML frontmatter plus `references/`). Claude Code, Codex, Cursor, Gemini
CLI and other agents read the same format; only the directory they look in differs.
`install` copies the skill of the installed roboloom into a project, so the instructions
always match the installed version; `check` reports a copy left behind by an update.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

from ..errors import ConfigError

SKILL = "roboloom"

# agent -> skills directory, relative to the project root; a new agent adds one line
TARGETS = {
    "agents": Path(".agents/skills"),  # Codex, Cursor, Gemini CLI and other agents
    "claude": Path(".claude/skills"),  # Claude Code
}


@dataclass(frozen=True)
class SkillCopy:
    """One installed copy of the skill and how it compares with the shipped one."""

    target: str
    path: Path
    state: str  # "up to date", "missing", "outdated"
    # files (relative to the skill) that are missing, changed or extra
    differing: tuple[str, ...] = ()

    def line(self) -> str:
        text = f"{self.target}: {self.path} {self.state}"
        if self.differing:
            text += f" ({', '.join(self.differing)})"
        return text


def skill_files() -> Traversable:
    """The skill directory inside the installed package."""
    return resources.files(__package__).joinpath(SKILL)


def path() -> str:
    """Where the shipped skill lives, for copying it by hand into another agent."""
    return str(skill_files())


def _walk(source: Traversable, prefix: str = "") -> Iterator[tuple[str, bytes]]:
    for item in sorted(source.iterdir(), key=lambda t: t.name):
        if item.name == "__pycache__":
            continue
        name = f"{prefix}{item.name}"
        if item.is_dir():
            yield from _walk(item, f"{name}/")
        else:
            yield name, item.read_bytes()


def _shipped() -> dict[str, bytes]:
    return dict(_walk(skill_files()))


def _installed(directory: Path) -> dict[str, bytes]:
    return {
        p.relative_to(directory).as_posix(): p.read_bytes()
        for p in sorted(directory.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


def _targets(targets: Iterable[str]) -> list[str]:
    chosen = list(dict.fromkeys(targets))
    unknown = [t for t in chosen if t not in TARGETS]
    if unknown or not chosen:
        raise ConfigError(
            f"unknown agent target {', '.join(unknown) or '(none)'}; "
            f"available: {', '.join(TARGETS)}"
        )
    return chosen


def _compare(target: str, directory: Path, shipped: dict[str, bytes]) -> SkillCopy:
    if not directory.exists():
        return SkillCopy(target, directory, "missing")
    found = _installed(directory)
    differing = tuple(
        sorted(
            n for n in shipped.keys() | found.keys() if shipped.get(n) != found.get(n)
        )
    )
    return SkillCopy(
        target, directory, "outdated" if differing else "up to date", differing
    )


def check(
    root: str | Path = ".", targets: Iterable[str] = tuple(TARGETS)
) -> list[SkillCopy]:
    """Compare the copies in a project with the shipped skill; writes nothing."""
    shipped = _shipped()
    return [
        _compare(t, Path(root) / TARGETS[t] / SKILL, shipped) for t in _targets(targets)
    ]


def install(
    root: str | Path = ".",
    targets: Iterable[str] = tuple(TARGETS),
    *,
    force: bool = False,
) -> list[SkillCopy]:
    """Copy the shipped skill into `<root>/<agent skills dir>/roboloom/` for each target.

    A copy that already matches is left alone. A copy that differs (an older roboloom, or
    local edits) is refused unless `force`, which replaces only the `roboloom/` skill
    directory; other skills next to it are never touched. Returns the state of each copy
    before installing."""
    shipped = _shipped()
    copies = [
        _compare(t, Path(root) / TARGETS[t] / SKILL, shipped) for t in _targets(targets)
    ]
    outdated = [c for c in copies if c.state == "outdated"]
    if outdated and not force:
        raise ConfigError(
            "the installed skill differs from this roboloom's; nothing was changed. "
            "Pass --force (force=True) to replace it:\n"
            + "\n".join(c.line() for c in outdated)
        )
    for copy in copies:
        if copy.state == "up to date":
            continue
        for name in _installed(copy.path) if copy.path.exists() else {}:
            if name not in shipped:
                (copy.path / name).unlink()
        for name, data in shipped.items():
            out = copy.path / name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
        for directory in sorted(copy.path.rglob("*"), reverse=True):
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
    return copies
