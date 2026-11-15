"""Which roboloom this is: the package version, and the commit when it runs from a
git checkout (every commit of a checkout has the same package version)."""

from __future__ import annotations

import subprocess
from functools import cache
from importlib import metadata
from pathlib import Path


@cache
def version() -> str:
    """`0.1.0`, or `0.1.0+g1a2b3c4` (`.dirty` with uncommitted changes) in a checkout."""
    try:
        base = metadata.version("roboloom")
    except metadata.PackageNotFoundError:
        base = "0"
    # src layout: <checkout>/src/roboloom/version.py. An installed package may sit
    # inside another project's repository (its .venv): never report that one's commit.
    checkout = Path(__file__).resolve().parents[2]
    if not (checkout / ".git").exists():
        return base
    try:
        commit = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            [
                "git",
                "-C",
                str(checkout),
                "status",
                "--porcelain",
                "--untracked-files=no",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return base
    return f"{base}+g{commit}" + (".dirty" if dirty else "") if commit else base
