"""Validation, local dora launch, and terminal episode controls."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .config import load_experiment
from .runtime.flow import build_flow, write_flow


def send_session(path: str, line: str) -> None:
    cfg = load_experiment(path)
    fifo = Path(cfg.output).resolve().with_suffix(".fifo")
    fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
    try:
        os.write(fd, (line + "\n").encode())
    finally:
        os.close(fd)


def main() -> None:
    parser = argparse.ArgumentParser(prog="roboloom")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser(
        "init", help="create .roboloom/<robot>/ from the robot's configuration template"
    )
    init.add_argument("robot")
    init.add_argument("--root", default=".roboloom")
    probe_cmd = sub.add_parser("probe", help="read-only inspection of a Dynamixel bus")
    probe_cmd.add_argument("port")
    probe_cmd.add_argument(
        "--ids", type=lambda text: [int(x) for x in text.split(",")], default=None
    )
    probe_cmd.add_argument("--baudrate", type=int, default=1_000_000)
    com = sub.add_parser(
        "commission",
        help="write the Operating Mode / Current Limit a node expects (EEPROM)",
    )
    com.add_argument("experiment")
    com.add_argument("node")
    com.add_argument("--hardware", action="store_true", required=True)
    wd = sub.add_parser(
        "watchdog-test",
        help="bench test: does the Bus Watchdog stop a current-mode motor (torques it)",
    )
    wd.add_argument("experiment")
    wd.add_argument("node")
    wd.add_argument("joint")
    wd.add_argument("--current-mA", type=float, default=30.0)
    wd.add_argument("--hardware", action="store_true", required=True)
    gc = sub.add_parser(
        "gravity-check",
        help="release the arm with and without gravity compensation and compare (torques it)",
    )
    gc.add_argument("experiment")
    gc.add_argument("node")
    gc.add_argument("group", help="control group, e.g. right_arm")
    gc.add_argument("--poses", type=int, default=3)
    gc.add_argument(
        "--scales",
        type=lambda text: [float(x) for x in text.split(",")],
        default=[1.0, 0.0],
        help="multiples of the configured gains to try at each pose, e.g. 1,0,2,-2",
    )
    gc.add_argument("--hardware", action="store_true", required=True)
    tune = sub.add_parser(
        "tune-gravity",
        help="tune gravity compensation joint by joint with a live guide (torques the arm)",
    )
    tune.add_argument("experiment")
    tune.add_argument("node")
    tune.add_argument("group", help="gravity_comp group, e.g. right_arm")
    tune.add_argument("--hardware", action="store_true")
    calib = sub.add_parser(
        "calibrate-joints", help="record zero counts at the URDF zero pose (read-only)"
    )
    calib.add_argument("calibration")
    calib.add_argument("--joints", type=lambda text: text.split(","), default=None)
    travel = sub.add_parser(
        "measure-travel",
        help="record each joint's travel while moving the limp arm (read-only)",
    )
    travel.add_argument("calibration")
    travel.add_argument("--out", required=True)
    ident = sub.add_parser(
        "identify-gravity", help="collect holding currents and fit a gravity model"
    )
    ident.add_argument("calibration")
    ident.add_argument("--out", required=True)
    ident.add_argument(
        "--data", default=None, help="npz of holding currents (default: next to --out)"
    )
    ident.add_argument(
        "--collect",
        action="store_true",
        help="collect new poses first (needs --hardware)",
    )
    ident.add_argument("--hardware", action="store_true")
    ident.add_argument(
        "--delta", type=int, default=30, help="approach offset in counts"
    )
    ident.add_argument("--max-rms-mA", type=float, default=15.0)
    for name in ("validate", "run", "session"):
        cmd = sub.add_parser(name)
        cmd.add_argument("experiment")
        if name == "run":
            cmd.add_argument(
                "--hardware",
                action="store_true",
                help="explicitly allow opening real devices",
            )
            cmd.add_argument(
                "--plain",
                action="store_true",
                help="line-by-line prompt instead of the fixed screen",
            )
        if name == "session":
            cmd.add_argument(
                "operation",
                choices=(
                    "start",
                    "stop",
                    "save",
                    "discard",
                    "estop",
                    "release",
                    "quit",
                ),
            )
            cmd.add_argument("task", nargs="?", default="")
    args = parser.parse_args()
    if getattr(args, "experiment", None):
        from .config import resolve_experiment

        try:
            args.experiment = str(resolve_experiment(args.experiment))
        except FileNotFoundError as exc:
            raise SystemExit(str(exc)) from None
    if args.command == "init":
        from .project import init_project

        print(init_project(args.robot, args.root))
        return
    if args.command == "probe":
        from .probe import probe

        print(probe(args.port, args.ids, args.baudrate))
        return
    if args.command == "commission":
        from .tools import commission

        print(commission(args.experiment, args.node))
        return
    if args.command == "watchdog-test":
        from .tools import watchdog_test

        print(watchdog_test(args.experiment, args.node, args.joint, args.current_mA))
        return
    if args.command == "gravity-check":
        from .tools import gravity_check

        print(
            gravity_check(
                args.experiment, args.node, args.group, args.poses, args.scales
            )
        )
        return
    if args.command == "tune-gravity":
        from .tools import tune_gravity

        if not load_experiment(args.experiment).mock and not args.hardware:
            raise SystemExit("tune-gravity on hardware torques the arm; add --hardware")
        print(tune_gravity(args.experiment, args.node, args.group))
        return
    if args.command == "calibrate-joints":
        from .tools import calibrate_joints

        print(calibrate_joints(args.calibration, args.joints))
        return
    if args.command == "measure-travel":
        from .tools import measure_travel

        print(measure_travel(args.calibration, args.out))
        return
    if args.command == "identify-gravity":
        from .tools import Calibration, collect_holding_currents, fit_gravity

        cal = Calibration(args.calibration)
        out = Path(args.out)
        data = Path(args.data) if args.data else out.with_suffix(".npz")
        if args.collect:
            if not args.hardware:
                raise SystemExit("--collect torques the arm; add --hardware")
            from .tools import confirm

            if not confirm(
                f"{cal.data['port']}: output joints will hold each pose with torque on, moving {args.delta} counts."
            ):
                return
            collect_holding_currents(cal, data, args.delta)
        print(fit_gravity(cal, data, out, args.max_rms_mA))
        return
    try:
        cfg = load_experiment(args.experiment)
    except (
        ValueError,
        TypeError,
        FileNotFoundError,
    ) as exc:  # configuration, not a bug
        raise SystemExit(f"{args.experiment}: {exc}") from None
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
            print(f"Valid: {cfg.path} ({len(build_flow(cfg)['nodes'])} nodes)")
            return
        if not cfg.mock and not args.hardware:
            raise SystemExit("hardware mode requires run --hardware")
        fifo = Path(cfg.output).resolve().with_suffix(".fifo")
        fifo.parent.mkdir(parents=True, exist_ok=True)
        if fifo.exists():
            raise SystemExit(f"session FIFO already exists: {fifo}")
        os.mkfifo(fifo, 0o600)
        # next to the experiment, so a project keeps its own logs (ignored by git)
        log_dir = (
            Path(cfg.path).parent
            / "logs"
            / f"{Path(cfg.path).stem}-{time.strftime('%Y%m%d-%H%M%S')}"
        )

        log_dir.mkdir(parents=True, exist_ok=True)
        try:
            run_dataflow(
                dora, flow, fifo, Path(directory), args.plain, log_dir.resolve()
            )
        finally:
            fifo.unlink(missing_ok=True)


def run_dataflow(
    dora: str,
    flow: Path,
    fifo: Path,
    directory: Path,
    plain: bool,
    log_dir: Path | None = None,
) -> None:
    """Start `dora run` and drive it from the fixed screen, or line by line without a terminal."""
    from .ui.client import SessionClient

    report, status = directory / "report.jsonl", directory / "status.json"
    report.touch()
    live = not plain and sys.stdin.isatty() and sys.stdout.isatty()
    log_dir = log_dir or directory  # kept after the run: dora.log and device traces
    log_path = log_dir / "dora.log"
    command = [
        dora,
        "run",
        "--log-level",
        "error",
        "--env",
        f"ROBOLOOM_SESSION_FIFO={fifo}",
        "--env",
        f"ROBOLOOM_REPORT_PATH={report}",
        "--env",
        f"ROBOLOOM_STATUS_PATH={status}",
        "--env",
        f"ROBOLOOM_LOG_DIR={log_dir}",
        str(flow),
    ]
    client = SessionClient(fifo, report, status)
    if live:
        from .ui.live import LiveSession

        with open(log_path, "w") as log:
            # own session: terminal Ctrl-C reaches only this CLI, which sends `quit`
            process = subprocess.Popen(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            try:
                LiveSession(client, process, log_path, "roboloom").run()
            finally:
                _finish(process)
        if (
            process.returncode
        ):  # the log lives in a temporary directory; show its end now
            print(
                f"dora exited with {process.returncode}; end of its log:\n{log_path.read_text()[-4000:]}"
            )
        print(f"logs: {log_dir}")
        return
    process = subprocess.Popen(command)
    try:
        _plain_loop(client, process)
    finally:
        _finish(process)
    print(f"logs: {log_dir}")


def _finish(process: subprocess.Popen) -> None:
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def _plain_loop(client, process: subprocess.Popen) -> None:
    """Line input for pipes and non-terminal use; reports are printed as they arrive."""
    from .ui.render import describe_report

    print("Commands: start <task>, stop, save, discard, estop, release, quit")
    while process.poll() is None:
        try:
            line = input("roboloom> ").strip()
        except (KeyboardInterrupt, EOFError):
            line = "quit"
        for item in client.new_reports():
            print(describe_report(item).plain, flush=True)
        if not line:
            continue
        if (
            line == "release"
            and input(
                "Support the arms. Type yes to turn the follower torque off: "
            ).strip()
            != "yes"
        ):
            print("release cancelled")
            continue
        try:
            client.send(line)
        except OSError:
            if process.poll() is not None:
                break
            raise
        if line == "save":
            deadline = time.monotonic() + 120
            while process.poll() is None and time.monotonic() < deadline:
                items = client.new_reports()
                for item in items:
                    print(describe_report(item).plain, flush=True)
                if any(
                    "saved_frames" in x or x.get("command") == "save" for x in items
                ):
                    break
                time.sleep(0.1)
            else:
                if process.poll() is None:
                    print("Save did not complete within 120 seconds", flush=True)
        if line == "quit":
            break


if __name__ == "__main__":
    main()
