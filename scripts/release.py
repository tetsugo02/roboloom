"""Release preparation and version consistency helper for roboloom.

Usage:
    uv run python scripts/release.py check [--tag v0.1.0]
    uv run python scripts/release.py set 0.1.0
    uv run python scripts/release.py bump minor [--dry-run]
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = Path("src/roboloom/agent_skills/roboloom/SKILL.md")
TAG_DOC_TARGETS = (
    Path("README.md"),
    Path("README.ja.md"),
    Path("docs"),
    Path("src/roboloom/agent_skills"),
    Path("src/roboloom/robots/rakuda2/template/README.md"),
)
REPO_GIT_MARKER = "github.com/tetsugo02/roboloom.git"
SKILL_VERSION_RE = re.compile(
    r'^(\s*roboloom-version:\s*["\']?)([^"\'\s]+)(["\']?\s*)$',
    re.MULTILINE,
)


def read_pyproject_version(root: Path) -> str:
    """Return ``project.version`` from ``pyproject.toml``."""
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = data.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("pyproject.toml is missing [project].version")
    return version


def read_lock_version(root: Path) -> str | None:
    """Return the locked ``roboloom`` version from ``uv.lock``, or ``None`` if absent."""
    lock_path = root / "uv.lock"
    if not lock_path.is_file():
        return None
    data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    for pkg in data.get("package", []):
        if pkg.get("name") == "roboloom":
            ver = pkg.get("version")
            return str(ver) if ver is not None else None
    return None


def read_skill_version(root: Path) -> str:
    """Return ``metadata.roboloom-version`` from the bundled Agent Skill ``SKILL.md``."""
    text = (root / SKILL_PATH).read_text(encoding="utf-8")
    match = SKILL_VERSION_RE.search(text)
    if not match:
        raise ValueError(f"roboloom-version not found in {SKILL_PATH}")
    return match.group(2)


def check_versions(
    root: Path, expected_tag: str | None = None
) -> tuple[str, list[str]]:
    """Verify version consistency across ``pyproject.toml``, ``uv.lock``, and ``SKILL.md``."""
    errors: list[str] = []
    pyproject_ver = read_pyproject_version(root)
    lock_ver = read_lock_version(root)
    skill_ver = read_skill_version(root)

    if lock_ver is not None and lock_ver != pyproject_ver:
        errors.append(
            f"uv.lock version ({lock_ver}) != pyproject.toml version ({pyproject_ver})"
        )
    if skill_ver != pyproject_ver:
        errors.append(
            f"{SKILL_PATH} roboloom-version ({skill_ver}) != pyproject.toml version ({pyproject_ver})"
        )
    if expected_tag is not None:
        expected = f"v{pyproject_ver}"
        if expected_tag != expected:
            errors.append(f"tag ({expected_tag}) != expected ({expected})")
    return pyproject_ver, errors


def update_skill_version(
    root: Path, new_version: str, *, dry_run: bool = False
) -> bool:
    """Update ``roboloom-version`` in ``SKILL.md``; return whether it changed."""
    path = root / SKILL_PATH
    text = path.read_text(encoding="utf-8")
    new_text, count = SKILL_VERSION_RE.subn(rf"\g<1>{new_version}\g<3>", text, count=1)
    if count != 1:
        raise ValueError(f"Could not update roboloom-version in {SKILL_PATH}")
    changed = new_text != text
    if changed and not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return changed


def _iter_tag_doc_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for rel in TAG_DOC_TARGETS:
        target = root / rel
        if target.is_file():
            files.append(target)
        elif target.is_dir():
            files.extend(sorted(p for p in target.rglob("*.md") if p.is_file()))
    return files


def update_tag_references(
    root: Path, old_version: str, new_version: str, *, dry_run: bool = False
) -> list[Path]:
    """Update ``--tag v<old_version>`` install snippets in docs, READMEs, and skills."""
    if old_version == new_version:
        return []
    pattern = re.compile(rf"--tag\s+v{re.escape(old_version)}(?![0-9A-Za-z._-])")
    updated: list[Path] = []
    for path in _iter_tag_doc_files(root):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        changed = False
        new_lines: list[str] = []
        for line in lines:
            if REPO_GIT_MARKER in line and pattern.search(line):
                new_line = pattern.sub(f"--tag v{new_version}", line)
                if new_line != line:
                    changed = True
                new_lines.append(new_line)
            else:
                new_lines.append(line)
        if changed:
            updated.append(path.relative_to(root))
            if not dry_run:
                path.write_text("".join(new_lines), encoding="utf-8")
    return updated


def _run_uv_version(
    root: Path, *, value: str | None = None, bump: str | None = None, dry_run: bool
) -> str:
    uv_bin = shutil.which("uv")
    if not uv_bin:
        raise RuntimeError(
            "uv is required on PATH to update pyproject.toml and uv.lock"
        )
    cmd = [uv_bin, "version", "--no-sync", "--short"]
    if dry_run:
        cmd.append("--dry-run")
    if bump is not None:
        cmd.extend(["--bump", bump])
    elif value is not None:
        cmd.append(value)
    else:
        raise ValueError("Either value or bump must be provided")
    res = subprocess.run(cmd, cwd=root, check=True, capture_output=True, text=True)
    lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("uv version returned empty output")
    return lines[-1]


def _cliff_command() -> list[str]:
    if cliff_bin := shutil.which("git-cliff"):
        return [cliff_bin]
    if uvx_bin := shutil.which("uvx"):
        return [uvx_bin, "git-cliff"]
    raise RuntimeError("Neither git-cliff nor uvx was found on PATH")


def generate_changelog(root: Path, tag: str, *, dry_run: bool = False) -> None:
    """Regenerate ``CHANGELOG.md`` via ``git-cliff`` for ``tag``."""
    cmd = [*_cliff_command(), "--config", "cliff.toml", "--tag", tag]
    if dry_run:
        subprocess.run([*cmd, "--unreleased"], cwd=root, check=True)
        return
    subprocess.run([*cmd, "-o", "CHANGELOG.md"], cwd=root, check=True)


def _prepare(
    root: Path,
    *,
    value: str | None,
    bump: str | None,
    changelog: bool,
    tag_docs: bool,
    dry_run: bool,
) -> int:
    old_version = read_pyproject_version(root)
    new_version = _run_uv_version(root, value=value, bump=bump, dry_run=dry_run)
    skill_changed = update_skill_version(root, new_version, dry_run=dry_run)
    doc_paths = (
        update_tag_references(root, old_version, new_version, dry_run=dry_run)
        if tag_docs
        else []
    )
    tag = f"v{new_version}"
    if changelog:
        generate_changelog(root, tag, dry_run=dry_run)

    prefix = "[dry-run] " if dry_run else ""
    print(f"{prefix}Version: {old_version} -> {new_version}")
    print(f"{prefix}{SKILL_PATH}: {'updated' if skill_changed else 'unchanged'}")
    if doc_paths:
        print(f"{prefix}Updated --tag references in:")
        for rel in doc_paths:
            print(f"  - {rel}")
    if not dry_run:
        print("\nNext steps:")
        print("  1. Review CHANGELOG.md and git diff")
        print(
            "  2. Run: uv run ruff check . && uv run mypy src && "
            'uv run pytest -m "not e2e" && uv run --group docs python scripts/docs.py build'
        )
        print(f"  3. Open a PR for release {tag}, merge to main, then run:")
        print(f"     git tag -a {tag} -m 'Release {tag}' && git push origin {tag}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root (default: checkout root)",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    check_p = sub.add_parser("check", help="Verify version consistency")
    check_p.add_argument("--tag", default=None, help="Expected git tag (e.g. v0.1.0)")

    for name, arg_name, arg_help in (
        ("set", "version", "Explicit PEP 440 version (e.g. 0.1.0, 0.2.0rc1)"),
        (
            "bump",
            "part",
            "Version component to bump (major, minor, patch, alpha, beta, rc, stable)",
        ),
    ):
        p = sub.add_parser(name, help=f"{name.capitalize()} release version and files")
        p.add_argument(arg_name, help=arg_help)
        p.add_argument("--no-changelog", action="store_true", help="Skip CHANGELOG.md")
        p.add_argument(
            "--no-tag-docs",
            action="store_true",
            help="Skip updating --tag vX.Y.Z snippets in README/docs/skills",
        )
        p.add_argument("--dry-run", action="store_true", help="Preview without writing")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root: Path = args.root.resolve()
    if args.action == "check":
        ver, errors = check_versions(root, expected_tag=args.tag)
        if errors:
            for err in errors:
                print(f"ERROR: {err}", file=sys.stderr)
            return 1
        print(
            f"OK: version {ver} is consistent across pyproject.toml, uv.lock, and SKILL.md"
        )
        return 0

    return _prepare(
        root,
        value=args.version if args.action == "set" else None,
        bump=args.part if args.action == "bump" else None,
        changelog=not args.no_changelog,
        tag_docs=not args.no_tag_docs,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
