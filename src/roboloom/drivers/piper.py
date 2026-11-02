"""AgileX PiPER arm over CAN (piper_sdk, extra: piper). Joint positions in rad.

One `PiperBus` per arm, each on its own CAN interface (e.g. `can_left`, 1 Mbps). The
SDK keeps a receive thread and caches the latest frame of every kind; this class turns
that cache into the bus contract and refuses stale data:

- Opening waits until joint, motor and status feedback have actually arrived. Before the
  first frame the SDK reports zeros, which would seed a hold target of 0 rad (a jump).
- Every read checks the age of the cached frame (`stale_ms`): the SDK keeps returning
  the last values after a cable is pulled, so stale feedback raises ConnectionError and
  the follower latches FAULT.
- Writes switch the arm to CAN control, MOVE J (`speed_percent` of the firmware's joint
  speed) before each `JointCtrl`, as the vendor demos do.
- `close` disconnects without disabling the motors: what the arm does then is its
  `unattended` safety trait (not established yet; `roboloom check-hold` measures it).
  `disable_torque` disables them, and the arm falls.

Only joint position control (MOVE J) is used; its frames are the same in the V2 and V3
protocols, so the V2 interface of the stable SDK serves both firmware lines.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Any

from .base import Health, JointState

DIMENSION = 6
MILLIDEG_PER_RAD = 180_000 / math.pi
CAN_CONTROL = 0x01  # ctrl_mode: commanded over CAN (anything else: teach button, etc.)
MOVE_J = 0x01
ALL_MOTORS = 7
# foc_status bits of the low-speed motor feedback (bit 6 is "enabled", not an error)
FOC_ERRORS = {
    0: "supply voltage low",
    1: "motor over-temperature",
    2: "driver over-current",
    3: "driver over-temperature",
    4: "collision protection",
    5: "driver error",
    7: "stall protection",
}
FOC_ENABLED = 1 << 6
# low-speed feedback (temperatures, driver status) comes slower than joint feedback
LOW_SPEED_STALE_S = 0.5
ADMIN_HINT = (
    "check the arm's power and the CAN interface (1 Mbps, `ip -details link show {can}`); "
    "creating or renaming CAN interfaces needs sudo, so ask an administrator"
)


def connect(can: str) -> Any:
    """The SDK interface on `can`, connected (its receive thread running)."""
    from piper_sdk import C_PiperInterface_V2

    sdk = C_PiperInterface_V2(
        can,
        judge_flag=True,
        can_auto_init=True,
        start_sdk_joint_limit=False,  # FollowerSafety checks limits; no silent clipping
        start_sdk_gripper_limit=False,
    )
    sdk.ConnectPort()
    return sdk


class PiperBus:
    def __init__(
        self,
        can: str,
        speed_percent: int,
        *,
        stale_ms: float = 50.0,
        connect_timeout_s: float = 2.0,
        enable_timeout_s: float = 5.0,
        sdk: Any | None = None,
        clock: Callable[
            [], float
        ] = time.time,  # the SDK stamps frames with time.time()
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not 1 <= int(speed_percent) <= 100:
            raise ValueError("speed_percent must be 1..100")
        self.can, self.speed_percent = can, int(speed_percent)
        self.stale_s = stale_ms / 1000
        self.enable_timeout_s = enable_timeout_s
        self.clock, self.sleep = clock, sleep
        self.enabled = False  # we enabled the motors; a disabled motor is then a fault
        try:
            self.sdk = connect(can) if sdk is None else sdk
        except Exception as exc:
            raise ConnectionError(
                f"PiPER on {can}: {exc}; {ADMIN_HINT.format(can=can)}"
            ) from exc
        try:
            self._wait_feedback(connect_timeout_s)
            self.firmware = self._firmware()
        except BaseException:
            self.close()
            raise

    # -- opening -----------------------------------------------------------------

    def _feedback(self) -> dict[str, Any]:
        return {
            "joint": self.sdk.GetArmJointMsgs(),
            "motor": self.sdk.GetArmHighSpdInfoMsgs(),
            "driver": self.sdk.GetArmLowSpdInfoMsgs(),
            "status": self.sdk.GetArmStatus(),
        }

    def _wait_feedback(self, timeout_s: float) -> None:
        """Until every kind of feedback has arrived since opening: the SDK object is one
        per interface and keeps the frames of an earlier connection in the process."""
        opened = self.clock()
        deadline = opened + timeout_s
        while True:
            missing = [k for k, m in self._feedback().items() if m.time_stamp < opened]
            if not missing:
                return
            if self.clock() >= deadline:
                raise ConnectionError(
                    f"PiPER on {self.can}: no {', '.join(missing)} feedback within "
                    f"{timeout_s:.0f} s; {ADMIN_HINT.format(can=self.can)}"
                )
            self.sleep(0.01)

    def _firmware(self) -> str:
        self.sdk.SearchPiperFirmwareVersion()
        for _ in range(50):
            version = self.sdk.GetPiperFirmwareVersion()
            if isinstance(version, str):
                return version
            self.sleep(0.01)
        return "unknown"

    # -- reading ------------------------------------------------------------------

    def _fresh(self, msg: Any, what: str, limit_s: float | None = None) -> Any:
        age = self.clock() - msg.time_stamp
        if msg.time_stamp <= 0 or age > (limit_s or self.stale_s):
            raise ConnectionError(
                f"PiPER on {self.can}: {what} feedback is {age * 1e3:.0f} ms old "
                "(power, cable or CAN interface lost)"
            )
        return msg

    def _motors(self, msg: Any) -> list[Any]:
        return [getattr(msg, f"motor_{i}") for i in range(1, DIMENSION + 1)]

    def read_positions(self) -> list[float]:
        joints = self._fresh(self.sdk.GetArmJointMsgs(), "joint").joint_state
        return [
            getattr(joints, f"joint_{i}") / MILLIDEG_PER_RAD
            for i in range(1, DIMENSION + 1)
        ]

    def read_state(self) -> JointState:
        positions = self.read_positions()
        motors = self._motors(self._fresh(self.sdk.GetArmHighSpdInfoMsgs(), "motor"))
        return JointState(
            positions=positions,
            velocities=[m.motor_speed / 1000 for m in motors],  # 0.001 rad/s
            efforts_Nm=[m.effort / 1000 for m in motors],  # 0.001 N·m
        )

    def enable_status(self) -> list[bool]:
        driver = self._fresh(
            self.sdk.GetArmLowSpdInfoMsgs(), "driver", LOW_SPEED_STALE_S
        )
        return [bool(m.foc_status_code & FOC_ENABLED) for m in self._motors(driver)]

    def read_health(self) -> Health:
        status = self._fresh(self.sdk.GetArmStatus(), "status").arm_status
        driver = self._fresh(
            self.sdk.GetArmLowSpdInfoMsgs(), "driver", LOW_SPEED_STALE_S
        )
        faults = []
        if int(status.ctrl_mode) != CAN_CONTROL:
            faults.append(
                f"control mode {_name(status.ctrl_mode)}, not CAN (teach button or "
                "another controller)"
            )
        if int(status.arm_status) != 0:
            faults.append(f"arm status {_name(status.arm_status)}")
        errors = status.err_status
        for i in range(1, DIMENSION + 1):
            if getattr(errors, f"communication_status_joint_{i}", False):
                faults.append(f"joint{i}: communication error")
        codes, temperatures = [], []
        for i, motor in enumerate(self._motors(driver), start=1):
            code = int(motor.foc_status_code)
            codes.append(code & ~FOC_ENABLED)
            temperatures.append(float(max(motor.motor_temp, motor.foc_temp)))
            faults.extend(
                f"joint{i}: {text}"
                for bit, text in FOC_ERRORS.items()
                if code >> bit & 1
            )
            if self.enabled and not code & FOC_ENABLED:
                faults.append(f"joint{i}: motor disabled")
        return Health(hardware_error=codes, temperature_c=temperatures, faults=faults)

    # -- writing ------------------------------------------------------------------

    def write_positions(self, values: list[float]) -> None:
        if len(values) != DIMENSION:
            raise ValueError(f"PiPER takes {DIMENSION} joint positions")
        self.sdk.MotionCtrl_2(CAN_CONTROL, MOVE_J, self.speed_percent, 0x00)
        self.sdk.JointCtrl(*(round(v * MILLIDEG_PER_RAD) for v in values))

    def enable_torque(self) -> None:
        deadline = self.clock() + self.enable_timeout_s
        while not all(self.enable_status()):
            if self.clock() >= deadline:
                off = [i + 1 for i, on in enumerate(self.enable_status()) if not on]
                raise RuntimeError(
                    f"PiPER on {self.can}: joints {off} did not enable within "
                    f"{self.enable_timeout_s:.0f} s"
                )
            self.sdk.EnableArm(ALL_MOTORS)
            self.sleep(0.01)
        self.enabled = True

    def disable_torque(self) -> None:
        """Disable every motor: the arm falls (support it first)."""
        self.enabled = False
        self.sdk.DisableArm(ALL_MOTORS)

    def close(self) -> None:
        """Stop reading; the motors stay as they are (enabled ones keep their target)."""
        self.sdk.DisconnectPort()


def _name(value: Any) -> str:
    return getattr(value, "name", None) or f"0x{int(value):02X}"


def probe(can: str) -> str:
    """Read-only look at one arm: firmware, joints, modes, enable state, faults and
    feedback rates. Never enables or moves the arm (it only sends queries)."""
    bus = PiperBus(can, speed_percent=1)
    try:
        frames = bus._feedback()
        status = frames["status"].arm_status
        health = bus.read_health()
        positions = bus.read_positions()
        lines = [
            f"PiPER on {can}: firmware {bus.firmware}",
            (
                f"control mode {_name(status.ctrl_mode)}, arm status "
                f"{_name(status.arm_status)}, move mode {_name(status.mode_feed)}"
            ),
            "joints (rad / deg): "
            + ", ".join(
                f"joint{i} {p:+.4f} / {math.degrees(p):+.2f}"
                for i, p in enumerate(positions, start=1)
            ),
            "enabled: " + ", ".join(str(on) for on in bus.enable_status()),
            "temperature (C): " + ", ".join(f"{t:.0f}" for t in health.temperature_c),
            "feedback Hz: "
            + ", ".join(f"{k} {getattr(m, 'Hz', 0):.0f}" for k, m in frames.items()),
            "faults: " + ("; ".join(health.faults) if health.faults else "none"),
        ]
        errors = status.err_status
        limits = [
            i
            for i in range(1, DIMENSION + 1)
            if getattr(errors, f"joint_{i}_angle_limit", False)
        ]
        if limits:
            lines.append(f"joints at their angle limit: {limits}")
        return "\n".join(lines)
    finally:
        bus.close()
