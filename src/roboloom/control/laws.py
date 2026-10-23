"""Control laws. Each maps the measured state (and an optional position target) to goals.

Units: positions and position targets in the device unit (Dynamixel counts),
velocities in counts/s, currents in mA. Current-mode laws ramp in over `ramp_s`
and clip to `max_current_mA` per joint.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import ClassVar

from ..core.checks import finite, positive
from ..drivers.base import JointState
from ..dynamics.base import GravityModel


class RunawayError(RuntimeError):
    """A current-mode joint moved too fast or left its range; the device must go limp."""


@dataclass
class Goals:
    positions: dict[int, float] = field(default_factory=dict)  # device joint index -> goal position
    currents_mA: dict[int, float] = field(default_factory=dict)  # device joint index -> goal current


def _per_joint(value: object, count: int, name: str) -> list[float]:
    values: list = value if isinstance(value, list) else [value] * count
    if len(values) != count or not all(finite(v) for v in values):
        raise ValueError(f"{name}: expected a number or one number per joint")
    return [float(v) for v in values]


class ControlLaw(ABC):
    mode: ClassVar[str | None]  # operating mode name; None keeps torque off
    current_mode: ClassVar[bool] = False
    hardware_validated: ClassVar[bool] = True
    # bus methods the law needs; JointDevice refuses a bus without them, so a robot whose
    # motors lack e.g. current commands cannot select the law
    needs: ClassVar[tuple[str, ...]] = ()

    def __init__(self, name: str, joints: list[int], joint_names: Sequence[str], cfg: dict, gravity: GravityModel | None = None):
        self.name, self.joints, self.cfg = name, joints, cfg
        self.device_joints = tuple(joint_names)
        self.gravity = gravity

    def reset(self, state: JointState) -> None:
        """Called when torque turns on, with the state measured just before."""

    @abstractmethod
    def compute(self, state: JointState, target: Sequence[float] | None, dt: float) -> Goals: ...


class Free(ControlLaw):
    """Torque off, e.g. a hand-guided leader joint."""

    mode = None

    def compute(self, state, target, dt):
        return Goals()


class Position(ControlLaw):
    """Goal position = target; without a target, hold the last goal."""

    mode = "position"
    needs: ClassVar[tuple[str, ...]] = ("write_goal_positions", "set_torque", "read_register")

    def reset(self, state):
        self.goal = {i: state.positions[i] for i in self.joints}

    def compute(self, state, target, dt):
        if target is not None:
            self.goal = {i: float(target[i]) for i in self.joints}
        return Goals(positions=dict(self.goal))


class CurrentPosition(Position):
    """Current-based position: goal current is the torque limit. A fixed `target` makes a spring."""

    mode = "current_position"
    needs = (*Position.needs, "write_goal_currents")

    def __init__(self, name, joints, joint_names, cfg, gravity=None):
        super().__init__(name, joints, joint_names, cfg, gravity)
        self.limit = _per_joint(cfg.get("goal_current_mA"), len(joints), f"{name}.goal_current_mA")
        self.fixed = None if cfg.get("target") is None else _per_joint(cfg["target"], len(joints), f"{name}.target")

    def compute(self, state, target, dt):
        if self.fixed is not None:
            target = None
            self.goal = dict(zip(self.joints, self.fixed, strict=True))
        goals = super().compute(state, target, dt)
        goals.currents_mA = dict(zip(self.joints, self.limit, strict=True))
        return goals


class Spring(CurrentPosition):
    """Return spring for a hand-operated joint, e.g. a leader gripper trigger.

    The joint is held at `rest` in current-based position mode; pushing it away meets a
    restoring force that grows with the displacement (the motor's position gain) and is
    capped by `goal_current_mA`, so the operator can always overpower it.
    """

    def __init__(self, name, joints, joint_names, cfg, gravity=None):
        if cfg.get("rest") is None:
            raise ValueError(f"{name}: spring needs rest (counts, one per joint or one for all)")
        super().__init__(name, joints, joint_names, {**cfg, "target": cfg["rest"]}, gravity)


class CurrentLaw(ControlLaw):
    """Shared current-mode machinery: gravity term, damping, range barrier, runaway check, ramp, clip."""

    mode = "current"
    current_mode = True
    needs = ("write_goal_currents", "set_torque", "read_register")

    def __init__(self, name, joints, joint_names, cfg, gravity=None):
        super().__init__(name, joints, joint_names, cfg, gravity)
        n = len(joints)
        self.max_current = [positive(x, f"{name}.max_current_mA") for x in _per_joint(cfg.get("max_current_mA"), n, f"{name}.max_current_mA")]
        self.kd = _per_joint(cfg.get("kd", 0.0), n, f"{name}.kd")  # mA per count/s
        self.gain = float(cfg.get("gravity_gain", 1.0 if gravity else 0.0))
        self.ramp_s = positive(cfg.get("ramp_s", 1.0), f"{name}.ramp_s")
        self.max_velocity = positive(cfg.get("max_velocity"), f"{name}.max_velocity")  # counts/s
        limits = cfg.get("range")
        if not isinstance(limits, list) or len(limits) != n or not all(isinstance(r, list) and len(r) == 2 and r[0] < r[1] for r in limits):
            raise ValueError(f"{name}.range needs [min, max] counts per joint")
        self.range = [(float(lo), float(hi)) for lo, hi in limits]
        self.margin = positive(cfg.get("range_margin", 100), f"{name}.range_margin")
        self.barrier = float(cfg.get("barrier_mA_per_count", 0.5))
        self.elapsed = 0.0
        if gravity is not None:
            missing = set(gravity.output_joints) ^ {joint_names[i] for i in joints}
            if missing:
                raise ValueError(f"{name}: gravity model joints differ from the group: {sorted(missing)}")
            if not set(gravity.joint_names) <= set(joint_names):
                raise ValueError(f"{name}: gravity model reads joints the device does not have")
            self.model_inputs = [list(joint_names).index(j) for j in gravity.joint_names]
            self.model_outputs = {list(joint_names).index(j): k for k, j in enumerate(gravity.output_joints)}

    def reset(self, state):
        self.elapsed = 0.0

    def gravity_mA(self, state: JointState) -> dict[int, float]:
        if self.gravity is None or not self.gain:
            return {i: 0.0 for i in self.joints}
        effort = self.gravity.effort_mA([state.positions[i] for i in self.model_inputs])
        return {i: self.gain * effort[self.model_outputs[i]] for i in self.joints}

    def shape(self, state: JointState, raw: dict[int, float], dt: float) -> Goals:
        self.elapsed += dt
        scale = min(1.0, self.elapsed / self.ramp_s)
        velocities = state.velocities or [0.0] * len(state.positions)
        out = {}
        for k, i in enumerate(self.joints):
            q, v = state.positions[i], velocities[i]
            lo, hi = self.range[k]
            if abs(v) > self.max_velocity or not lo - self.margin <= q <= hi + self.margin:
                raise RunawayError(f"{self.device_joints[i]}: q={q:.0f} v={v:.0f} outside the allowed range")
            push = self.barrier * (max(0.0, lo - q) - max(0.0, q - hi))
            value = scale * (raw[i] - self.kd[k] * v) + push
            out[i] = max(-self.max_current[k], min(self.max_current[k], value))
        return Goals(currents_mA=out)


class GravityComp(CurrentLaw):
    """Hand-guided joint that does not fall: current = gain * g(q) - kd * qdot + range barrier."""

    def __init__(self, name, joints, joint_names, cfg, gravity=None):
        if gravity is None:
            raise ValueError(f"{name}: gravity_comp needs a gravity model")
        super().__init__(name, joints, joint_names, cfg, gravity)

    def compute(self, state, target, dt):
        return self.shape(state, self.gravity_mA(state), dt)


class Impedance(CurrentLaw):
    """Joint impedance around the target: kp (q* - q) - kd qdot + gain g(q). Not validated on hardware."""

    hardware_validated = False

    def __init__(self, name, joints, joint_names, cfg, gravity=None):
        super().__init__(name, joints, joint_names, cfg, gravity)
        self.kp = _per_joint(cfg.get("kp"), len(joints), f"{name}.kp")  # mA per count

    def reset(self, state):
        super().reset(state)
        self.goal = {i: state.positions[i] for i in self.joints}

    def compute(self, state, target, dt):
        if target is not None:
            self.goal = {i: float(target[i]) for i in self.joints}
        g = self.gravity_mA(state)
        raw = {i: kp * (self.goal[i] - state.positions[i]) + g[i] for kp, i in zip(self.kp, self.joints, strict=True)}
        return self.shape(state, raw, dt)
