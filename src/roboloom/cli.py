"""The `roboloom` command: a thin layer over `roboloom.setup` and `roboloom.runtime.Session`."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from .config import (
    INFER_OPTION,
    Option,
    RobotConfig,
    is_configuration,
    load_config,
    parse_options,
    resolve_config,
    select_options,
)
from .errors import Cancelled, ConfigError, RoboloomError
from .runtime.flow import build_flow

if TYPE_CHECKING:
    from .ui.launcher import LaunchPlan

# Subcommands whose first word may name the configuration (a robot under .roboloom/ or a
# YAML file). Commands without other positional words always read it as one.
CONFIGURED = {
    "launch",
    "run",
    "record",
    "infer",
    "validate",
    "session",
    "commission",
    "watchdog-test",
    "gravity-check",
    "tune-gravity",
    "capture-pose",
}
ONLY_CONFIG = {"launch", "run", "record", "infer", "validate"}
SESSION_OPERATIONS = (
    "start",
    "stop",
    "save",
    "discard",
    "estop",
    "release",
    "home",
    "quit",
)


class _Removed(argparse.Action):
    """`--hardware` is gone: real devices are the default; say so instead of ignoring it."""

    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, dest, nargs=0, help=argparse.SUPPRESS)

    def __call__(self, parser, namespace, values, option_string=None):
        parser.error(
            "--hardware is no longer needed: real devices are the default; "
            "pass --mock for mock devices"
        )


def _names(text: str) -> list[str]:
    return [n.strip() for n in text.split(",") if n.strip()]


def _with_config(argv: list[str]) -> list[str]:
    """Move an optional leading configuration word into `--config`, so `roboloom run`,
    `roboloom run rakuda2` and `roboloom commission follower` all parse."""
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv = ["launch", *argv]  # `roboloom`, `roboloom --mock`: the launcher
    elif argv[0] not in CONFIGURED and is_configuration(argv[0]):
        argv = ["launch", *argv]  # `roboloom rakuda2`
    command, rest = argv[0], argv[1:]
    if command not in CONFIGURED or not rest or rest[0].startswith("-"):
        return argv
    word = rest[0]
    if (
        command in ONLY_CONFIG
        or (command == "session" and word not in SESSION_OPERATIONS)
        or is_configuration(word)
    ):
        return [command, "--config", word, *rest[1:]]
    return argv


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="roboloom",
        description="Without a command: the launcher (choose operation and options).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    # --config: the robot under .roboloom/ (optional when there is only one) or a YAML file
    configured = argparse.ArgumentParser(add_help=False)
    configured.add_argument("--config", default=None, help=argparse.SUPPRESS)
    configured.add_argument("--hardware", action=_Removed)
    # devices: launch options and mock/hardware
    devices = argparse.ArgumentParser(add_help=False)
    devices.add_argument(
        "--with",
        dest="with_",
        type=_names,
        default=None,
        metavar="A,B",
        help="enable these options (and what they require)",
    )
    devices.add_argument(
        "--without",
        type=_names,
        default=None,
        metavar="A,B",
        help="disable these options (also ones enabled by default)",
    )
    devices.add_argument(
        "--mock", action="store_true", help="mock devices instead of the hardware"
    )
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
        parents=[configured, devices],
        help="Dynamixel: write the Operating Mode / Current Limit a node expects (EEPROM)",
    )
    com.add_argument("node")
    wd = sub.add_parser(
        "watchdog-test",
        parents=[configured, devices],
        help="Dynamixel bench test: does the Bus Watchdog stop a current-mode motor (torques it)",
    )
    wd.add_argument("node")
    wd.add_argument("joint")
    wd.add_argument("--current-mA", type=float, default=30.0)
    gc = sub.add_parser(
        "gravity-check",
        parents=[configured, devices],
        help="Dynamixel leader: release the arm with and without gravity compensation and compare (torques it)",
    )
    gc.add_argument("node")
    gc.add_argument("group", help="control group, e.g. right_arm")
    gc.add_argument("--poses", type=int, default=3)
    gc.add_argument(
        "--scales",
        type=lambda text: [float(x) for x in text.split(",")],
        default=[1.0, 0.0],
        help="multiples of the configured gains to try at each pose, e.g. 1,0,2,-2",
    )
    tune = sub.add_parser(
        "tune-gravity",
        parents=[configured, devices],
        help="Dynamixel leader: tune gravity compensation joint by joint with a live guide (torques the arm)",
    )
    tune.add_argument("node")
    tune.add_argument("group", help="gravity_comp group, e.g. right_arm")
    calib = sub.add_parser(
        "calibrate-joints",
        help="Dynamixel: record zero counts at the URDF zero pose (read-only)",
    )
    calib.add_argument("calibration")
    calib.add_argument("--joints", type=lambda text: text.split(","), default=None)
    travel = sub.add_parser(
        "measure-travel",
        help="Dynamixel: record each joint's travel while moving the limp arm (read-only)",
    )
    travel.add_argument("calibration")
    travel.add_argument("--out", required=True)
    pose = sub.add_parser(
        "capture-pose",
        parents=[configured, devices],
        help="save a follower's current pose as poses/<follower>/<name>.yaml (for home)",
    )
    pose.add_argument(
        "pose",
        nargs="+",
        metavar="[FOLLOWER] NAME",
        help="the follower node (may be omitted when there is one) and the pose name",
    )
    pose.add_argument("--force", action="store_true", help="replace an existing pose")
    ident = sub.add_parser(
        "identify-gravity",
        help="Dynamixel: collect holding currents and fit a gravity model",
    )
    ident.add_argument("calibration")
    ident.add_argument("--out", required=True)
    ident.add_argument(
        "--data", default=None, help="npz of holding currents (default: next to --out)"
    )
    ident.add_argument(
        "--collect",
        action="store_true",
        help="collect new poses first (torques the arm)",
    )
    ident.add_argument("--hardware", action=_Removed)
    ident.add_argument(
        "--delta", type=int, default=30, help="approach offset in counts"
    )
    ident.add_argument("--max-rms-mA", type=float, default=15.0)
    sub.add_parser(
        "validate",
        parents=[configured, devices],
        help="check a configuration and its dora dataflow (opens no device)",
    )
    sub.add_parser(
        "launch",
        parents=[configured, devices],
        help="the launcher: choose the operation and options, then start (default)",
    )
    run_cmd = sub.add_parser(
        "run",
        parents=[configured, devices],
        help="start the dataflow with the operator screen (many episodes)",
    )
    run_cmd.add_argument(
        "--plain",
        action="store_true",
        help="line-by-line prompt instead of the fixed screen",
    )
    rec = sub.add_parser(
        "record",
        parents=[configured, devices],
        help="record episodes of a fixed length (default: one) and exit",
    )
    rec.add_argument(
        "--plain", action="store_true", help="use non-interactive recording"
    )
    rec.add_argument("--task", required=True, help="task text stored with every frame")
    rec.add_argument("--seconds", type=float, required=True)
    rec.add_argument("--episodes", type=int, default=1)
    rec.add_argument(
        "--home",
        action="store_true",
        help="move to the controller's saved home pose before every episode",
    )
    inf = sub.add_parser(
        "infer",
        parents=[configured, devices],
        help="run a learned policy for fixed-length episodes (enables option `policy`)",
    )
    inf.add_argument(
        "--plain", action="store_true", help="use non-interactive inference"
    )
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
    sess = sub.add_parser(
        "session", parents=[configured], help="send one command to a running `run`"
    )
    sess.add_argument("operation", choices=SESSION_OPERATIONS)
    sess.add_argument("task", nargs="?", default="")
    args = parser.parse_args(_with_config(list(sys.argv[1:] if argv is None else argv)))
    try:
        _dispatch(args)
    except Cancelled as exc:
        print(exc)
    except RoboloomError as exc:
        raise SystemExit(f"error: {exc}") from None


def _selection(args: argparse.Namespace, path: Path) -> tuple[str, ...] | None:
    """The options the command line asks for (None: the configuration's defaults)."""
    with_ = list(getattr(args, "with_", None) or [])
    without = getattr(args, "without", None) or []
    options = _declared(path)
    if args.command == "infer" and INFER_OPTION in options:
        with_.append(INFER_OPTION)
    if not with_ and not without:
        return None
    return select_options(options, with_, without)


def _declared(path: Path) -> dict[str, Option]:
    """The configuration's options, read without loading its nodes."""
    return parse_options((yaml.safe_load(path.read_text()) or {}).get("options"))


def _load(args: argparse.Namespace) -> RobotConfig:
    path = resolve_config(args.config)
    return load_config(
        path,
        options=_selection(args, path),
        mock=True if getattr(args, "mock", False) else None,
    )


def _dispatch(args: argparse.Namespace) -> None:
    from . import setup
    from .operator import TerminalOperator

    operator = TerminalOperator()
    if args.command == "init":
        from .project import init_project

        print(init_project(args.robot, args.root))
        return
    if args.command == "probe":
        from .probe import probe

        print(probe(args.port, args.ids, args.baudrate))
        return
    if args.command == "commission":
        plan = setup.plan_commission(_load(args), args.node)
        if not plan.changes:
            print(f"{args.node}: EEPROM already matches the configuration")
            return
        print("\n".join(plan.lines()))
        written = setup.apply_commission(plan, operator)
        print(f"{args.node}: wrote and read back {written} values")
        return
    if args.command == "watchdog-test":
        result = setup.watchdog_test(
            _load(args), args.node, args.joint, operator, args.current_mA
        )
        print("\n".join(result.lines()))
        return
    if args.command == "gravity-check":
        check = setup.gravity_check(
            _load(args), args.node, args.group, operator, args.poses, args.scales
        )
        print("\n".join(check.lines()))
        return
    if args.command == "tune-gravity":
        from .ui.tune import run

        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise ConfigError(
                "tune-gravity requires an interactive terminal; no device was opened"
            )
        tuned = _load(args)
        mode = "mock" if tuned.mock else "hardware"
        outcome = run(
            lambda: setup.open_tuning(tuned, args.node, args.group),
            f"tune-gravity  {args.node}.{args.group}  ({mode})",
        )
        print(outcome)
        return
    if args.command == "calibrate-joints":
        zeros = setup.calibrate_joints(args.calibration, operator, args.joints)
        print(
            f"recorded zeros for {len(zeros)} joints in {args.calibration}; "
            "check directions, then set confirmed: true"
        )
        return
    if args.command == "capture-pose":
        if len(args.pose) > 2:
            raise ConfigError("capture-pose takes [FOLLOWER] NAME")
        *follower, name = args.pose
        path = setup.capture_pose(
            _load(args),
            name,
            follower=follower[0] if follower else None,
            force=args.force,
        )
        print(
            f"saved {path}; select it with "
            f"home: {{pose: ../poses/{path.parent.name}/{path.name}}}"
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
            delta=args.delta,
            max_rms_mA=args.max_rms_mA,
        )
        print("\n".join(fit.lines()))
        return
    from .runtime.session import fifo_for, validate_flow

    if args.command == "session":
        # the FIFO belongs to the configuration file, whatever options the run chose
        cfg = load_config(resolve_config(args.config), mock=True)
        send_session(
            fifo_for(cfg), " ".join(x for x in (args.operation, args.task) if x)
        )
        return
    if args.command == "validate":
        cfg = _load(args)
        with tempfile.TemporaryDirectory(prefix="roboloom-flow-") as directory:
            validate_flow(cfg, Path(directory))
        options = ", ".join(cfg.options) or "none"
        print(
            f"Valid: {cfg.path} ({len(build_flow(cfg)['nodes'])} nodes; "
            f"options: {options}; dataset: {cfg.repo_id})"
        )
        return
    _operate(args)


def _operate(args: argparse.Namespace) -> None:
    """run / record / infer / the launcher. `roboloom` without a robot starts with the
    robot list; the options screen's Back returns to it."""
    from .ui.launcher import BACK, choose_robot

    terminal = sys.stdin.isatty() and sys.stdout.isatty()
    if args.command == "launch" and not terminal:
        raise ConfigError("the launcher needs an interactive terminal; use run --plain")
    pick = args.command == "launch" and args.config is None
    while True:
        if pick:
            robot = choose_robot()
            if robot is None:
                print("cancelled; nothing was started")
                return
            args.config = robot
        if _operate_robot(args, terminal, back=pick) != BACK:
            return


def _operate_robot(
    args: argparse.Namespace, terminal: bool, *, back: bool
) -> str | None:
    """One robot: in a terminal the options screen comes first unless the options were
    given (--with/--without); quitting the operator screen with "choose options again"
    comes back to it. Returns BACK when the operator went back to the robot list."""
    from .ui.launcher import BACK, LaunchPlan, choose, load_last

    path = resolve_config(args.config)
    plain = getattr(args, "plain", False)
    given = _selection(args, path)
    asked = bool(getattr(args, "with_", None) or getattr(args, "without", None))
    mock = bool(getattr(args, "mock", False))
    plan = LaunchPlan(
        mode="run" if args.command == "launch" else args.command,
        options=given or (),
        mock=mock,
        task=getattr(args, "task", "") or "",
        seconds=getattr(args, "seconds", 0.0) or 0.0,
        episodes=getattr(args, "episodes", 1) or 1,
        home=getattr(args, "home", False),
    )
    show = terminal and not plain and not asked
    if show:
        options = _declared(path)
        last = load_last(path, options)
        if args.command == "launch" and last is not None:
            plan = replace(last, mock=last.mock or mock)
        elif given is None:  # the options start as last time, else the defaults
            plan = replace(
                plan,
                options=last.options if last is not None else select_options(options),
            )
    while True:
        if show:
            chosen = choose(path, plan, back=back)
            if chosen == BACK:
                return BACK
            if not isinstance(chosen, LaunchPlan):
                print("cancelled; nothing was started")
                return None
            plan = chosen
        selected = plan.options if (show or given is not None) else None
        cfg = load_config(path, options=selected, mock=True if plan.mock else None)
        if terminal and not cfg.mock:
            _commission(cfg)
        outcome = _start(
            args, cfg, plan, live=terminal and not plain, reselect=terminal
        )
        if outcome != "reselect":
            return None
        show = True


def _commission(cfg: RobotConfig) -> None:
    """Options can change a node's Operating Mode or Current Limit (EEPROM), which the
    nodes check at startup. Before launching, show the differences and write them after
    the operator confirms (as `roboloom commission` does)."""
    from . import setup
    from .operator import TerminalOperator

    for name, owner in {**cfg.inputs, **cfg.followers}.items():
        if getattr(owner, "expected_eeprom", None) is None:
            continue
        plan = setup.plan_commission(cfg, name)
        if not plan.changes:
            continue
        print(f"{name}: the chosen options need different EEPROM values:")
        print("\n".join(f"  {line}" for line in plan.lines()))
        written = setup.apply_commission(plan, TerminalOperator())
        print(f"{name}: wrote and read back {written} values")


def _start(
    args: argparse.Namespace,
    cfg: RobotConfig,
    plan: LaunchPlan,
    *,
    live: bool,
    reselect: bool,
) -> str:
    from .runtime.session import Session

    policy = getattr(args, "policy", None)
    policy_kwargs = getattr(args, "policy_kwargs", None)
    if live:
        from .ui.app import run_backend
        from .ui.backend import RecordingPlan, SessionBackend

        recording = None
        if plan.mode in ("record", "infer"):
            recording = RecordingPlan(
                plan.task or "inference",
                plan.seconds,
                plan.episodes,
                save=plan.mode == "record" or bool(plan.task),
                home=plan.home,
            )
        backend = SessionBackend(
            lambda: Session.launch(
                cfg,
                policy=policy,
                policy_kwargs=policy_kwargs,
                screen=False,
                operator=None,
            ),
            mode=plan.mode,
            recording=recording,
            reselect=reselect,
        )
        outcome = run_backend(backend)
        if outcome == "failed":
            raise ConfigError(backend.failure)
        if backend.session is not None:
            print(f"logs: {backend.session.log_dir}")
        return outcome
    session = Session.launch(
        cfg, policy=policy, policy_kwargs=policy_kwargs, screen=False
    )
    try:
        if plan.mode == "record":
            from .ui.record import record

            record(session, plan.task, plan.seconds, plan.episodes, home=plan.home)
        elif plan.mode == "infer":
            from .ui.record import record

            # a task names the run and keeps it; without one nothing is saved
            record(
                session,
                plan.task or "inference",
                plan.seconds,
                plan.episodes,
                keep=lambda _: bool(plan.task),
            )
        else:
            _plain_loop(session.client, session.process, session.release_note())
    finally:
        session.close()
        if session.process.returncode:
            print(
                f"dora exited with {session.process.returncode}; end of its log:\n"
                f"{session.log_path.read_text()[-4000:]}"
            )
        print(f"logs: {session.log_dir}")
    return "done"


def send_session(fifo: Path, line: str) -> None:
    try:
        fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
    except (FileNotFoundError, OSError) as exc:
        raise ConfigError(
            f"no running `run` to send to ({fifo}: {exc.strerror})"
        ) from None
    try:
        os.write(fd, (line + "\n").encode())
    finally:
        os.close(fd)


def _plain_loop(client, process: subprocess.Popen, release_note: str) -> None:
    """Line input for pipes and non-terminal use; reports are printed as they arrive.
    `release_note`: what to do before release (Session.release_note)."""
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
            and input(f"Before release: {release_note}. Type yes to release: ").strip()
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
