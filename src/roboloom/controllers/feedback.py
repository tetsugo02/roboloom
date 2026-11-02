"""Force feedback of a joint controller: follower effort residuals -> leader currents.

Configured as `feedback:` in the controller YAML. For each follower joint in `gain`, the
leader joint mapped to it in `joints` receives `-gain * sign * residual`, with an
absolute deadline. The controller only asks for the feedback to be applied (`gate`)
while the estimate is valid and in contact, the follower is ACTIVE and the pair is
following; the leader checks the deadline and ramps in and out.
"""

from __future__ import annotations

import time

from ..core.checks import finite, positive
from ..core.protocol import Envelope, Publisher
from ..estimators.base import Estimator
from ..robots.base import Robot


class FeedbackMap:
    kind = "feedback"

    def __init__(self, cfg: object, owner: str, mapping: list[dict]):
        where = f"{owner}.feedback"
        if not isinstance(cfg, dict):
            raise TypeError(f"{where} must be a mapping")
        estimator = cfg.get("estimator")
        if not isinstance(estimator, str) or not estimator:
            raise ValueError(f"{where}.estimator must name an estimator node")
        self.estimator_name = estimator
        self.deadline_ms = positive(cfg.get("deadline_ms"), f"{where}.deadline_ms")
        unit = cfg.get("unit")
        if not isinstance(unit, str) or unit.count("/") != 1:
            raise ValueError(f"{where}.unit must be <leader unit>/<estimator unit>")
        self.unit = unit
        gain = cfg.get("gain")
        if not isinstance(gain, dict) or not gain:
            raise ValueError(f"{where}.gain must map follower joints to gains")
        by_follower = {j["follower"]: j for j in mapping}
        for joint, k in gain.items():
            if joint not in by_follower:
                raise ValueError(
                    f"{where}.gain: {joint!r} is not a mapped follower joint"
                )
            if not finite(k) or k < 0:
                raise ValueError(f"{where}.gain.{joint} must be a finite number >= 0")
        self.follower_joints = list(gain)
        self.gain = [float(gain[j]) for j in self.follower_joints]
        self.leader_joints = [by_follower[j]["leader"] for j in self.follower_joints]
        self.signs = [int(by_follower[j]["sign"]) for j in self.follower_joints]
        self.owner = owner
        self.publisher = Publisher(owner)
        self.estimator_joints: tuple[str, ...] = ()
        self.estimator_unit = ""
        self.leader_unit = ""
        self.gate = False
        self.error = ""

    def bind(
        self, estimator: Estimator, robot: Robot, leader_units: dict[str, str]
    ) -> None:
        """Check the estimator, robot and leader this feedback connects."""
        where = f"{self.owner}.feedback"
        if estimator.robot != robot.name:
            raise ValueError(
                f"{where}: estimator {estimator.name!r} reads robot {estimator.robot!r}, "
                f"not this controller's robot {robot.name!r}"
            )
        missing = set(self.follower_joints) - set(estimator.joint_names)
        if missing:
            raise ValueError(
                f"{where}.gain: estimator {estimator.name!r} does not estimate {sorted(missing)}"
            )
        refused = [j for j in self.leader_joints if j not in leader_units]
        if refused:
            raise ValueError(
                f"{where}: leader joints {refused} take no feedback "
                "(add feedback: to their current-mode group)"
            )
        units = {leader_units[j] for j in self.leader_joints}
        if len(units) != 1:
            raise ValueError(f"{where}: leader joints take mixed units {sorted(units)}")
        (self.leader_unit,) = units
        expected = f"{self.leader_unit}/{estimator.unit}"
        if self.unit != expected:
            raise ValueError(f"{where}.unit must be {expected!r}, got {self.unit!r}")
        self.estimator_joints = estimator.joint_names
        self.estimator_unit = estimator.unit

    def make(
        self,
        estimate: Envelope,
        follower_mode: str | None,
        following: bool,
        now_ns: int | None = None,
    ) -> Envelope | None:
        """The leader feedback for one estimate, or None when the estimate does not fit."""
        now = time.monotonic_ns() if now_ns is None else now_ns
        payload = estimate.payload
        residual = payload.get("residual")
        robot_t = payload.get("robot_t_ns")
        if (
            estimate.kind != Estimator.kind
            or not isinstance(robot_t, int)
            or isinstance(robot_t, bool)
            or robot_t > now
            or tuple(payload.get("joints") or ()) != self.estimator_joints
            or payload.get("unit") != self.estimator_unit
            or not isinstance(residual, list)
            or len(residual) != len(self.estimator_joints)
        ):
            self.gate = False
            self.error = (
                f"estimate from {estimate.source_id} does not match its configuration"
            )
            return None
        # The deadline counts from the robot sample, not from now: a late estimate
        # (a stalled estimator) must not renew an old force.
        deadline = robot_t + int(self.deadline_ms * 1e6)
        if deadline < now:
            self.gate = False
            self.error = (
                f"estimate from {estimate.source_id} is stale "
                f"({(now - robot_t) / 1e6:.0f} ms after its robot sample)"
            )
            return None
        self.error = ""
        by_joint = dict(zip(self.estimator_joints, residual, strict=True))
        effort = [
            -k * sign * float(by_joint[j])
            for k, sign, j in zip(
                self.gain, self.signs, self.follower_joints, strict=True
            )
        ]
        self.gate = bool(
            payload.get("valid")
            and payload.get("contact")
            and follower_mode == "ACTIVE"
            and following
        )
        return self.publisher.make(
            self.kind,
            {
                "joints": list(self.leader_joints),
                "effort": effort,
                "unit": self.leader_unit,
                "deadline_ns": deadline,
                "gate": self.gate,
                "robot_t_ns": robot_t,
            },
            now,
        )
