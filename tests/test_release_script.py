"""Tests for release version consistency helpers and CLI `--version`."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from roboloom.cli import _with_config
from roboloom.cli import main as cli_main
from roboloom.version import version

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def rel():
    spec = importlib.util.spec_from_file_location(
        "release_script", REPO / "scripts" / "release.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _make_fake_repo(root: Path, ver: str = "0.1.0") -> None:
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "roboloom"\nversion = "{ver}"\n',
        encoding="utf-8",
    )
    (root / "uv.lock").write_text(
        f'[[package]]\nname = "roboloom"\nversion = "{ver}"\n',
        encoding="utf-8",
    )
    skill = root / "src" / "roboloom" / "agent_skills" / "roboloom" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        f'---\nname: roboloom\nmetadata:\n  roboloom-version: "{ver}"\n---\n',
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        "uv add git+https://github.com/tetsugo02/roboloom.git --tag v0.1.0 --extra rakuda2\n"
        "uv add git+https://github.com/tetsugo02/roboloom.git --tag <tag>\n",
        encoding="utf-8",
    )


def test_check_versions_passes_and_detects_mismatches(tmp_path, rel):
    _make_fake_repo(tmp_path, "0.1.0")

    ver, errors = rel.check_versions(tmp_path, expected_tag="v0.1.0")
    assert ver == "0.1.0"
    assert errors == []

    _, tag_errors = rel.check_versions(tmp_path, expected_tag="v0.2.0")
    assert len(tag_errors) == 1

    skill = tmp_path / rel.SKILL_PATH
    skill.write_text(
        '---\nname: roboloom\nmetadata:\n  roboloom-version: "0.0.9"\n---\n',
        encoding="utf-8",
    )
    _, skill_errors = rel.check_versions(tmp_path)
    assert any("SKILL.md" in err for err in skill_errors)


def test_update_skill_and_tag_references(tmp_path, rel):
    _make_fake_repo(tmp_path, "0.1.0")

    assert rel.update_skill_version(tmp_path, "0.2.0", dry_run=True) is True
    assert rel.read_skill_version(tmp_path) == "0.1.0"

    assert rel.update_skill_version(tmp_path, "0.2.0") is True
    assert rel.read_skill_version(tmp_path) == "0.2.0"

    updated = rel.update_tag_references(tmp_path, "0.1.0", "0.2.0")
    assert updated == [Path("README.md")]
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "--tag v0.2.0 --extra rakuda2" in readme
    assert "--tag <tag>" in readme


def test_repo_versions_are_currently_consistent(rel):
    assert rel.main(["--root", str(REPO), "check"]) == 0


def test_cli_version_flag_passes_through_with_config(capsys):
    assert _with_config(["--version"]) == ["--version"]
    assert _with_config(["-V"]) == ["-V"]

    with pytest.raises(SystemExit) as exc_info:
        cli_main(["--version"])
    assert exc_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"roboloom {version()}"
