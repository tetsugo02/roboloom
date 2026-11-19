"""Run the checkout's background-save checks against the mock dataflow."""

from __future__ import annotations

import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from roboloom import load_config

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_background_save.py"
MOCK = REPO / "examples" / "mock"


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("command", "settings", "verdicts"),
    [
        ("compare", ["--seconds", "3", "--episodes", "1"], {"PASS", "WARN"}),
        ("limit", ["--seconds", "0.5"], {"PASS", "SKIP"}),
        ("crash", ["--seconds", "8"], {"PASS"}),
    ],
)
def test_mock_checks(
    tmp_path: Path, command: str, settings: list[str], verdicts: set[str]
) -> None:
    # Each dataflow creates a FIFO beside its configuration.
    config = (
        shutil.copytree(
            MOCK, tmp_path / "mock", ignore=shutil.ignore_patterns("logs", "*.fifo")
        )
        / "config.yaml"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            command,
            str(config),
            "--mock",
            "--root",
            str(tmp_path / "dataset"),
            *settings,
        ],
        cwd=tmp_path,
        capture_output=True,
        check=False,
        env={**os.environ, "TMPDIR": str(tmp_path)},
        text=True,
        timeout=180,
    )
    output = result.stdout.splitlines()
    assert result.returncode == 0, result.stdout + result.stderr
    assert output[-1].split()[0] in verdicts, result.stdout
    report_path = Path(
        next(
            line.removeprefix("Result: ")
            for line in output
            if line.startswith("Result: ")
        )
    )
    assert (report_path.parent / "dora.log").is_file()
    report = json.loads(report_path.read_text())
    assert report["verdict"] == output[-1].split()[0]
    assert report["arguments"]["command"] == command
    assert report["roboloom_version"]
    assert report["timeline"]
    assert report["episodes"] and all(entry["metrics"] for entry in report["episodes"])
    if command == "crash":
        assert any(
            "episodes left from an interrupted run are being saved" in item["event"]
            for item in report["timeline"]
        )
        assert (
            report["timeline"][-1]["episodes_before"] + 1
            == report["timeline"][-1]["episodes_after"]
        )


def test_refuses_robot_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = MOCK / "config.yaml"
    root = load_config(config).output
    monkeypatch.chdir(tmp_path)
    script = runpy.run_path(str(SCRIPT))
    args = script["parse_args"](["limit", str(config), "--mock", "--root", root])
    with pytest.raises(
        ValueError, match="refusing --root .* configured output dataset"
    ):
        script["prepare"](args)
