"""Actual dora/mock dataflow operated through the Textual backend and Pilot."""

from __future__ import annotations

import asyncio
import shutil
import sys
import time
from pathlib import Path

import pytest
from conftest import mock_project

from roboloom import Session
from roboloom.cli import main
from roboloom.ui.app import OperatorApp
from roboloom.ui.backend import RecordingPlan, SessionBackend
from roboloom.ui.command import CommandInput


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("dora") is None, reason="needs dora")
async def test_textual_records_and_saves_a_mock_episode(tmp_path: Path):
    project = mock_project(tmp_path / ".roboloom")
    backend = SessionBackend(
        lambda: Session.launch(
            project / "experiment.yaml", screen=False, operator=None
        ),
        mode="record",
        recording=RecordingPlan("Pilot collection", 0.6),
    )
    app = OperatorApp(backend)
    async with app.run_test(size=(80, 24)) as pilot:
        deadline = time.monotonic() + 40
        while not any(
            o.command == "start" and o.enabled for o in app.snapshot.operations
        ):
            assert time.monotonic() < deadline, app.snapshot
            await asyncio.sleep(0.1)
        await pilot.press("enter")
        deadline = time.monotonic() + 40
        while app.snapshot.phase != "complete":
            assert time.monotonic() < deadline, app.snapshot
            await asyncio.sleep(0.1)
        assert len(app.screen_stack) == 2
        assert backend.session is not None and backend.session.episodes == 1
        assert backend.session.screen is None and backend.session.operator is None
        assert app.query_one(CommandInput).history == []
        await pilot.press("down", "enter")
        deadline = time.monotonic() + 20
        while backend.session.alive:
            assert time.monotonic() < deadline
            await asyncio.sleep(0.1)
    assert not (project / "datasets" / "rakuda2.fifo").exists()


def test_non_tty_tuning_is_rejected_before_open(tmp_path: Path, monkeypatch):
    from roboloom import setup

    project = mock_project(tmp_path / ".roboloom")
    opened: list[bool] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        opened.append(True)
        raise AssertionError("device opened without a terminal")

    monkeypatch.setattr(setup, "open_tuning", forbidden)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "roboloom",
            "tune-gravity",
            str(project / "experiment_gravity.yaml"),
            "leader",
            "right_arm",
        ],
    )
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(SystemExit, match="requires an interactive terminal"):
        main()
    assert not opened


@pytest.mark.parametrize("command", ["record", "infer"])
def test_plain_flags_are_accepted(command: str, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["roboloom", command, "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    assert "--plain" in capsys.readouterr().out


@pytest.mark.skipif(shutil.which("dora") is None, reason="needs dora")
def test_api_auto_screen_leaves_input_to_the_script(
    tmp_path: Path, monkeypatch, capsys
):
    from io import StringIO

    class ScriptInput(StringIO):
        calls = 0

        def isatty(self) -> bool:
            return True

        def readline(self, size: int | None = -1) -> str:
            self.calls += 1
            return super().readline(-1 if size is None else size)

        def read(self, size: int | None = -1) -> str:
            raise AssertionError("the status screen consumed stdin")

    project = mock_project(tmp_path / ".roboloom")
    stdin = ScriptInput("answer from script\n")
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    with Session.launch(project / "experiment.yaml", operator=None) as session:
        assert session.screen is not None
        print("script output")
        assert input("script prompt: ") == "answer from script"
        time.sleep(0.2)
        assert stdin.calls == 1
    assert stdin.calls == 1
    assert "script output" in capsys.readouterr().out
