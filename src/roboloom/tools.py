"""Hardware commissioning and gravity identification commands. Each opens one Dynamixel bus.

All commands that write to motors require `--hardware` and an explicit `yes`.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import yaml

from .config import load_experiment, placeholders
from .core.resources import is_package_ref, resolve
from .drivers.dynamixel_table import MODELS, OPERATING_MODES

POSITION_MODES = {
    OPERATING_MODES[m] for m in ("position", "extended_position", "current_position")
}


def confirm(prompt: str) -> bool:
    return input(f"{prompt} Type yes to continue: ").strip() == "yes"


# -- commission ------------------------------------------------------------------


def commission(experiment: str, node: str, yes: bool = False) -> str:
    """Write the Operating Mode and Current Limit (EEPROM) a node's configuration expects."""
    from .drivers.dynamixel import DynamixelBus

    cfg = load_experiment(experiment)
    owner = {**cfg.inputs, **cfg.robots}.get(node)
    expected = getattr(owner, "expected_eeprom", None)
    if owner is None or expected is None or cfg.mock:
        raise SystemExit(f"{node}: not a commissionable hardware node in {experiment}")
    joints, ids, want = expected()
    bus = DynamixelBus(str(getattr(owner, "port", "")), ids)
    try:
        units = bus.current_units_mA()
        plan: dict[str, dict[int, int]] = {}
        for register in ("operating_mode", "current_limit"):
            values = bus.read_register(register)
            for i, joint in enumerate(joints):
                if joint not in want.get(register, {}):
                    continue
                target = want[register][joint]
                raw = (
                    int(target)
                    if register == "operating_mode"
                    else round(target / units[i])
                )
                if raw != values[i]:
                    plan.setdefault(register, {})[i] = raw
        if not plan:
            return f"{node}: EEPROM already matches the configuration"
        lines = [
            f"{joints[i]}: {register} {bus.read_register(register)[i]} -> {raw}"
            for register, items in plan.items()
            for i, raw in items.items()
        ]
        print("\n".join(lines))
        torque = bus.read_register("torque_enable")
        if any(torque[i] for items in plan.values() for i in items):
            raise SystemExit(
                "torque is on for some of these motors; support the arm, release it, then retry"
            )
        if not yes and not confirm(f"{node}: write {len(lines)} EEPROM values."):
            return "cancelled"
        for register, items in plan.items():
            for value in sorted(set(items.values())):
                indices = [i for i, v in items.items() if v == value]
                bus.write_eeprom(register, indices, [value] * len(indices))
        return f"{node}: wrote and read back {len(lines)} values"
    finally:
        bus.close()


# -- bus watchdog bench test -----------------------------------------------------


def watchdog_trial(
    bus, current_mA: float, period_ms: float, sleep=time.sleep
) -> dict[str, object]:
    """Push one current-mode motor with `current_mA`, go silent, and read what the motor did.

    `bus` holds exactly one motor. Returns readings before and after the silence; the
    motor is left with zero goal current, torque off and the watchdog cleared.
    """
    if bus.read_register("operating_mode") != [OPERATING_MODES["current"]]:
        raise SystemExit("the motor is not in current mode; commission it first")
    if any(bus.read_register("torque_enable")):
        raise SystemExit("torque is on; stop the dataflow first")
    out: dict[str, object] = {}
    try:
        bus.write_goal_currents([0], [0.0])
        bus.set_bus_watchdog(period_ms)
        bus.set_torque([0], True)
        bus.write_goal_currents([0], [current_mA])
        currents_mA: list[float] | None = None
        for _ in range(10):  # keep talking: the watchdog must not fire yet
            sleep(period_ms / 4000)
            currents_mA = bus.read_state().currents_mA
        out["current_before_mA"] = currents_mA[0] if currents_mA else None
        out["watchdog_before"] = bus.read_register("bus_watchdog")[0]
        sleep(
            3 * period_ms / 1000
        )  # silence: the host process died or the cable came out
        out["watchdog_after"] = bus.read_register("bus_watchdog")[0]
        out["torque_after"] = bus.read_register("torque_enable")[0]
        out["goal_current_after_mA"] = bus.read_goal_currents()[0]
        state = bus.read_state()
        out["current_after_mA"] = state.currents_mA[0] if state.currents_mA else None
        out["hardware_error_after"] = bus.read_register("hardware_error")[0]
        bus.write_goal_currents([0], [0.0])  # does a fired watchdog refuse new goals?
        out["goal_after_zero_write_mA"] = bus.read_goal_currents()[0]
    finally:
        bus.set_torque([0], False)
        bus.set_bus_watchdog(None)  # clears the fired state
        bus.write_goal_currents([0], [0.0])
    return out


def watchdog_test(
    experiment: str, node: str, joint: str, current_mA: float, yes: bool = False
) -> str:
    """Bench test: does the Bus Watchdog stop a current-mode motor when the host goes silent?"""
    from .drivers.dynamixel import DynamixelBus

    cfg = load_experiment(experiment)
    owner = {**cfg.inputs, **cfg.robots}.get(node)
    expected = getattr(owner, "expected_eeprom", None)
    if owner is None or expected is None or cfg.mock:
        raise SystemExit(f"{node}: not a hardware node in {experiment}")
    period_ms = getattr(owner, "cfg", {}).get("bus_watchdog_ms")
    if not period_ms:
        raise SystemExit(f"{node}: bus_watchdog_ms is not set")
    joints, ids, _ = expected()
    if joint not in joints:
        raise SystemExit(f"{joint}: not a joint of {node}")
    if not yes and not confirm(
        f"{joint} (ID {ids[joints.index(joint)]}) will push with {current_mA:g} mA for about "
        f"{0.6 + 3 * period_ms / 1000:.1f} s. Support the arm."
    ):
        return "cancelled"
    bus = DynamixelBus(str(getattr(owner, "port", "")), [ids[joints.index(joint)]])
    try:
        r = watchdog_trial(bus, current_mA, period_ms)
    finally:
        bus.close()
    fired = isinstance(r["watchdog_after"], int) and r["watchdog_after"] < 0
    after = r["current_after_mA"]
    stopped = isinstance(after, float) and abs(after) < 0.3 * abs(current_mA)
    lines = [
        f"{k}: {v:.1f}" if isinstance(v, float) else f"{k}: {v}" for k, v in r.items()
    ]
    lines.append(
        f"watchdog {'fired' if fired else 'DID NOT FIRE'} after {period_ms} ms of silence; "
        f"motor current {'dropped' if stopped else 'DID NOT DROP'}"
    )
    lines.append(
        "PASS: silence stops this motor"
        if fired and stopped
        else "FAIL: do not rely on the watchdog; keep the arm supported"
    )
    return "\n".join(lines)


# -- gravity compensation check ---------------------------------------------------


def release_trial(
    device,
    law,
    gains: list[float],
    settle_s: float,
    watch_s: float,
    period_s: float,
    sleep=time.sleep,
    signal=lambda: print("\a  LET GO now", flush=True),
) -> dict[str, tuple[float, float, float, float, float]]:
    """Enable `law` with `gains`, let the operator release the arm, and watch it.

    Returns per joint, at the release: position (counts), g(q) at gain 1 and the sent
    current (mA); then the drift in counts over `watch_s` and the peak |velocity|
    (counts/s). Torque is off again afterwards; a runaway stops the trial early.
    """
    law.gain = list(gains)
    device.read_state()
    device.enable_torque()
    names = [device.joint_names[i] for i in law.joints]
    start: list[float] = []
    model: list[float] = []
    sent: list[float] = []
    peak = [0.0] * len(names)
    try:
        for tick in range(round((settle_s + watch_s) / period_s)):
            state = device.read_state()
            if tick == round(settle_s / period_s):
                signal()
                start = [state.positions[i] for i in law.joints]
            if start:
                velocities = state.velocities or [0.0] * len(state.positions)
                peak = [
                    max(p, abs(velocities[i]))
                    for p, i in zip(peak, law.joints, strict=True)
                ]
            device.command(None)
            if len(start) and not sent:
                model = [law.model_mA.get(i, float("nan")) for i in law.joints]
                sent = [device.last_currents.get(i, 0.0) for i in law.joints]
            sleep(period_s)
    except RuntimeError as exc:  # RunawayError / WatchdogFired: the device went limp
        print(f"  stopped: {exc}")
    finally:
        device.disable_torque()
    end = device.read_state().positions
    nan = [float("nan")] * len(names)
    start, model, sent = start or nan, model or nan, sent or nan
    return {
        n: (q0, g, c, end[i] - q0, v)
        for n, i, q0, g, c, v in zip(
            names, law.joints, start, model, sent, peak, strict=True
        )
    }


def gravity_check(
    experiment: str,
    node: str,
    group: str,
    poses: int = 3,
    scales: Sequence[float] = (1.0, 0.0),
) -> str:
    """Objective A/B: at the same pose, release the arm once per scale of the configured
    gains (default: as configured, then 0) and compare how far and how fast each joint moves.
    A negative scale pushes the other way: it tells a wrong sign from too little current."""
    from .control.device import JointDevice, build_laws
    from .control.laws import CurrentLaw
    from .control.trace import Trace
    from .inputs.base import JointInput

    cfg = load_experiment(experiment)
    owner = cfg.inputs.get(node)
    control = owner.control if isinstance(owner, JointInput) else None
    if not isinstance(owner, JointInput) or not control or cfg.mock:
        raise SystemExit(f"{node}: not an actuated hardware input in {experiment}")
    laws = build_laws(control, owner.joint_names, owner.cfg.get("__dir__"))
    law = next((x for x in laws if x.name == group), None)
    if not isinstance(law, CurrentLaw) or law.gravity is None:
        raise SystemExit(f"{group}: not a gravity-compensated group of {node}")
    configured = list(law.gain)
    for other in laws:  # only the tested arm pushes
        if other is not law and isinstance(other, CurrentLaw):
            other.gain = [0.0] * len(other.joints)
    device = JointDevice(owner.open_bus(False), owner.joint_names, laws, node)
    trace_path = (
        Path(cfg.path).parent
        / "logs"
        / f"gravity-check-{group}-{time.strftime('%Y%m%d-%H%M%S')}.npz"
    )
    device.trace = Trace(trace_path, owner.joint_names)
    period = 1 / float(owner.cfg.get("poll_hz", 60))
    rows = []
    try:
        for pose in range(poses):
            for scale in scales:
                label = f"gain x{scale:g}"
                gains = [scale * g for g in configured]
                input(
                    f"pose {pose + 1}/{poses}, {label}: hold the arm still in a pose "
                    f"(the same pose for both runs), press Enter, let go at the beep: "
                )
                result = release_trial(
                    device, law, gains, law.ramp_s + 0.5, 1.5, period
                )
                rows += [(pose + 1, label, j, *r) for j, r in result.items()]
    finally:
        try:
            device.trace.save()
        finally:
            device.close()
    lines = [
        (
            f"{'pose':>4} {'run':<12} {'joint':<16} {'q':>5} {'g(q)':>5} {'sent':>5} "
            f"{'drift':>6} {'peak v':>6}"
        )
    ]
    lines += [
        f"{p:>4} {r:<12} {j:<16} {q:>5.0f} {g:>5.0f} {c:>5.0f} {d:>6.0f} {v:>6.0f}"
        for p, r, j, q, g, c, d, v in rows
    ]
    lines.append(f"trace: {trace_path}")
    lines.append(
        "drift: counts moved in 1.5 s after letting go; compensation works where the "
        "compensated drift is much smaller than the gain-0 drift"
    )
    return "\n".join(lines)


def tune_gravity(experiment: str, node: str, group: str) -> str:
    """Live, joint-by-joint tuning of one gravity_comp group; saves to its tuning file."""
    from .control.device import JointDevice, build_laws, tuning_path
    from .control.laws import CurrentLaw, GravityComp
    from .control.tuning import TuningSession
    from .inputs.base import JointInput
    from .ui.tune import run

    cfg = load_experiment(experiment)
    owner = cfg.inputs.get(node)
    control = owner.control if isinstance(owner, JointInput) else None
    if not isinstance(owner, JointInput) or not control:
        raise SystemExit(f"{node}: not an actuated input in {experiment}")
    spec = next((g for g in control if g.name == group), None)
    if spec is None or spec.law != "gravity_comp" or not spec.cfg.get("tuning"):
        raise SystemExit(
            f"{group}: needs a gravity_comp group with `tuning:` (the file this tool writes)"
        )
    laws = build_laws(control, owner.joint_names, owner.cfg.get("__dir__"))
    law = next(x for x in laws if x.name == group)
    assert isinstance(law, GravityComp)
    for other in laws:  # only the tuned arm pushes; the others stay limp
        if other is not law and isinstance(other, GravityComp):
            other.gain = [0.0] * len(other.joints)
            other.hold = [0.0] * len(other.joints)
        elif other is not law and isinstance(other, CurrentLaw):
            other.gain = [0.0] * len(other.joints)
    ids = dict(zip(owner.joint_names, owner.cfg.get("motor_ids") or [], strict=False))
    device = JointDevice(owner.open_bus(cfg.mock), owner.joint_names, laws, node)
    session = TuningSession(
        device,
        law,
        tuning_path(spec.cfg["tuning"], owner.cfg.get("__dir__")),
        ids,
    )
    try:
        result = run(
            session,
            1 / float(owner.cfg.get("poll_hz", 60)),
            f"tune-gravity  {node}.{group}  ({'mock' if cfg.mock else 'hardware'})",
        )
    finally:
        device.close()
    return f"{result}: {session.path}"


# -- calibration file ------------------------------------------------------------


class Calibration:
    """Joint map for gravity identification: motor IDs, URDF joints, zero counts and directions."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = yaml.safe_load(self.path.read_text())
        missing = placeholders(self.data)
        if missing:
            raise SystemExit(f"{path}: fill first: " + ", ".join(missing))
        joints = self.data.get("joints")
        if not isinstance(joints, list) or not joints:
            raise ValueError(f"{path}: joints list required")
        self.joints = joints
        self.names = [j["name"] for j in joints]
        self.ids = [int(j["motor_id"]) for j in joints]
        self.outputs = list(self.data.get("outputs") or [])
        if not set(self.outputs) <= set(self.names):
            raise ValueError(f"{path}: outputs must be calibration joints")
        # what a saved model records: the package reference itself, or the resolved file
        self.urdf_ref: str | Path = (
            self.data["urdf"]
            if is_package_ref(self.data["urdf"])
            else resolve(self.data["urdf"], self.path.parent)
        )
        self.urdf = resolve(self.data["urdf"], self.path.parent)

    def joint_maps(self):
        from .dynamics.regressor import JointMap

        maps = []
        for j in self.joints:
            if j.get("direction") not in (1, -1) or not isinstance(
                j.get("zero"), (int, float)
            ):
                raise ValueError(
                    f"{self.path}: {j['name']} needs direction +1/-1 and a zero count"
                )
            maps.append(
                JointMap(j["name"], j["urdf"], float(j["zero"]), int(j["direction"]))
            )
        return maps

    def save(self) -> None:
        self.path.write_text(
            yaml.safe_dump(self.data, sort_keys=False, allow_unicode=True)
        )


def calibrate_joints(path: str, joints: list[str] | None = None) -> str:
    """Record zero counts while the operator holds the arm at the URDF zero pose. Read-only on the bus."""
    from .drivers.dynamixel import DynamixelBus

    cal = Calibration(path)
    chosen = joints or cal.names
    bus = DynamixelBus(cal.data["port"], cal.ids)
    try:
        if any(bus.read_register("torque_enable")):
            raise SystemExit(
                "torque is on; this command expects a limp arm held by the operator"
            )
        input(f"Hold {', '.join(chosen)} at the URDF zero pose and press Enter: ")
        positions = bus.read_positions()
    finally:
        bus.close()
    for j, count in zip(cal.joints, positions, strict=True):
        if j["name"] in chosen:
            j["zero"] = int(count)
    cal.data["confirmed"] = False
    cal.save()
    return f"recorded zeros for {len(chosen)} joints in {path}; check directions, then set confirmed: true"


def measure_travel(
    path: str, out: str, min_span: int = 200, period_s: float = 1 / 30
) -> str:
    """Record each output joint's min/max counts while the operator moves the limp arm. Read-only."""
    import select
    import sys

    from .drivers.dynamixel import DynamixelBus

    cal = Calibration(path)
    joints = cal.outputs or cal.names
    index = [cal.names.index(j) for j in joints]
    bus = DynamixelBus(cal.data["port"], cal.ids)
    try:
        if any(bus.read_register("torque_enable")):
            raise SystemExit(
                "torque is on; this command expects a limp arm moved by the operator"
            )
        first = bus.read_positions()
        lo = {j: first[i] for j, i in zip(joints, index, strict=True)}
        hi = dict(lo)
        print(
            f"Move {', '.join(joints)} slowly to both ends of their travel, one at a time.\n"
            "Press Enter when every joint has reached both ends."
        )
        while not select.select([sys.stdin], [], [], 0)[0]:
            positions = bus.read_positions()
            for j, i in zip(joints, index, strict=True):
                lo[j], hi[j] = min(lo[j], positions[i]), max(hi[j], positions[i])
            spans = " ".join(f"{j.split('_')[-1]}={hi[j] - lo[j]:.0f}" for j in joints)
            print(f"\rspan (counts): {spans}   ", end="", flush=True)
            time.sleep(period_s)
        sys.stdin.readline()
        print()
    finally:
        bus.close()
    short = [j for j in joints if hi[j] - lo[j] < min_span]
    if short:
        raise SystemExit(
            f"moved less than {min_span} counts: {short}; nothing saved, measure again"
        )
    travel = {j: [int(lo[j]), int(hi[j])] for j in joints}
    Path(out).write_text(
        "# Measured joint travel (raw counts) for current-mode runaway checks.\n"
        f"# Written by: roboloom measure-travel {path}\n"
        + yaml.safe_dump(
            {
                "port": cal.data["port"],
                "measured": time.strftime("%Y-%m-%d"),
                "travel": travel,
            },
            sort_keys=False,
        )
    )
    lines = [f"{j}: {a} .. {b} ({b - a} counts)" for j, (a, b) in travel.items()]
    return "\n".join([*lines, f"saved {out}"])


# -- gravity identification ----------------------------------------------------


def collect_holding_currents(
    cal: Calibration,
    data_path: Path,
    delta: int = 30,
    settle_s: float = 0.7,
    samples: int = 10,
) -> int:
    """Interactive: per pose, hold each output joint after approaching from below and from above."""
    from .drivers.dynamixel import DynamixelBus

    out = [cal.names.index(o) for o in cal.outputs]
    bus = DynamixelBus(cal.data["port"], cal.ids)
    rows, currents, poses = [], [], []
    if data_path.exists():
        old = np.load(data_path)
        rows, currents, poses = (
            list(old["positions"]),
            list(old["currents_mA"]),
            list(old["pose"]),
        )
    pose = int(max(poses, default=-1)) + 1
    try:
        modes = bus.read_register("operating_mode")
        wrong = [cal.names[i] for i in out if modes[i] not in POSITION_MODES]
        if wrong:
            raise SystemExit(
                f"{wrong}: identification holds joints in a position mode; commission them first"
            )
        if any(bus.read_register("torque_enable")):
            raise SystemExit("torque is on; another process may own this bus")
        models = bus.read_register("model_number")
        print(
            "Motors:",
            ", ".join(
                f"{n}={MODELS[m].name if m in MODELS else m}"
                for n, m in zip(cal.names, models, strict=True)
            ),
        )
        while True:
            answer = input(
                f"Pose {pose}: move the arm, hold it still, press Enter (q to finish): "
            ).strip()
            if answer == "q":
                break
            p0 = bus.read_positions()
            bus.write_goal_positions(list(range(len(cal.ids))), p0)
            bus.set_torque(out, True)
            try:
                for sign in (
                    1,
                    -1,
                ):  # approach from below, then from above: averages out static friction
                    bus.write_goal_positions(out, [p0[i] - sign * delta for i in out])
                    time.sleep(settle_s)
                    bus.write_goal_positions(out, [p0[i] for i in out])
                    time.sleep(settle_s)
                    states = [bus.read_state() for _ in range(samples)]
                    rows.append(np.mean([s.positions for s in states], axis=0))
                    currents.append(
                        np.mean(
                            [[(s.currents_mA or [])[i] for i in out] for s in states],
                            axis=0,
                        )
                    )
                    poses.append(pose)
            finally:
                bus.set_torque(out, False)
            print("  mA:", np.round(currents[-2], 1), "/", np.round(currents[-1], 1))
            np.savez(
                data_path,
                positions=np.array(rows),
                currents_mA=np.array(currents),
                pose=np.array(poses),
                joints=np.array(cal.names),
                outputs=np.array(cal.outputs),
            )
            pose += 1
    finally:
        bus.set_torque(list(range(len(cal.ids))), False)
        bus.close()
    return pose


def fit_gravity(
    cal: Calibration,
    data_path: Path,
    out: Path,
    max_rms_mA: float,
    holdout_every: int = 4,
) -> str:
    from .dynamics.identify import robust_outliers, search_directions
    from .dynamics.regressor import Regressor, RegressorGravityModel

    if cal.data.get("confirmed") is not True:
        raise SystemExit(
            f"{cal.path}: check the URDF mapping, zeros and directions, then set confirmed: true"
        )
    data = np.load(data_path)
    if list(data["joints"]) != cal.names or list(data["outputs"]) != cal.outputs:
        raise SystemExit(f"{data_path} was collected for different joints")
    # The two approaches of a pose (from below, from above) bracket static friction: average them.
    poses = np.unique(data["pose"])
    samples = np.array([data["positions"][data["pose"] == p].mean(0) for p in poses])
    currents = np.array([data["currents_mA"][data["pose"] == p].mean(0) for p in poses])
    spread = np.array(
        [np.ptp(data["currents_mA"][data["pose"] == p], axis=0) / 2 for p in poses]
    )
    # Failed measurements (arm still moving, touched by hand): the two approaches disagree far
    # more than friction does, or the pose disagrees with every other pose.
    dropped = robust_outliers(spread, floor=15.0)
    first = Regressor(cal.urdf.read_text(), cal.joint_maps(), cal.outputs).fit(
        samples[~dropped],
        currents[~dropped],
        shared=bool(cal.data.get("shared_parameters", False)),
    )
    model0 = RegressorGravityModel(
        cal.urdf.read_text(), cal.joint_maps(), cal.outputs, first.theta
    )
    residual = np.array([model0.effort_mA(q) for q in samples]) - currents
    dropped |= robust_outliers(np.where(dropped[:, None], 0.0, residual), floor=15.0)
    report_dropped = (
        f"dropped poses {poses[dropped].tolist()} (approaches disagree or far off the fit)"
        if dropped.any()
        else ""
    )
    poses, samples, currents = poses[~dropped], samples[~dropped], currents[~dropped]
    holdout = poses % holdout_every == holdout_every - 1
    if holdout.sum() < 2 or (~holdout).sum() < 8:
        raise SystemExit("collect more poses (at least 12)")
    report_poses = f"{len(poses)} poses ({int(holdout.sum())} held out for validation)"
    urdf = cal.urdf.read_text()
    maps = cal.joint_maps()
    shared = bool(cal.data.get("shared_parameters", False))
    # Inputs that are not outputs (e.g. a torso yawing about the gravity axis) keep their sign:
    # gravity often cannot tell their direction, and they only orient the arm.
    fixed = {m.name for m in maps if m.name not in cal.outputs}
    ranked = search_directions(
        urdf, maps, cal.outputs, samples, currents, holdout, fixed, shared
    )
    best_score = ranked[0][0]
    calibrated = next(
        r for r in ranked if [m.direction for m in r[1]] == [m.direction for m in maps]
    )
    if [m.direction for m in ranked[0][1]] != [m.direction for m in maps]:
        report_best = f"best directions: {[m.direction for m in ranked[0][1]]}"
    else:
        report_best = ""
    report = [
        *([report_dropped] if report_dropped else []),
        report_poses,
        f"{'shared' if shared else 'per-joint'} parameters; calibrated directions: holdout RMS {calibrated[0]:.1f} mA (best {best_score:.1f} mA)",
    ]
    ties = [
        [m.direction for m in trial]
        for score, trial, _ in ranked
        if score <= best_score * 1.1 + 1e-9
    ]
    if report_best:
        report.append(report_best)
    if len(ties) > 1:
        report.append(
            f"warning: {len(ties)} direction sets fit within 10%; data cannot decide, calibration does"
        )
    if calibrated[0] > best_score * 1.5 + 1.0:
        best = [m.direction for m in ranked[0][1]]
        raise SystemExit(
            "\n".join(
                [
                    *report,
                    f"directions {best} fit much better; check the calibration before saving",
                ]
            )
        )
    fit = calibrated[2]
    # An RMS is only small relative to how much the current varies: a joint whose holding
    # current hardly changes passes any RMS limit while the model explains none of it.
    explained = 1 - np.square(fit.holdout_rms_mA) / np.maximum(
        currents.var(axis=0), 1e-9
    )
    report += [
        f"{o}: rank {r}, holdout RMS {h:.1f} mA, train {t:.1f} mA, "
        f"current std {sd:.1f} mA, explained {e:.0%}"
        for o, r, h, t, sd, e in zip(
            cal.outputs,
            fit.rank,
            fit.holdout_rms_mA,
            fit.rms_mA,
            currents.std(axis=0),
            explained,
            strict=True,
        )
    ]
    weak = [o for o, e in zip(cal.outputs, explained, strict=True) if e < 0.5]
    if weak:
        report.append(
            f"warning: the model explains under half of the measured current on {weak}; "
            "keep their gravity_gain at 0"
        )
    # A small holdout can be lucky: the training error must also be within the limit.
    # Joints the model does not explain are only usable at gain 0 (warned above), so the
    # limit applies to the joints it can compensate.
    usable = [k for k, e in enumerate(explained) if e >= 0.5]
    if not usable:
        raise SystemExit("\n".join([*report, "no joint is explained; model not saved"]))
    worst = max(max(fit.holdout_rms_mA[k], fit.rms_mA[k]) for k in usable)
    if worst > max_rms_mA:
        raise SystemExit(
            "\n".join(
                [*report, f"RMS {worst:.1f} mA above {max_rms_mA} mA; model not saved"]
            )
        )
    # refit with every pose for the saved model
    from .dynamics.regressor import Regressor

    final = Regressor(urdf, maps, cal.outputs).fit(samples, currents, shared=shared)
    final.holdout_rms_mA = fit.holdout_rms_mA
    RegressorGravityModel(urdf, maps, cal.outputs, final.theta).save(
        out,
        cal.urdf_ref,
        final,
        {  # relative to the model, so a committed project still points at its files
            "calibration": str(
                cal.path.resolve().relative_to(out.resolve().parent, walk_up=True)
            ),
            "data": str(
                data_path.resolve().relative_to(out.resolve().parent, walk_up=True)
            ),
        },
    )
    return "\n".join([*report, f"saved {out}"])
