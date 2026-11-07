"""Forward and inverse kinematics of one arm with pinocchio (extra: ik).

The URDF is reduced to the follower's joints (every other joint locked at 0), and a tool
frame `tool` is attached to the tip. `solve` runs damped least squares on the tool
frame's pose error, from a seed (the target the follower holds) and inside the joint
limits; it is deterministic, and a result that does not reach the target within the
tolerances is reported as such (the caller sends nothing then).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from .spec import KinematicSpec, Pose

TOOL_FRAME = "roboloom_tool"


@dataclass(frozen=True)
class IkResult:
    q: list[float]  # in the follower's joint order
    position_error_m: float
    rotation_error_rad: float
    iterations: int
    reached: bool


class ArmModel:
    def __init__(self, spec: KinematicSpec, tool: Pose | None = None):
        try:
            import pinocchio as pin
        except ImportError as exc:
            raise ImportError(
                "pose controllers need pinocchio: install roboloom with the ik extra "
                "(uv add git+https://github.com/tetsugo02/roboloom.git --extra ik; "
                "in a roboloom checkout: uv sync --extra ik)"
            ) from exc
        self.pin = pin
        full = pin.buildModelFromUrdf(str(spec.urdf))
        names = list(full.names)[1:]  # 0 is the universe
        missing = [j for j in spec.joints if j not in names]
        if missing:
            raise ValueError(f"{spec.urdf.name}: no joints {missing}")
        lock = [full.getJointId(n) for n in names if n not in spec.joints]
        model = pin.buildReducedModel(full, lock, pin.neutral(full)) if lock else full
        if model.nq != len(spec.joints) or model.nv != len(spec.joints):
            raise ValueError(
                f"{spec.urdf.name}: the joints {list(spec.joints)} are not all revolute"
            )
        self.index = [model.idx_qs[model.getJointId(j)] for j in spec.joints]
        for frame in (spec.base, spec.tip):
            if not model.existFrame(frame):
                raise ValueError(f"{spec.urdf.name}: no link {frame!r}")
        tip = model.frames[model.getFrameId(spec.tip)]
        placement = tip.placement * pin.SE3(
            np.eye(3) if tool is None else tool[:3, :3],
            np.zeros(3) if tool is None else tool[:3, 3],
        )
        self.tool = model.addFrame(
            pin.Frame(TOOL_FRAME, tip.parentJoint, placement, pin.FrameType.OP_FRAME)
        )
        self.base = model.getFrameId(spec.base)
        self.model, self.data = model, model.createData()
        self.joints = spec.joints

    def _q(self, joints: Sequence[float]) -> np.ndarray:
        q = np.zeros(self.model.nq)
        for i, value in zip(self.index, joints, strict=True):
            q[i] = float(value)
        return q

    def _joints(self, q: np.ndarray) -> list[float]:
        return [float(q[i]) for i in self.index]

    def _tool_in_base(self, q: np.ndarray):
        pin = self.pin
        pin.framesForwardKinematics(self.model, self.data, q)
        return self.data.oMf[self.base].actInv(self.data.oMf[self.tool])

    def fk(self, joints: Sequence[float]) -> Pose:
        """The tool's pose in the base frame at `joints` (follower order)."""
        return np.asarray(self._tool_in_base(self._q(joints)).homogeneous)

    def solve(
        self,
        target: Pose,
        seed: Sequence[float],
        lower: Sequence[float],
        upper: Sequence[float],
        *,
        iterations: int = 30,
        damping: float = 1e-3,
        position_tolerance_m: float = 1e-3,
        rotation_tolerance_rad: float = 1e-2,
        max_step_rad: float = 0.2,
    ) -> IkResult:
        """Joints that put the tool at `target`. Each iteration moves a joint by at most
        `max_step_rad`, so a far target cannot throw the arm onto another branch of
        solutions in one step."""
        pin = self.pin
        goal = pin.SE3(np.asarray(target[:3, :3]), np.asarray(target[:3, 3]))
        low, high = self._q(lower), self._q(upper)
        q = np.clip(self._q(seed), low, high)
        position, rotation, done = np.inf, np.inf, 0
        for done in range(iterations + 1):
            current = self._tool_in_base(q)
            error = current.actInv(goal)  # the remaining motion, in the tool frame
            position = float(np.linalg.norm(error.translation))
            rotation = float(np.linalg.norm(pin.log3(error.rotation)))
            if position <= position_tolerance_m and rotation <= rotation_tolerance_rad:
                break
            if done == iterations:
                break
            # tool-frame Jacobian of the base-relative pose (the base is fixed)
            pin.computeJointJacobians(self.model, self.data, q)
            jacobian = pin.getFrameJacobian(
                self.model, self.data, self.tool, pin.ReferenceFrame.LOCAL
            )
            jacobian = pin.Jlog6(error.inverse()) @ jacobian
            twist = pin.log6(error).vector
            step = jacobian.T @ np.linalg.solve(
                jacobian @ jacobian.T + damping * np.eye(6), twist
            )
            largest = float(np.max(np.abs(step)))
            if largest > max_step_rad:
                step = step * (max_step_rad / largest)
            q = np.clip(q + step, low, high)
        return IkResult(
            self._joints(q),
            position,
            rotation,
            done,
            position <= position_tolerance_m and rotation <= rotation_tolerance_rad,
        )
