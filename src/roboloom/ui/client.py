"""Talk to a running dataflow: commands into the session FIFO, reports and status out of files."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


class SessionClient:
    def __init__(self, fifo: Path, report: Path, status: Path):
        self.fifo, self.report, self.status_path = fifo, report, status
        self.offset = 0

    def send(self, line: str, attempts: int = 30) -> None:
        """Write one command line; the session node may still be starting, so retry briefly."""
        for k in range(attempts):
            try:
                fd = os.open(self.fifo, os.O_WRONLY | os.O_NONBLOCK)
            except OSError:
                if k == attempts - 1:
                    raise
                time.sleep(0.1)
                continue
            try:
                os.write(fd, (line + "\n").encode())
            finally:
                os.close(fd)
            return

    def new_reports(self) -> list[dict]:
        try:
            with open(self.report) as f:
                f.seek(self.offset)
                lines = f.readlines()
                complete = [x for x in lines if x.endswith("\n")]
                self.offset += sum(len(x.encode()) for x in complete)
        except OSError:
            return []
        out = []
        for line in complete:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"error": f"unreadable report: {line.strip()}"})
        return out

    def status(self) -> dict | None:
        try:
            return json.loads(self.status_path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
