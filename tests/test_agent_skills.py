"""The Agent Skill shipped for coding agents: format, links, drift from the API and CLI,
and installing it into a project."""

import ast
import importlib
import importlib.util
import re
import tomllib
from pathlib import Path

import pytest
import yaml

from roboloom import agent_skills
from roboloom.cli import main
from roboloom.errors import ConfigError

REPO = Path(__file__).resolve().parents[1]
SKILL = Path(agent_skills.path())
PAGES = sorted(SKILL.rglob("*.md"))


def _frontmatter() -> dict:
    text = (SKILL / "SKILL.md").read_text()
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "SKILL.md starts with YAML frontmatter"
    return yaml.safe_load(match.group(1))


def test_frontmatter_follows_the_agent_skills_format():
    meta = _frontmatter()
    assert meta["name"] == SKILL.name == "roboloom"
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", meta["name"])
    assert 0 < len(meta["description"]) <= 1024
    assert len((SKILL / "SKILL.md").read_text().splitlines()) < 500
    version = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["version"]
    assert meta["metadata"]["roboloom-version"] == version


@pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p.relative_to(SKILL)))
def test_relative_links_point_to_existing_files(page):
    for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", page.read_text()):
        if re.match(r"[a-z]+:", target):
            continue
        assert (page.parent / target).resolve().is_file(), f"{page.name} -> {target}"


def _code_blocks(languages: tuple[str, ...]):
    for page in PAGES:
        fence, lines = None, []
        for line in page.read_text().splitlines():
            if fence is None and line.startswith("```"):
                fence, lines = line[3:].strip(), []
            elif fence is not None and line.strip() == "```":
                if fence in languages:
                    yield page, "\n".join(lines)
                fence = None
            elif fence is not None:
                lines.append(line)


def test_python_examples_parse_and_their_roboloom_imports_exist():
    for page, block in _code_blocks(("python",)):
        tree = ast.parse(block, filename=str(page))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ImportFrom) and node.module):
                continue
            if node.module.split(".")[0] != "roboloom":
                continue
            try:
                module = importlib.import_module(node.module)
            except ModuleNotFoundError as error:  # an optional extra (lerobot, ...)
                if (error.name or "").startswith("roboloom"):
                    raise
                continue
            for alias in node.names:
                assert hasattr(module, alias.name) or importlib.util.find_spec(
                    f"{node.module}.{alias.name}"
                ), f"{page.name}: from {node.module} import {alias.name}"


def _subcommands(capsys) -> set[str]:
    with pytest.raises(SystemExit):
        main(["--help"])
    usage = capsys.readouterr().out
    match = re.search(r"\{([a-z0-9,-]+)\}", usage)
    assert match, usage
    return set(match.group(1).split(","))


def test_cli_commands_in_the_skill_exist(capsys):
    commands = _subcommands(capsys)
    used = set()
    for page in PAGES:  # inline `roboloom <command> ...`
        used |= set(
            re.findall(r"`(?:uv run )?roboloom ([a-z][a-z0-9-]+)", page.read_text())
        )
    for _, block in _code_blocks(("bash", "sh", "")):
        used |= set(
            re.findall(r"^(?:uv run )?roboloom ([a-z][a-z0-9-]+)", block, re.MULTILINE)
        )
    robots = {"rakuda2"}  # `roboloom rakuda2` opens the launcher for that robot
    unknown = used - commands - robots
    assert not unknown, f"commands in the skill but not in the CLI: {sorted(unknown)}"


def test_install_check_and_force(tmp_path):
    other = tmp_path / ".claude" / "skills" / "other" / "SKILL.md"
    other.parent.mkdir(parents=True)
    other.write_text("someone else's skill")

    assert {c.state for c in agent_skills.check(tmp_path)} == {"missing"}
    agent_skills.install(tmp_path)
    for directory in (".agents/skills/roboloom", ".claude/skills/roboloom"):
        assert (tmp_path / directory / "SKILL.md").is_file()
        assert (tmp_path / directory / "references" / "cli.md").is_file()
    assert {c.state for c in agent_skills.check(tmp_path)} == {"up to date"}
    assert {c.state for c in agent_skills.install(tmp_path)} == {"up to date"}

    copy = tmp_path / ".claude" / "skills" / "roboloom"
    (copy / "SKILL.md").write_text("old")
    (copy / "references" / "removed.md").write_text("from an older roboloom")
    (states,) = [c for c in agent_skills.check(tmp_path) if c.target == "claude"]
    assert states.state == "outdated"
    assert states.differing == ("SKILL.md", "references/removed.md")
    with pytest.raises(ConfigError, match="--force"):
        agent_skills.install(tmp_path)
    assert (copy / "SKILL.md").read_text() == "old"  # nothing changed

    agent_skills.install(tmp_path, force=True)
    assert {c.state for c in agent_skills.check(tmp_path)} == {"up to date"}
    assert not (copy / "references" / "removed.md").exists()
    assert other.read_text() == "someone else's skill"


def test_install_one_agent_and_reject_unknown(tmp_path):
    agent_skills.install(tmp_path, ["claude"])
    assert (tmp_path / ".claude/skills/roboloom/SKILL.md").is_file()
    assert not (tmp_path / ".agents").exists()
    with pytest.raises(ConfigError, match="unknown agent target"):
        agent_skills.install(tmp_path, ["nope"])


def test_cli_install_then_check(tmp_path, capsys):
    with pytest.raises(SystemExit):
        main(["skills", "check", "--root", str(tmp_path)])
    main(["skills", "install", "--root", str(tmp_path)])
    assert "installed" in capsys.readouterr().out
    main(["skills", "check", "--root", str(tmp_path)])
    assert capsys.readouterr().out.count("up to date") == 2
    main(["skills", "path"])
    assert capsys.readouterr().out.strip() == str(SKILL)


def test_repository_link_for_npx_skills_points_at_the_packaged_skill():
    link = REPO / "skills" / "roboloom"
    assert link.is_symlink()
    assert link.resolve() == SKILL.resolve()
