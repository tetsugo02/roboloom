"""Hardware commissioning and gravity identification commands. Each opens one Dynamixel bus.

All commands that write to motors require `--hardware` and an explicit `yes`.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import yaml

from .config import load_experiment
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


# -- calibration file ------------------------------------------------------------


class Calibration:
    """Joint map for gravity identification: motor IDs, URDF joints, zero counts and directions."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = yaml.safe_load(self.path.read_text())
        joints = self.data.get("joints")
        if not isinstance(joints, list) or not joints:
            raise ValueError(f"{path}: joints list required")
        self.joints = joints
        self.names = [j["name"] for j in joints]
        self.ids = [int(j["motor_id"]) for j in joints]
        self.outputs = list(self.data.get("outputs") or [])
        if not set(self.outputs) <= set(self.names):
            raise ValueError(f"{path}: outputs must be calibration joints")
        self.urdf = (self.path.parent / self.data["urdf"]).resolve()

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
    report += [
        f"{o}: rank {r}, holdout RMS {h:.1f} mA, train {t:.1f} mA"
        for o, r, h, t in zip(
            cal.outputs, fit.rank, fit.holdout_rms_mA, fit.rms_mA, strict=True
        )
    ]
    # A small holdout can be lucky: the training error must also be within the limit.
    worst = max(*fit.holdout_rms_mA, *fit.rms_mA)
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
        cal.urdf,
        final,
        {"calibration": str(cal.path.resolve()), "data": str(data_path.resolve())},
    )
    return "\n".join([*report, f"saved {out}"])
