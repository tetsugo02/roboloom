"""Talk to a running dataflow: commands into the session FIFO, reports and status out of files."""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
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


class ViewerLinks:
    """Announce the current viewer URL once per change in a terminal session."""

    def __init__(self) -> None:
        self._url: str | None = None

    def messages(self, fields: Mapping[str, object]) -> tuple[str, ...]:
        url = fields.get("url")
        if not isinstance(url, str) or not url or url == self._url:
            return ()
        self._url = url
        lines: tuple[str, ...] = (f"viewer: open Rerun in a browser: {url}",)
        local_url = fields.get("local_url")
        if isinstance(local_url, str) and local_url:
            lines += (f"viewer: through SSH port forwarding: {local_url}",)
        return lines

    def from_status(self, status: dict | None) -> tuple[str, ...]:
        fields = (status or {}).get("nodes", {}).get("viewer", {}).get("fields", {})
        return self.messages(fields)


@contextmanager
def watch_viewer_links(client: SessionClient) -> Iterator[None]:
    """Print URL changes even while the plain CLI is waiting for input."""
    links = ViewerLinks()
    stop = threading.Event()

    def show() -> None:
        if messages := links.from_status(client.status()):
            print("\n".join(messages), flush=True)

    def watch() -> None:
        while not stop.wait(0.1):
            show()

    show()
    thread = threading.Thread(target=watch, name="viewer-links")
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()
        show()
