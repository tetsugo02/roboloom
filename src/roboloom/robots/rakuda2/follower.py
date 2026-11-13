"""Rakuda2 follower: the follower node's exclusive owner of the follower bus."""

from __future__ import annotations

import math
from pathlib import Path

import yaml

from ...control.device import law_class
from ...core.checks import identity
from ...core.resources import resolve
from ...kinematics.spec import KinematicSpec
from ..base import Follower, JointBus, SafetyTraits
from .spec import (
    ARM_BASE,
    ARM_TIP,
    COUNTS_PER_TURN,
    FOLLOWER_MODELS,
    JOINTS,
    MOTOR_IDS,
    PARTS,
    UNIT,
    check_motor_ids,
    expected_registers,
    open_rakuda_bus,
)


class RakudaFollower(Follower):
    model = "rakuda2"
    effort_signal = ("currents_mA", "mA")
    PARTS = PARTS

    def __init__(self, name: str, cfg: dict):
        super().__init__(name, cfg, JOINTS, UNIT)
        check_motor_ids(cfg, name)
        expected_registers(cfg, name)
        self.port = identity(cfg.get("port"), f"{name}.port")

    def declared_traits(self) -> SafetyTraits:
        # The arms and head fall without torque. Position-mode joints keep their last goal
        # when the node stops writing; current-mode joints go limp (JointDevice.close and
        # the bus watchdog), so a follower running current laws does not hold.
        current = any(law_class(g.law).current_mode for g in self.control or [])
        return SafetyTraits(
            torque_off="falls", unattended="torque_off" if current else "holds"
        )

    def kinematics(self, part: str | None = None) -> KinematicSpec | None:
        """An arm's chain, from the joint map in a calibration file:

            kinematics:
              right_arm: ../calibration/follower_right.yaml
              left_arm: ../calibration/follower_left.yaml

        The file lists, per joint, the URDF joint, the count at the URDF's zero pose
        (`zero`) and the direction (+1/-1): per-unit values, measured with
        `roboloom calibrate-joints`. Until its `confirmed` is true the map is a guess,
        and controllers refuse to move the robot with it. The torso is not part of the
        chain: poses are relative to the frame that turns with it."""
        files = self.cfg.get("kinematics") or {}
        if part not in ARM_TIP or part not in files:
            return None
        base_dir = Path(self.cfg.get("__dir__") or ".")
        path = resolve(str(files[part]), base_dir)
        data = yaml.safe_load(Path(path).read_text())
        by_name = {j.get("name"): j for j in data.get("joints") or []}
        joints = self.parts()[part]
        missing = [j for j in joints if j not in by_name]
        if missing:
            raise ValueError(f"{self.name}.kinematics.{part}: {path} lacks {missing}")
        rows = [by_name[j] for j in joints]
        for row in rows:
            if row.get("direction") not in (1, -1) or not isinstance(
                row.get("zero"), (int, float)
            ):
                raise ValueError(
                    f"{path}: {row['name']} needs direction +1/-1 and a zero count"
                )
        per_count = 2 * math.pi / COUNTS_PER_TURN
        return KinematicSpec(
            Path(resolve(data["urdf"], Path(path).parent)),
            base=ARM_BASE,
            tip=ARM_TIP[part],
            joints=tuple(str(row["urdf"]) for row in rows),
            follower_joints=tuple(joints),
            scale=tuple(row["direction"] * per_count for row in rows),
            offset=tuple(float(row["zero"]) for row in rows),
            confirmed=bool(data.get("confirmed", False)),
        )

    def expected_eeprom(
        self,
    ) -> tuple[list[str], list[int], dict[str, dict[str, float]]]:
        """Joints, motor IDs and the EEPROM values `roboloom commission` writes."""
        return list(JOINTS), list(MOTOR_IDS), expected_registers(self.cfg, self.name)

    def current_limits_mA(self) -> dict[str, float]:
        return expected_registers(self.cfg, self.name).get("current_limit", {})

    def device_ids(self) -> tuple[str, ...]:
        return (self.port,)

    def open_bus(self, mock: bool) -> JointBus:
        return open_rakuda_bus(
            self.port, mock, FOLLOWER_MODELS, self.cfg, self.name, self.limits
        )
