"""Fixed operator screen: rich Live view, keys read in cbreak mode on a thread.

The dora process's own output goes to a log file while the screen is up; lines
that look like errors are copied into the message panel.
"""

from __future__ import annotations

import os
import queue
import select
import signal
import subprocess
import sys
import termios
import threading
import time
import tty
from collections import deque
from pathlib import Path
from typing import Self

from rich.console import Console
from rich.live import Live
from rich.text import Text

from .client import SessionClient
from .render import describe_report, render

ALERT_WORDS = ("ERROR", "Error", "Traceback", "panicked", "exceeds maximum")
RELEASE_PROMPT = "Support the arms. Type yes to turn the follower torque off: "
QUIT_PROMPT = (
    "Support the arms of {}: it goes limp on quit. Enter quits, other text cancels: "
)


class KeyReader:
    """Characters from stdin on a daemon thread; the terminal is restored on exit."""

    def __init__(self) -> None:
        self.fd = sys.stdin.fileno()
        self.keys: queue.Queue[str] = queue.Queue()
        self.saved: list | None = None
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None

    def __enter__(self) -> Self:
        self.saved = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        self.thread = threading.Thread(target=self._run, daemon=True, name="keys")
        self.thread.start()
        return self

    def _run(self) -> None:
        while not self.stop.is_set():
            # poll, so the thread ends with the reader instead of eating the next key
            # (e.g. the Enter of a prompt after the screen)
            if not select.select([self.fd], [], [], 0.1)[0]:
                continue
            data = os.read(self.fd, 64)
            if not data:
                self.keys.put("\x04")
                return
            for ch in data.decode(errors="ignore"):
                self.keys.put(ch)

    def __exit__(self, *_) -> None:
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=1)
        if self.saved is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)


class LineEditor:
    """Minimal line editing: printable keys, Backspace, Ctrl-U, Enter; Ctrl-C/Ctrl-D mean quit."""

    def __init__(self) -> None:
        self.buffer = ""

    def feed(self, ch: str) -> str | None:
        if ch in ("\r", "\n"):
            line, self.buffer = self.buffer.strip(), ""
            return line
        if ch in ("\x03", "\x04"):
            self.buffer = ""
            return "quit"
        if ch in ("\x7f", "\b"):
            self.buffer = self.buffer[:-1]
        elif ch == "\x15":
            self.buffer = ""
        elif ch.isprintable():
            self.buffer += ch
        return None


def tail_alerts(path: Path, offset: int) -> tuple[list[Text], int]:
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read()
    except OSError:
        return [], offset
    lines = [
        x
        for x in data.decode(errors="ignore").splitlines()
        if any(w in x for w in ALERT_WORDS)
    ]
    return [Text(x[-200:], style="red") for x in lines], offset + len(data)


class LiveSession:
    """The operator screen for one running dataflow."""

    def __init__(
        self,
        client: SessionClient,
        process: subprocess.Popen,
        log_path: Path,
        title: str,
        limp_on_quit: list[str] | None = None,
    ):
        self.client, self.process, self.log_path, self.title = (
            client,
            process,
            log_path,
            title,
        )
        # actuated leaders go limp on quit: the operator supports them first
        self.limp_on_quit = limp_on_quit or []
        self.editor = LineEditor()
        self.messages: deque[Text] = deque(maxlen=8)
        self.confirm_release = False
        self.confirm_quit = False
        self.quitting_since: float | None = None
        self.log_offset = 0

    def prompt(self) -> Text:
        confirming = self.confirm_release or self.confirm_quit
        label = (
            RELEASE_PROMPT
            if self.confirm_release
            else QUIT_PROMPT.format(", ".join(self.limp_on_quit))
            if self.confirm_quit
            else "roboloom> "
        )
        return Text(label, style="bold yellow" if confirming else "bold") + Text(
            self.editor.buffer + "▏"
        )

    def submit(self, line: str) -> None:
        if self.confirm_quit:
            self.confirm_quit = False
            if line in ("", "quit"):  # Enter, or Ctrl-C again
                self.client.send("quit")
                self.messages.append(Text("> quit", style="dim"))
                self.quitting_since = time.monotonic()
            else:
                self.messages.append(Text("quit cancelled"))
            return
        if self.confirm_release:
            self.confirm_release = False
            if line == "yes":
                self.client.send("release")
                self.messages.append(Text("release sent", style="yellow"))
            else:
                self.messages.append(Text("release cancelled"))
            return
        if not line:
            return
        command, *rest = line.split()
        if command == "release":
            self.confirm_release = True
        elif command == "quit" and self.limp_on_quit:
            self.confirm_quit = True
        elif command not in ("start", "stop", "save", "discard", "estop", "quit"):
            self.messages.append(Text(f"unknown command: {command}", style="yellow"))
        elif command == "start" and not rest:
            self.messages.append(
                Text("start needs a task, e.g. start pick up the cup", style="yellow")
            )
        else:
            self.client.send(line)
            self.messages.append(Text(f"> {line}", style="dim"))
            if command == "quit":
                self.quitting_since = time.monotonic()

    def view(self, prompt: Text | None = None):
        return render(
            self.client.status(),
            self.messages,
            prompt or self.prompt(),
            title=self.title,
            log_path=self.log_path,
        )

    def step(self, keys: KeyReader) -> None:
        try:
            while True:
                line = self.editor.feed(keys.keys.get_nowait())
                if line is not None and self.quitting_since is None:
                    self.submit(line)
        except queue.Empty:
            pass
        self.messages.extend(describe_report(r) for r in self.client.new_reports())
        alerts, self.log_offset = tail_alerts(self.log_path, self.log_offset)
        self.messages.extend(alerts)
        if (
            self.quitting_since is not None
            and time.monotonic() - self.quitting_since > 10
        ):
            self.messages.append(
                Text("dataflow did not stop within 10 s; terminating", style="red")
            )
            self.process.terminate()
            self.quitting_since = time.monotonic()

    def run(self) -> None:
        keys = KeyReader()
        # Ctrl-C becomes `quit`; the dataflow runs in its own session and does not see the signal.
        previous = signal.signal(signal.SIGINT, lambda *_: keys.keys.put("\x03"))
        try:
            with (
                keys,
                Live(
                    self.view(), console=Console(), auto_refresh=False, transient=False
                ) as live,
            ):
                while self.process.poll() is None:
                    self.step(keys)
                    live.update(self.view(), refresh=True)
                    time.sleep(0.1)
                self.messages.extend(
                    describe_report(r) for r in self.client.new_reports()
                )
                live.update(
                    self.view(Text(f"dataflow exited ({self.process.returncode})")),
                    refresh=True,
                )
        finally:
            signal.signal(signal.SIGINT, previous)
