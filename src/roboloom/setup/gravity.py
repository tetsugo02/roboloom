"""Gravity compensation of an actuated leader: identify g(q), check it, tune it by hand.

- `identify_gravity`: hold poses in position mode, record holding currents, fit a model.
- `gravity_check`: release the arm at a pose with scaled gains and measure the drift.
- `open_tuning`: a live `TuningSession` for joint-by-joint manual tuning (`ui/tune.py`).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..control.tuning import TuningSession
from ..drivers.dynamixel_table import MODELS, OPERATING_MODES
from ..errors import Cancelled, ConfigError, HardwareError, SetupError
from ..operator import Operator
from .calibration import Calibration
from .common import experiment_node, require_hardware

POSITION_MODES = {
    OPERATING_MODES[m] for m in ("position", "extended_position", "current_position")
}


# -- check: release the arm and watch it ----------------------------------------


@dataclass
class ReleaseTrial:
    """Per joint at the release: position (counts), g(q) at gain 1 and the sent current (mA);
    then the drift in counts and the peak |velocity| (counts/s)."""

    joints: dict[str, tuple[float, float, float, float, float]]
    stopped: str | None = None  # why a runaway or watchdog check ended the trial early


def release_trial(
    device,
    law,
    gains: list[float],
    settle_s: float,
    watch_s: float,
    period_s: float,
    sleep=time.sleep,
    signal: Callable[[], None] = lambda: None,
) -> ReleaseTrial:
    """Enable `law` with `gains`, call `signal` when the operator should let go, and watch the
    arm for `watch_s`. Torque is off again afterwards; a runaway stops the trial early."""
    law.gain = list(gains)
    device.read_state()
    device.enable_torque()
    names = [device.joint_names[i] for i in law.joints]
    start: list[float] = []
    model: list[float] = []
    sent: list[float] = []
    peak = [0.0] * len(names)
    stopped = None
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
        stopped = str(exc)
    finally:
        device.disable_torque()
    end = device.read_state().positions
    nan = [float("nan")] * len(names)
    start, model, sent = start or nan, model or nan, sent or nan
    return ReleaseTrial(
        {
            n: (q0, g, c, end[i] - q0, v)
            for n, i, q0, g, c, v in zip(
                names, law.joints, start, model, sent, peak, strict=True
            )
        },
        stopped,
    )


@dataclass
class CheckRow:
    pose: int
    scale: float  # multiple of the configured gains
    joint: str
    position: float
    model_mA: float
    sent_mA: float
    drift: float  # counts moved after letting go
    peak_velocity: float


@dataclass
class GravityCheck:
    rows: list[CheckRow] = field(default_factory=list)
    trace: Path | None = None
    stopped: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        out = [
            (
                f"{'pose':>4} {'run':<12} {'joint':<16} {'q':>5} {'g(q)':>5} {'sent':>5} "
                f"{'drift':>6} {'peak v':>6}"
            )
        ]
        out += [
            f"{r.pose:>4} {f'gain x{r.scale:g}':<12} {r.joint:<16} {r.position:>5.0f} "
            f"{r.model_mA:>5.0f} {r.sent_mA:>5.0f} {r.drift:>6.0f} {r.peak_velocity:>6.0f}"
            for r in self.rows
        ]
        out += [f"stopped: {s}" for s in self.stopped]
        out.append(f"trace: {self.trace}")
        out.append(
            "drift: counts moved in 1.5 s after letting go; compensation works where the "
            "compensated drift is much smaller than the gain-0 drift"
        )
        return out


def _gravity_group(experiment: str | Path, node: str, group: str):
    from ..control.device import build_laws
    from ..inputs.base import JointInput

    cfg, owner = experiment_node(experiment, node)
    control = owner.control if isinstance(owner, JointInput) else None
    if not isinstance(owner, JointInput) or not control:
        raise ConfigError(f"{node}: not an actuated input in {cfg.path}")
    spec = next((g for g in control if g.name == group), None)
    if spec is None:
        raise ConfigError(f"{group}: no such control group of {node}")
    laws = build_laws(control, owner.joint_names, owner.cfg.get("__dir__"))
    law = next(x for x in laws if x.name == group)
    return cfg, owner, spec, laws, law


def _only(law, laws) -> None:
    """Only `law` pushes; every other current law of the device stays limp."""
    from ..control.laws import CurrentLaw, GravityComp

    for other in laws:
        if other is law:
            continue
        if isinstance(other, CurrentLaw):
            other.gain = [0.0] * len(other.joints)
        if isinstance(other, GravityComp):
            other.hold = [0.0] * len(other.joints)


def gravity_check(
    experiment: str | Path,
    node: str,
    group: str,
    operator: Operator,
    poses: int = 3,
    scales: Sequence[float] = (1.0, 0.0),
    *,
    hardware: bool = False,
) -> GravityCheck:
    """Objective A/B: at the same pose, release the arm once per scale of the configured
    gains (default: as configured, then 0) and compare how far and how fast each joint moves.
    A negative scale pushes the other way: it tells a wrong sign from too little current."""
    from ..control.device import JointDevice
    from ..control.laws import CurrentLaw
    from ..control.trace import Trace

    cfg, owner, _, laws, law = _gravity_group(experiment, node, group)
    if not isinstance(law, CurrentLaw) or law.gravity is None:
        raise ConfigError(f"{group}: not a gravity-compensated group of {node}")
    require_hardware(cfg, hardware, "gravity-check")
    configured = list(law.gain)
    _only(law, laws)
    device = JointDevice(owner.open_bus(False), owner.joint_names, laws, node)
    trace = (
        Path(cfg.path).parent
        / "logs"
        / f"gravity-check-{group}-{time.strftime('%Y%m%d-%H%M%S')}.npz"
    )
    result = GravityCheck(trace=trace)
    device.trace = Trace(trace, owner.joint_names)
    period = 1 / float(owner.cfg.get("poll_hz", 60))
    try:
        for pose in range(poses):
            for scale in scales:
                operator.prompt(
                    f"pose {pose + 1}/{poses}, gain x{scale:g}: hold the arm still in a pose "
                    "(the same pose for every run), press Enter, let go at the beep: "
                )
                trial = release_trial(
                    device,
                    law,
                    [scale * g for g in configured],
                    law.ramp_s + 0.5,
                    1.5,
                    period,
                    signal=lambda: operator.notify("\a  LET GO now"),
                )
                if trial.stopped:
                    result.stopped.append(trial.stopped)
                result.rows += [
                    CheckRow(pose + 1, scale, j, *r) for j, r in trial.joints.items()
                ]
    finally:
        try:
            device.trace.save()
        finally:
            device.close()
    return result


def open_tuning(
    experiment: str | Path, node: str, group: str, *, hardware: bool = False
) -> TuningSession:
    """A live tuning session for one gravity_comp group; the other groups stay limp.
    Saving writes the group's `tuning:` file. Close the session when done."""
    from ..control.device import JointDevice, tuning_path
    from ..control.laws import GravityComp

    cfg, owner, spec, laws, law = _gravity_group(experiment, node, group)
    if not isinstance(law, GravityComp) or not spec.cfg.get("tuning"):
        raise ConfigError(
            f"{group}: needs a gravity_comp group with `tuning:` (the file tuning writes)"
        )
    if not cfg.mock:
        require_hardware(cfg, hardware, "tune-gravity")
    _only(law, laws)
    ids = dict(zip(owner.joint_names, owner.cfg.get("motor_ids") or [], strict=False))
    device = JointDevice(owner.open_bus(cfg.mock), owner.joint_names, laws, node)
    return TuningSession(
        device,
        law,
        tuning_path(spec.cfg["tuning"], owner.cfg.get("__dir__")),
        ids,
        1 / float(owner.cfg.get("poll_hz", 60)),
    )


# -- identify: holding currents in position mode, then a regression fit ---------


def collect_holding_currents(
    calibration: Calibration,
    data_path: Path,
    operator: Operator,
    delta: int = 30,
    settle_s: float = 0.7,
    samples: int = 10,
) -> int:
    """Per pose, hold each output joint after approaching from below and from above, and
    append the holding currents to `data_path` (npz). The operator moves the arm between
    poses and answers `q` to finish. Returns the next pose number."""
    from ..drivers.dynamixel import DynamixelBus

    cal = calibration
    out = [cal.names.index(o) for o in cal.outputs]
    rows, currents, poses = [], [], []
    if data_path.exists():
        old = np.load(data_path)
        rows, currents, poses = (
            list(old["positions"]),
            list(old["currents_mA"]),
            list(old["pose"]),
        )
    pose = int(max(poses, default=-1)) + 1
    if not operator.confirm(
        f"{cal.data['port']}: output joints will hold each pose with torque on, "
        f"moving {delta} counts."
    ):
        raise Cancelled("identification cancelled; nothing was collected")
    bus = DynamixelBus(cal.data["port"], cal.ids)
    try:
        modes = bus.read_register("operating_mode")
        wrong = [cal.names[i] for i in out if modes[i] not in POSITION_MODES]
        if wrong:
            raise HardwareError(
                f"{wrong}: identification holds joints in a position mode; commission them first"
            )
        if any(bus.read_register("torque_enable")):
            raise HardwareError("torque is on; another process may own this bus")
        models = bus.read_register("model_number")
        operator.notify(
            "Motors: "
            + ", ".join(
                f"{n}={MODELS[m].name if m in MODELS else m}"
                for n, m in zip(cal.names, models, strict=True)
            )
        )
        while True:
            answer = operator.prompt(
                f"Pose {pose}: move the arm, hold it still, press Enter (q to finish): "
            )
            if answer == "q":
                break
            p0 = bus.read_positions()
            bus.write_goal_positions(list(range(len(cal.ids))), p0)
            bus.set_torque(out, True)
            try:
                # approach from below, then from above: averages out static friction
                for sign in (1, -1):
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
            operator.notify(
                f"  mA: {np.round(currents[-2], 1)} / {np.round(currents[-1], 1)}"
            )
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


@dataclass
class JointFit:
    joint: str
    rank: int
    holdout_rms_mA: float
    train_rms_mA: float
    current_std_mA: float
    explained: float  # share of the measured current's variance the model explains


@dataclass
class GravityFit:
    path: Path
    joints: list[JointFit]
    report: list[str]  # poses used, directions, per-joint lines and warnings

    @property
    def warnings(self) -> list[str]:
        return [x for x in self.report if x.startswith("warning")]

    def lines(self) -> list[str]:
        return [*self.report, f"saved {self.path}"]


def fit_gravity(
    calibration: Calibration,
    data_path: Path,
    out: Path,
    max_rms_mA: float = 15.0,
    holdout_every: int = 4,
) -> GravityFit:
    """Fit and save the gravity model; refuses (SetupError, with the report) when the data
    contradicts the calibration or the fit is not good enough."""
    from ..dynamics.identify import robust_outliers, search_directions
    from ..dynamics.regressor import Regressor, RegressorGravityModel

    cal = calibration
    if cal.data.get("confirmed") is not True:
        raise ConfigError(
            f"{cal.path}: check the URDF mapping, zeros and directions, then set confirmed: true"
        )
    data = np.load(data_path)
    if list(data["joints"]) != cal.names or list(data["outputs"]) != cal.outputs:
        raise SetupError(f"{data_path} was collected for different joints")
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
    urdf = cal.urdf.read_text()
    maps = cal.joint_maps()
    shared = bool(cal.data.get("shared_parameters", False))
    first = Regressor(urdf, maps, cal.outputs).fit(
        samples[~dropped], currents[~dropped], shared=shared
    )
    model0 = RegressorGravityModel(urdf, maps, cal.outputs, first.theta)
    residual = np.array([model0.effort_mA(q) for q in samples]) - currents
    dropped |= robust_outliers(np.where(dropped[:, None], 0.0, residual), floor=15.0)
    report = []
    if dropped.any():
        report.append(
            f"dropped poses {poses[dropped].tolist()} (approaches disagree or far off the fit)"
        )
    poses, samples, currents = poses[~dropped], samples[~dropped], currents[~dropped]
    holdout = poses % holdout_every == holdout_every - 1
    if holdout.sum() < 2 or (~holdout).sum() < 8:
        raise SetupError("collect more poses (at least 12)")
    report.append(f"{len(poses)} poses ({int(holdout.sum())} held out for validation)")
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
    report.append(
        f"{'shared' if shared else 'per-joint'} parameters; calibrated directions: "
        f"holdout RMS {calibrated[0]:.1f} mA (best {best_score:.1f} mA)"
    )
    best = [m.direction for m in ranked[0][1]]
    if best != [m.direction for m in maps]:
        report.append(f"best directions: {best}")
    ties = [
        [m.direction for m in trial]
        for score, trial, _ in ranked
        if score <= best_score * 1.1 + 1e-9
    ]
    if len(ties) > 1:
        report.append(
            f"warning: {len(ties)} direction sets fit within 10%; data cannot decide, calibration does"
        )
    if calibrated[0] > best_score * 1.5 + 1.0:
        raise SetupError(
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
    joints = [
        JointFit(o, int(r), float(h), float(t), float(sd), float(e))
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
    report += [
        f"{j.joint}: rank {j.rank}, holdout RMS {j.holdout_rms_mA:.1f} mA, "
        f"train {j.train_rms_mA:.1f} mA, current std {j.current_std_mA:.1f} mA, "
        f"explained {j.explained:.0%}"
        for j in joints
    ]
    weak = [j.joint for j in joints if j.explained < 0.5]
    if weak:
        report.append(
            f"warning: the model explains under half of the measured current on {weak}; "
            "keep their gravity_gain at 0"
        )
    # A small holdout can be lucky: the training error must also be within the limit.
    # Joints the model does not explain are only usable at gain 0 (warned above), so the
    # limit applies to the joints it can compensate.
    usable = [j for j in joints if j.explained >= 0.5]
    if not usable:
        raise SetupError("\n".join([*report, "no joint is explained; model not saved"]))
    worst = max(max(j.holdout_rms_mA, j.train_rms_mA) for j in usable)
    if worst > max_rms_mA:
        raise SetupError(
            "\n".join(
                [*report, f"RMS {worst:.1f} mA above {max_rms_mA} mA; model not saved"]
            )
        )
    # refit with every pose for the saved model
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
    return GravityFit(out, joints, report)


def identify_gravity(
    calibration: str | Path | Calibration,
    out: str | Path,
    operator: Operator,
    *,
    data: str | Path | None = None,
    collect: bool = False,
    hardware: bool = False,
    delta: int = 30,
    max_rms_mA: float = 15.0,
) -> GravityFit:
    """Optionally collect new poses (torques the arm: needs `hardware=True`), then fit the
    model to every pose in `data` (default: next to `out`, as .npz) and save it to `out`."""
    cal = (
        calibration
        if isinstance(calibration, Calibration)
        else Calibration(calibration)
    )
    out = Path(out)
    data_path = Path(data) if data else out.with_suffix(".npz")
    if collect:
        if not hardware:
            raise HardwareError(
                "collecting torques the arm; pass hardware=True (--hardware)"
            )
        collect_holding_currents(cal, data_path, operator, delta)
    if not data_path.exists():
        raise SetupError(f"{data_path}: no holding currents yet; collect them first")
    return fit_gravity(cal, data_path, out, max_rms_mA)
