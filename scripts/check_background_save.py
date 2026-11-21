"""Check background episode saving from a roboloom checkout.

    uv run python scripts/check_background_save.py compare [robot] --seconds 30 --episodes 5
    uv run python scripts/check_background_save.py limit [robot] --seconds 1
    uv run python scripts/check_background_save.py crash [robot] --seconds 20

Use --mock for a hardware-free run. Use --root to choose a dedicated test dataset.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import signal
import tempfile
import time
from dataclasses import asdict, dataclass, field, replace
from itertools import pairwise
from pathlib import Path
from statistics import fmean

from roboloom import EpisodeFailed, Session, SessionError, resolve_config
from roboloom.config import load_config, load_experiment, read_config
from roboloom.recording import episodes, spool
from roboloom.recording.check import check_dataset
from roboloom.recording.metrics import QUALITY
from roboloom.runtime.session import log_dir_for
from roboloom.version import version

REPO_ID = "local/bgsave-check"
WAIT_SECONDS = 300
LIMIT_WARNING = re.compile(
    r"(\d+) episodes are waiting to be saved \(max_pending_saves (\d+)\)"
)
RECOVERY_WARNING = "episodes left from an interrupted run are being saved"
CRASH_PROMPT = (
    "Support the leader and follower arms now and through shutdown and restart. "
    "Recording has stopped. Killing the recorder can leave the other nodes running "
    "until this script closes the dataflow. On shutdown, Rakuda2 position-mode joints "
    "can keep holding and current-mode joints can lose holding force. "
    "Type 'kill' to continue with SIGKILL and restart: "
)


def positive_seconds(text: str) -> float:
    seconds = float(text)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("seconds must be finite and positive")
    return seconds


def positive_episodes(text: str) -> int:
    count = int(text)
    if count < 1:
        raise argparse.ArgumentTypeError("episodes must be at least 1")
    return count


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "robot", nargs="?", help="robot name or config path (default: rakuda2)"
    )
    common.add_argument("--experiment", help="experiment name or YAML path")
    common.add_argument(
        "--with",
        dest="options",
        metavar="A,B",
        help="comma-separated options; replaces the experiment or robot defaults",
    )
    common.add_argument("--mock", action="store_true", help="run without hardware")
    common.add_argument(
        "--root", help="test dataset (default: datasets/<robot>-bgsave-check)"
    )
    common.add_argument("--yes", action="store_true", help="skip confirmations")
    sub = parser.add_subparsers(dest="command", required=True)
    compare = sub.add_parser(
        "compare", parents=[common], help="compare recording metrics"
    )
    compare.add_argument("--seconds", type=positive_seconds, default=30)
    compare.add_argument(
        "--episodes", type=positive_episodes, default=5, help="per group"
    )
    limit = sub.add_parser("limit", parents=[common], help="try to fill the save queue")
    limit.add_argument("--seconds", type=positive_seconds, default=1)
    crash = sub.add_parser(
        "crash", parents=[common], help="kill the recorder and check recovery"
    )
    crash.add_argument("--seconds", type=positive_seconds, default=20)
    return parser.parse_args(argv)


def prepare(args: argparse.Namespace) -> tuple[Path, dict]:
    source = (
        load_experiment(args.experiment) if args.experiment else load_experiment({})
    )
    robot = resolve_config(args.robot or source.robot or "rakuda2").resolve()
    options = (
        source.options
        if args.options is None
        else [name.strip() for name in args.options.split(",") if name.strip()]
    )
    root = (
        Path(args.root or f"datasets/{robot.parent.name}-bgsave-check")
        .expanduser()
        .resolve()
    )
    # Guard the default robot output, the selected options' output, and any experiment output
    # before substituting the test dataset. resolve() also catches aliases via symlinks.
    for tree in (
        read_config(robot),
        read_config(robot, options, experiment=replace(source, dataset={})),
    ):
        output = tree["settings"].get("output")
        if output and root == Path(output).resolve():
            raise ValueError(
                f"refusing --root {root}: it is the robot's configured output dataset"
            )
    if "root" in source.dataset and root == Path(source.dataset["root"]).resolve():
        raise ValueError(
            f"refusing --root {root}: it is the experiment's configured dataset"
        )
    experiment = {
        **asdict(source),
        "robot": str(robot),
        "dataset": {**source.dataset, "root": str(root), "repo_id": REPO_ID},
    }
    if options is not None:
        experiment["options"] = list(options)
    return root, experiment


@dataclass
class Run:
    args: argparse.Namespace
    log_dir: Path
    timeline: list[dict] = field(default_factory=list)
    measurements: list[dict] = field(default_factory=list)
    started: float = field(default_factory=time.monotonic)

    def event(self, message: str, **fields: object) -> None:
        self.timeline.append(
            {
                "elapsed_s": round(time.monotonic() - self.started, 3),
                "event": message,
                **fields,
            }
        )
        print(message, flush=True)

    def launch(self, experiment: dict, log_dir: Path) -> Session:
        return Session.launch(
            experiment=experiment,
            mock=self.args.mock or None,
            log_dir=log_dir,
            screen=False,
            operator=None if self.args.yes else "auto",
        )

    def record(self, session: Session, group: str, number: int) -> dict:
        task = f"bgsave {group} {number}"
        if not session.cfg.mock:
            print(
                f"{task}: keep the leader aligned with the follower before Start.",
                flush=True,
            )
        session.poll()
        pending = session.pending_saves
        session.start(task)
        session.poll()
        pending_after = session.pending_saves
        self.event(
            f"{task}: started with {pending} pending before Start and {pending_after} after",
            pending_before_start=pending,
            pending_after_start=pending_after,
        )
        # Keep the same fault checks as Session.record while using Start directly so
        # wait_ready cannot wait away the full-queue refusal or the overlap.
        deadline = time.monotonic() + self.args.seconds
        while True:
            check_alive(session)
            status = session.status()
            for name in session.cfg.controllers:
                fields = status.get(name, {}).get("fields", {})
                if fields.get("state") == "failed":
                    raise EpisodeFailed(
                        f"{name} failed: {fields.get('error') or 'see its log'}"
                    )
            for name in session.cfg.followers:
                fields = status.get(name, {}).get("fields", {})
                if fields.get("mode") in ("FAULT", "ESTOP"):
                    raise EpisodeFailed(
                        f"{name} is {fields['mode']}: {fields.get('reason', '')}"
                    )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.2, remaining))
        stopped = session.stop()
        entry = {
            "task": task,
            "group": group,
            "frames": stopped.frames,
            "metrics": stopped.metrics,
            "overlapped": pending > 0 and pending_after > 0,
        }
        self.measurements.append(entry)
        return entry

    def save(self, session: Session, entry: dict) -> None:
        result = session.save(wait=False)
        if not (result.pending or result.saved):
            raise SessionError(f"{result.task}: save was not accepted")
        self.event(
            f"{result.task}: {'queued' if result.pending else 'saved'} {result.frames} rows"
        )
        entry["save_accepted"] = True


def check_alive(session: Session) -> None:
    errors = session.node_errors()
    if not session.alive or errors:
        raise SessionError(
            f"dataflow failed; log {session.log_path}: " + "\n".join(errors)
        )


def drain(run: Run, session: Session, *, recovery: bool = False) -> None:
    """Observe recorder-reported progress, including saves with no local ticket."""
    deadline = time.monotonic() + WAIT_SECONDS
    warned = False
    while True:
        for report in session.reports():
            if report.get("command") == "saved" and "error" in report:
                raise SessionError(f"{report.get('task')}: {report['error']}")
            if report.get("level") == "warn" and RECOVERY_WARNING in report.get(
                "note", ""
            ):
                run.event(report["note"])
                warned = True
        check_alive(session)
        if session.pending_saves == 0 and (warned or not recovery):
            return
        if time.monotonic() >= deadline:
            problem = (
                "missing interrupted-run warning"
                if not warned and recovery
                else "saves still pending"
            )
            raise SessionError(
                f"{problem} after {WAIT_SECONDS} s; log {session.log_path}"
            )
        time.sleep(0.05)


def verify(run: Run, root: Path, before: int) -> None:
    report = check_dataset(root)
    ready, unfinished = spool.counts(root)
    run.event(
        f"dataset: {before} → {report.episodes} episodes; spool: {ready} ready, {unfinished} unfinished",
        episodes_before=before,
        episodes_after=report.episodes,
        ready=ready,
        unfinished=unfinished,
        problems=report.problems,
        notes=report.notes,
    )
    by_task = {
        record.get("task"): record
        for index, record in episodes.read(root).items()
        if index >= before
    }
    for entry in run.measurements:
        if record := by_task.get(entry["task"]):
            entry["saved_record"] = record
    expected = before + sum(
        bool(entry.get("save_accepted")) for entry in run.measurements
    )
    problems = list(report.problems)
    if report.episodes != expected:
        problems.append(
            f"expected {expected} dataset episodes, found {report.episodes}"
        )
    if ready or unfinished:
        problems.append("the episode spool still has ready or unfinished episodes")
    if problems:
        raise ValueError("; ".join(problems))


def compare_metrics(run: Run, quality: dict) -> tuple[str, str]:
    groups: dict[str, dict[str, list[float]]] = {"sequential": {}, "overlap": {}}
    for entry in run.measurements:
        metrics = entry.get("saved_record", {}).get("metrics")
        if not metrics:
            raise ValueError(f"{entry['task']}: saved episode metrics are missing")
        values = {
            f"{key}.{name}": rate
            for key in ("missing_rate", "action_missing_rate")
            for name, rate in metrics.get(key, {}).items()
        }
        if "action_valid_rate" in metrics:
            values["action_valid_rate"] = metrics["action_valid_rate"]
        for key in ("queue_ms", "latency_ms"):
            for stat in ("p99", "max"):
                values[f"{key}.{stat}"] = metrics[key][stat]
        for name, stats in metrics.get("control_interval_ms", {}).items():
            values[f"control_interval_ms.{name}.max"] = stats["max"]
        for key, value in values.items():
            groups[entry["group"]].setdefault(key, []).append(value)

    for group, metrics in groups.items():
        print(f"\n{group:<41} {'mean':>10} {'max':>10}")
        for key, values in sorted(metrics.items()):
            print(f"{key:<41} {fmean(values):>10.4g} {max(values):>10.4g}")

    warnings = []
    if not any(e["overlapped"] for e in run.measurements if e["group"] == "overlap"):
        warnings.append(
            "no overlap confirmed; saves finished before the next Start or its acknowledgment"
        )
    limits = {**QUALITY, **quality}
    for key, values in groups["overlap"].items():
        mean = fmean(values)
        if key.startswith(("missing_rate.", "action_missing_rate.")):
            if fmean(groups["sequential"][key]) + 0.01 < mean:
                warnings.append(f"{key} increased by more than 0.01")
            if key.startswith("missing_rate.") and mean > limits["max_missing_rate"]:
                warnings.append(
                    f"{key} mean {mean:.3g} exceeds {limits['max_missing_rate']:.3g}"
                )
            if (
                key.startswith("action_missing_rate.")
                and 1 - mean < limits["min_action_valid_rate"]
            ):
                warnings.append(f"{key} mean {mean:.3g} exceeds the quality limit")
        if key == "action_valid_rate" and mean < limits["min_action_valid_rate"]:
            warnings.append(
                f"action_valid_rate mean {mean:.3g} is below the quality limit"
            )
        if (
            key.startswith("control_interval_ms.")
            and max(values) > limits["max_interval_ms"]
        ):
            warnings.append(f"{key} {max(values):g} exceeds the quality limit")
    if warnings:
        return "WARN", "; ".join(warnings)
    return (
        "PASS",
        "overlap observed, saves completed, and recording metrics met the limits",
    )


def limit_check(run: Run, session: Session) -> tuple[str, str]:
    limit = session.cfg.recorder.get("max_pending_saves", 2)
    for number in range(1, limit + 4):
        try:
            entry = run.record(session, "limit", number)
        except SessionError as exc:
            warning = exc.report.get("warning", "")
            match = LIMIT_WARNING.search(warning)
            if not match:
                raise
            pending, reported_limit = map(int, match.groups())
            run.event(warning, pending_saves=pending, max_pending_saves=reported_limit)
            if pending < limit or reported_limit != limit:
                raise ValueError(
                    f"unexpected refusal at {pending} pending saves (configured limit {limit})"
                ) from exc
            session.wait_saves(WAIT_SECONDS)
            session.wait_ready(120)
            run.save(session, run.record(session, "limit-retry", 1))
            return (
                "PASS",
                f"Start refused at {pending}/{limit} pending saves and worked after draining",
            )
        run.save(session, entry)
    reason = (
        "saves finished before the next Start or its acknowledgment"
        if not any(e["overlapped"] for e in run.measurements)
        else "saves overlapped but the queue never reached its limit"
    )
    return "SKIP", f"{reason}; try a longer --seconds or more sensors"


def is_recorder(proc: Path, config: str) -> bool:
    argv = (proc / "cmdline").read_bytes().split(b"\0")
    return argv[-2:-1] == [os.fsencode(config)] and any(
        Path(os.fsdecode(script)).name == "node.py" and role == b"recorder"
        for script, role in pairwise(argv)
    )


def recorder_pid(session: Session) -> int:
    group = os.getpgid(session.process.pid)
    sid = os.getsid(session.process.pid)
    found = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdecimal():
            continue
        pid = int(proc.name)
        try:
            if proc.stat().st_uid != os.geteuid():
                continue
            # Dora 1.0.1 gives each node its own process group in the same OS session.
            if os.getpgid(pid) != group and os.getsid(pid) != sid:
                continue
            if is_recorder(proc, session.cfg.path):
                found.append(pid)
        except (ProcessLookupError, FileNotFoundError, PermissionError):
            continue
    if len(found) != 1:
        raise RuntimeError(
            f"expected one recorder process in group {group} or session {sid}, found {found}"
        )
    return found[0]


def interrupt_save(run: Run, session: Session) -> str | None:
    entry = run.record(session, "crash", 1)
    if not (session.cfg.mock or run.args.yes) and input(CRASH_PROMPT).strip() != "kill":
        run.save(session, entry)
        session.wait_saves(WAIT_SECONDS)
        run.event("operator declined SIGKILL; the episode was saved")
        return "operator declined SIGKILL"
    pid = recorder_pid(session)
    run.save(session, entry)
    session.poll()
    if session.pending_saves == 0:
        session.wait_saves(WAIT_SECONDS)
        run.event("save finished before SIGKILL")
        return "save finished before SIGKILL; try a longer --seconds"
    if os.getsid(pid) != os.getsid(session.process.pid) or not is_recorder(
        Path("/proc") / str(pid), session.cfg.path
    ):
        raise RuntimeError("the selected PID is no longer this dataflow's recorder")
    os.kill(pid, signal.SIGKILL)
    run.event(f"sent SIGKILL to recorder PID {pid}", recorder_pid=pid)
    try:
        session.close(release=False)
    except SessionError as exc:
        if session.alive:
            raise
        run.event(f"interrupted session closed with SessionError: {exc}")
    if session.alive:
        raise SessionError("the interrupted dataflow is still running")
    for error in session.node_errors():
        run.event(error)
    return None


def execute(run: Run) -> tuple[str, str]:
    args = run.args
    root, experiment = prepare(args)
    cfg = load_config(
        experiment["robot"],
        options=experiment.get("options"),
        mock=args.mock or None,
        experiment=load_experiment(experiment),
    )
    if not cfg.recorder.get("background_save", True):
        raise ValueError("this check requires background_save: true")
    # next to the robot's other logs, so the result outlives the temporary directory
    run.log_dir = log_dir_for(cfg)
    run.event(
        f"test dataset: {root}", root=str(root), mock=cfg.mock, options=cfg.options
    )
    skipped_crash = None
    with run.launch(experiment, run.log_dir) as session:
        run.log_dir = session.log_dir
        drain(run, session)
        before = session.episodes
        if not session.cfg.mock:
            print(
                "Align the leader with the follower before each episode and keep them aligned between episodes.",
                flush=True,
            )
        session.wait_ready(120)
        if args.command == "compare":
            for group in ("sequential", "overlap"):
                for number in range(1, args.episodes + 1):
                    if group == "sequential":
                        session.wait_saves(WAIT_SECONDS)
                        session.wait_ready(120)
                    try:
                        entry = run.record(session, group, number)
                    except SessionError as exc:
                        if group != "overlap" or not LIMIT_WARNING.search(
                            exc.report.get("warning", "")
                        ):
                            raise
                        run.event(exc.report["warning"])
                        session.wait_saves(WAIT_SECONDS)
                        session.wait_ready(120)
                        entry = run.record(session, group, number)
                    run.save(session, entry)
            session.wait_saves(WAIT_SECONDS)
        elif args.command == "limit":
            verdict = limit_check(run, session)
            session.wait_saves(WAIT_SECONDS)
        else:
            skipped_crash = interrupt_save(run, session)

    if args.command == "crash" and skipped_crash is None:
        ready, unfinished = spool.counts(root)
        run.event(
            f"after SIGKILL: {ready} ready, {unfinished} unfinished",
            ready=ready,
            unfinished=unfinished,
        )
        if not ready:
            raise ValueError("no ready episode remained after SIGKILL")
        recovery_log = run.log_dir / "recovery"
        run.event(f"relaunching the recorder; logs: {recovery_log}")
        with run.launch(experiment, recovery_log) as recovered:
            drain(run, recovered, recovery=True)
    verify(run, root, before)
    if args.command == "compare":
        return compare_metrics(run, cfg.quality)
    if args.command == "limit":
        return verdict
    if skipped_crash is not None:
        return "SKIP", skipped_crash
    return "PASS", "recovered exactly one episode and the spool is empty"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run = Run(args, Path(tempfile.mkdtemp(prefix="roboloom-bgsave-")))
    try:
        verdict, reason = execute(run)
    except KeyboardInterrupt:
        verdict, reason = "FAIL", "interrupted by operator"
    except Exception as exc:  # noqa: BLE001 - report startup and runtime failures
        verdict, reason = "FAIL", str(exc)
    result = run.log_dir / "background-save-result.json"
    result.write_text(
        json.dumps(
            {
                "arguments": vars(args),
                "roboloom_version": version(),
                "timeline": run.timeline,
                "episodes": run.measurements,
                "verdict": verdict,
                "reason": reason,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Result: {result}")
    print(f"{verdict} {' '.join(reason.split())}")
    return int(verdict == "FAIL")


if __name__ == "__main__":
    raise SystemExit(main())
