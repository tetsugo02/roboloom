"""The joint map of one arm (calibration file) and the read-only measurements made on it:
joint zeros at the URDF zero pose, and each joint's travel."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..config import placeholders
from ..core.resources import is_package_ref, resolve
from ..errors import ConfigError, HardwareError, SetupError
from ..operator import Operator


class Calibration:
    """Joint map for gravity identification: motor IDs, URDF joints, zero counts and directions."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = yaml.safe_load(self.path.read_text())
        missing = placeholders(self.data)
        if missing:
            raise ConfigError(f"{path}: fill first: " + ", ".join(missing))
        joints = self.data.get("joints")
        if not isinstance(joints, list) or not joints:
            raise ConfigError(f"{path}: joints list required")
        self.joints = joints
        self.names = [j["name"] for j in joints]
        self.ids = [int(j["motor_id"]) for j in joints]
        self.outputs = list(self.data.get("outputs") or [])
        if not set(self.outputs) <= set(self.names):
            raise ConfigError(f"{path}: outputs must be calibration joints")
        # what a saved model records: the package reference itself, or the resolved file
        self.urdf_ref: str | Path = (
            self.data["urdf"]
            if is_package_ref(self.data["urdf"])
            else resolve(self.data["urdf"], self.path.parent)
        )
        self.urdf = resolve(self.data["urdf"], self.path.parent)

    def joint_maps(self):
        from ..dynamics.regressor import JointMap

        maps = []
        for j in self.joints:
            if j.get("direction") not in (1, -1) or not isinstance(
                j.get("zero"), (int, float)
            ):
                raise ConfigError(
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

    def open_bus(self, *, limp: bool = True):
        """The arm's bus; with `limp`, refuse while any joint is torqued (the operator moves it)."""
        from ..drivers.dynamixel import DynamixelBus

        bus = DynamixelBus(self.data["port"], self.ids)
        if limp and any(bus.read_register("torque_enable")):
            bus.close()
            raise HardwareError(
                "torque is on; this step expects a limp arm moved by the operator"
            )
        return bus


def calibrate_joints(
    calibration: str | Path | Calibration,
    operator: Operator,
    joints: list[str] | None = None,
) -> dict[str, int]:
    """Record zero counts while the operator holds the arm at the URDF zero pose. Read-only on
    the bus; writes the zeros to the calibration file and marks it unconfirmed."""
    cal = (
        calibration
        if isinstance(calibration, Calibration)
        else Calibration(calibration)
    )
    chosen = joints or cal.names
    bus = cal.open_bus()
    try:
        operator.prompt(
            f"Hold {', '.join(chosen)} at the URDF zero pose and press Enter: "
        )
        positions = bus.read_positions()
    finally:
        bus.close()
    zeros = {}
    for j, count in zip(cal.joints, positions, strict=True):
        if j["name"] in chosen:
            j["zero"] = zeros[j["name"]] = int(count)
    cal.data["confirmed"] = False
    cal.save()
    return zeros


@dataclass
class Travel:
    port: str
    joints: dict[str, tuple[int, int]]  # raw counts, lowest and highest seen
    path: Path

    def lines(self) -> list[str]:
        return [
            f"{j}: {a} .. {b} ({b - a} counts)" for j, (a, b) in self.joints.items()
        ] + [f"saved {self.path}"]


def measure_travel(
    calibration: str | Path | Calibration,
    out: str | Path,
    operator: Operator,
    min_span: int = 200,
    period_s: float = 1 / 30,
) -> Travel:
    """Record each output joint's min/max counts while the operator moves the limp arm, until
    `operator.finished()`. Read-only on the bus; writes `out` only if every joint moved."""
    cal = (
        calibration
        if isinstance(calibration, Calibration)
        else Calibration(calibration)
    )
    joints = cal.outputs or cal.names
    index = [cal.names.index(j) for j in joints]
    bus = cal.open_bus()
    try:
        first = bus.read_positions()
        lo = {j: first[i] for j, i in zip(joints, index, strict=True)}
        hi = dict(lo)
        operator.notify(
            f"Move {', '.join(joints)} slowly to both ends of their travel, one at a time.\n"
            "Press Enter when every joint has reached both ends."
        )
        while not operator.finished():
            positions = bus.read_positions()
            for j, i in zip(joints, index, strict=True):
                lo[j], hi[j] = min(lo[j], positions[i]), max(hi[j], positions[i])
            spans = " ".join(f"{j.split('_')[-1]}={hi[j] - lo[j]:.0f}" for j in joints)
            operator.progress(f"span (counts): {spans}")
            time.sleep(period_s)
    finally:
        bus.close()
    short = [j for j in joints if hi[j] - lo[j] < min_span]
    if short:
        raise SetupError(
            f"moved less than {min_span} counts: {short}; nothing saved, measure again"
        )
    travel = {j: (int(lo[j]), int(hi[j])) for j in joints}
    path = Path(out)
    path.write_text(
        "# Measured joint travel (raw counts) for current-mode runaway checks.\n"
        f"# Written by: roboloom measure-travel {cal.path}\n"
        + yaml.safe_dump(
            {
                "port": cal.data["port"],
                "measured": time.strftime("%Y-%m-%d"),
                "travel": {j: list(v) for j, v in travel.items()},
            },
            sort_keys=False,
        )
    )
    return Travel(cal.data["port"], travel, path)
