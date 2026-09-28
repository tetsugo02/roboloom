"""Validation, local dora launch, and terminal episode controls."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .config import load_experiment
from .flow import write_flow


def send_session(path: str, line: str) -> None:
    cfg = load_experiment(path)
    fifo = Path(cfg["experiment"]["output"]).resolve().with_suffix(".fifo")
    fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
    try:
        os.write(fd, (line + "\n").encode())
    finally:
        os.close(fd)


def main() -> None:
    parser = argparse.ArgumentParser(prog="roboloom")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "run", "session"):
        cmd = sub.add_parser(name)
        cmd.add_argument("experiment")
        if name == "run":
            cmd.add_argument(
                "--hardware",
                action="store_true",
                help="explicitly allow opening real devices",
            )
        if name == "session":
            cmd.add_argument(
                "operation",
                choices=("start", "stop", "save", "discard", "estop", "quit"),
            )
            cmd.add_argument("task", nargs="?", default="")
    args = parser.parse_args()
    cfg = load_experiment(args.experiment)
    if args.command == "session":
        send_session(
            args.experiment, " ".join(x for x in (args.operation, args.task) if x)
        )
        return
    dora = shutil.which("dora")
    if dora is None:
        raise SystemExit("dora CLI unavailable; install dependencies with uv sync")
    with tempfile.TemporaryDirectory(prefix="roboloom-flow-") as directory:
        flow = write_flow(cfg, Path(directory) / "flow.yaml")
        subprocess.run([dora, "validate", "--offline", str(flow)], check=True)
        if args.command == "validate":
            print(f"Valid: {cfg['path']} ({len(cfg['nodes'])} nodes)")
            return
        if cfg["experiment"]["mode"] == "hardware" and not args.hardware:
            raise SystemExit("hardware mode requires run --hardware")
        fifo = Path(cfg["experiment"]["output"]).resolve().with_suffix(".fifo")
        fifo.parent.mkdir(parents=True, exist_ok=True)
        if fifo.exists():
            raise SystemExit(f"session FIFO already exists: {fifo}")
        os.mkfifo(fifo, 0o600)
        try:
            report = Path(directory) / "report.jsonl"
            report.touch()
            process = subprocess.Popen(
                [
                    dora,
                    "run",
                    "--log-level",
                    "error",
                    "--env",
                    f"ROBOLOOM_SESSION_FIFO={fifo}",
                    "--env",
                    f"ROBOLOOM_REPORT_PATH={report}",
                    str(flow),
                ]
            )
            print("Commands: start <task>, stop, save, discard, estop, quit")
            line = ""
            while process.poll() is None:
                try:
                    line = input("roboloom> ").strip()
                except (KeyboardInterrupt, EOFError):
                    line = "quit"
                if not line:
                    continue
                previous_reports = (
                    len(report.read_text().splitlines()) if line == "save" else 0
                )
                for _ in range(30):
                    try:
                        send_session(args.experiment, line)
                        break
                    except OSError:
                        if process.poll() is not None:
                            break
                        time.sleep(0.1)
                if line == "save":
                    deadline = time.monotonic() + 120
                    while process.poll() is None and time.monotonic() < deadline:
                        lines = report.read_text().splitlines()
                        if len(lines) > previous_reports:
                            print(json.loads(lines[-1]), flush=True)
                            if "error" in json.loads(lines[-1]):
                                break
                            break
                        time.sleep(0.1)
                    else:
                        if process.poll() is None:
                            print(
                                "Save did not complete within 120 seconds", flush=True
                            )
                            continue
                if line == "quit":
                    break
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if process.returncode and line != "quit":
                raise SystemExit(process.returncode)
        finally:
            fifo.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
