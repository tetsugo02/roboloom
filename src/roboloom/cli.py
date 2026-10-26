"""The `roboloom` command: a thin layer over `roboloom.setup` and `roboloom.runtime.Session`."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .config import load_experiment, resolve_experiment
from .errors import Cancelled, RoboloomError
from .runtime.flow import build_flow


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
    sub.add_parser(
        "validate", help="check an experiment and its dora dataflow"
    ).add_argument("experiment")
    run_cmd = sub.add_parser(
        "run", help="start the dataflow with the operator screen (many episodes)"
    )
    run_cmd.add_argument("experiment")
    run_cmd.add_argument(
        "--hardware", action="store_true", help="explicitly allow opening real devices"
    )
    run_cmd.add_argument(
        "--plain",
        action="store_true",
        help="line-by-line prompt instead of the fixed screen",
    )
    rec = sub.add_parser(
        "record", help="record episodes of a fixed length (default: one) and exit"
    )
    rec.add_argument("experiment")
    rec.add_argument("--task", required=True, help="task text stored with every frame")
    rec.add_argument("--seconds", type=float, required=True)
    rec.add_argument("--episodes", type=int, default=1)
    rec.add_argument(
        "--hardware", action="store_true", help="explicitly allow opening real devices"
    )
    inf = sub.add_parser(
        "infer", help="run a policy experiment for fixed-length episodes"
    )
    inf.add_argument("experiment")
    inf.add_argument("--seconds", type=float, required=True)
    inf.add_argument("--episodes", type=int, default=1)
    inf.add_argument(
        "--policy", help="module:callable returning the policy (default: the YAML's)"
    )
    inf.add_argument(
        "--policy-kwargs", type=json.loads, default=None, help="JSON arguments"
    )
    inf.add_argument(
        "--task", default="", help="task given to the policy; with it, runs are saved"
    )
    inf.add_argument(
        "--hardware", action="store_true", help="explicitly allow opening real devices"
    )
    sess = sub.add_parser("session", help="send one command to a running `run`")
    sess.add_argument("experiment")
    sess.add_argument(
        "operation",
        choices=("start", "stop", "save", "discard", "estop", "release", "quit"),
    )
    sess.add_argument("task", nargs="?", default="")
    args = parser.parse_args()
    try:
        _dispatch(args)
    except Cancelled as exc:
        print(exc)
    except RoboloomError as exc:
        raise SystemExit(f"error: {exc}") from None


def _dispatch(args: argparse.Namespace) -> None:
    from . import setup
    from .operator import TerminalOperator

    operator = TerminalOperator()
    if getattr(args, "experiment", None):
        args.experiment = str(resolve_experiment(args.experiment))
    if args.command == "init":
        from .project import init_project

        print(init_project(args.robot, args.root))
        return
    if args.command == "probe":
        from .probe import probe

        print(probe(args.port, args.ids, args.baudrate))
        return
    if args.command == "commission":
        plan = setup.plan_commission(args.experiment, args.node, hardware=args.hardware)
        if not plan.changes:
            print(f"{args.node}: EEPROM already matches the configuration")
            return
        print("\n".join(plan.lines()))
        written = setup.apply_commission(plan, operator)
        print(f"{args.node}: wrote and read back {written} values")
        return
    if args.command == "watchdog-test":
        result = setup.watchdog_test(
            args.experiment,
            args.node,
            args.joint,
            operator,
            args.current_mA,
            hardware=args.hardware,
        )
        print("\n".join(result.lines()))
        return
    if args.command == "gravity-check":
        check = setup.gravity_check(
            args.experiment,
            args.node,
            args.group,
            operator,
            args.poses,
            args.scales,
            hardware=args.hardware,
        )
        print("\n".join(check.lines()))
        return
    if args.command == "tune-gravity":
        from .ui.tune import run

        tuning = setup.open_tuning(
            args.experiment, args.node, args.group, hardware=args.hardware
        )
        mode = "mock" if load_experiment(args.experiment).mock else "hardware"
        try:
            outcome = run(
                tuning,
                tuning.period_s,
                f"tune-gravity  {args.node}.{args.group}  ({mode})",
            )
        finally:
            tuning.close()
        print(f"{outcome}: {tuning.path}")
        return
    if args.command == "calibrate-joints":
        zeros = setup.calibrate_joints(args.calibration, operator, args.joints)
        print(
            f"recorded zeros for {len(zeros)} joints in {args.calibration}; "
            "check directions, then set confirmed: true"
        )
        return
    if args.command == "measure-travel":
        travel = setup.measure_travel(args.calibration, args.out, operator)
        print("\n".join(travel.lines()))
        return
    if args.command == "identify-gravity":
        fit = setup.identify_gravity(
            args.calibration,
            args.out,
            operator,
            data=args.data,
            collect=args.collect,
            hardware=args.hardware,
            delta=args.delta,
            max_rms_mA=args.max_rms_mA,
        )
        print("\n".join(fit.lines()))
        return
    from .runtime.session import Session, fifo_for, validate_flow

    cfg = load_experiment(args.experiment)
    if args.command == "session":
        send_session(
            fifo_for(cfg), " ".join(x for x in (args.operation, args.task) if x)
        )
        return
    if args.command == "validate":
        with tempfile.TemporaryDirectory(prefix="roboloom-flow-") as directory:
            validate_flow(cfg, Path(directory))
        print(f"Valid: {cfg.path} ({len(build_flow(cfg)['nodes'])} nodes)")
        return
    policy = getattr(args, "policy", None)
    session = Session.launch(
        cfg,
        hardware=args.hardware,
        policy=policy,
        policy_kwargs=getattr(args, "policy_kwargs", None),
    )
    try:
        if args.command == "record":
            from .ui.record import record

            record(session, args.task, args.seconds, args.episodes)
        elif args.command == "infer":
            from .ui.record import record

            # a task names the run and keeps it; without one nothing is saved
            record(
                session,
                args.task or "inference",
                args.seconds,
                args.episodes,
                keep=lambda _: bool(args.task),
            )
        elif not args.plain and sys.stdin.isatty() and sys.stdout.isatty():
            from .ui.live import LiveSession

            LiveSession(
                session.client, session.process, session.log_path, "roboloom"
            ).run()
        else:
            _plain_loop(session.client, session.process)
    finally:
        session.close()
        if session.process.returncode:
            print(
                f"dora exited with {session.process.returncode}; end of its log:\n"
                f"{session.log_path.read_text()[-4000:]}"
            )
        print(f"logs: {session.log_dir}")


def send_session(fifo: Path, line: str) -> None:
    fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
    try:
        os.write(fd, (line + "\n").encode())
    finally:
        os.close(fd)


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
