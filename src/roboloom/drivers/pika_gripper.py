"""AgileX Pika Gripper over its USB serial link. One joint: the motor angle in rad.

The command codes, feedback fields and status bits are those of the vendor's pika_sdk
(`pika/gripper.py`, `API_Doc.md`) and pika_ros (`serial_gripper_imu.cpp`); none of this
has been checked on hardware yet. Like `PiperBus`, this class turns the cached feedback
into the bus contract and refuses stale data:

- Opening waits until motor and status feedback arrive after the port opened.
- Every read checks the age of the cached value (`stale_ms`): the device stops talking
  when it loses power or USB, so old feedback raises ConnectionError and the follower
  latches FAULT.
- Enabling first sets the motor current limit (`current_limit_A`, command 15, as the
  ROS node does at start), then enables until the status says so.
- `close` closes the port without disabling the motor: what the gripper does then is its
  `unattended` safety trait (`roboloom check-hold` measures it). `disable_torque`
  disables it, and the gripper lets go.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from .base import Health, JointState
from .pika_serial import PORT_HINT, PikaSerial

DISABLE, ENABLE, SET_ZERO, CURRENT_LIMIT, POSITION = 10, 11, 12, 15, 22
# `motorstatus.Status` bits (bit 6 is "enabled", bit 7 "homed": not errors)
STATUS_ERRORS = {
    0: "supply voltage low",
    1: "motor over-temperature",
    2: "over-current",
    3: "driver over-temperature",
    4: "sensor abnormal",
    5: "driver error",
}
ENABLED = 1 << 6
HOMED = 1 << 7
FEEDBACK = ("motor", "motorstatus")
SETTLE_S = 0.05  # feedback must keep arriving this long after opening


def status_bits(value: Any) -> int:
    """`Status` comes as a hex string ("0x40"); accept a number too."""
    if isinstance(value, str):
        return int(value, 16)
    return int(value)


class PikaGripperBus:
    def __init__(
        self,
        port: str,
        current_limit_A: float,
        *,
        stale_ms: float = 100.0,
        connect_timeout_s: float = 2.0,
        enable_timeout_s: float = 2.0,
        transport: PikaSerial | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not 0 < current_limit_A:
            raise ValueError("current_limit_A must be positive")
        self.port, self.current_limit_A = port, float(current_limit_A)
        self.stale_s = stale_ms / 1000
        self.enable_timeout_s = enable_timeout_s
        self.clock, self.sleep = clock, sleep
        self.enabled = False  # we enabled the motor; a disabled motor is then a fault
        self.link = PikaSerial(port, clock=clock) if transport is None else transport
        try:
            self._wait_feedback(connect_timeout_s)
        except BaseException:
            self.close()
            raise

    def _wait_feedback(self, timeout_s: float) -> None:
        opened = self.clock()
        deadline = opened + timeout_s
        while True:
            missing = []
            for key in FEEDBACK:
                got = self.link.latest(key)
                if got is None or got[1] < opened + SETTLE_S:
                    missing.append(key)
            if not missing:
                return
            if self.clock() >= deadline:
                raise ConnectionError(
                    f"Pika Gripper on {self.port}: no {', '.join(missing)} feedback "
                    f"within {timeout_s:.0f} s; {PORT_HINT}"
                )
            self.sleep(0.01)

    def _fresh(self, key: str) -> dict[str, Any]:
        got = self.link.latest(key)
        age = float("inf") if got is None else self.clock() - got[1]
        if got is None or age > self.stale_s:
            shown = "none" if got is None else f"{age * 1e3:.0f} ms old"
            raise ConnectionError(
                f"Pika Gripper on {self.port}: {key} feedback {shown} "
                "(power or USB lost)"
            )
        value = got[0]
        if not isinstance(value, dict):
            raise ConnectionError(f"Pika Gripper on {self.port}: bad {key}: {value!r}")
        return value

    # -- reading ------------------------------------------------------------------

    def read_positions(self) -> list[float]:
        return [float(self._fresh("motor")["Position"])]

    def read_state(self) -> JointState:
        motor = self._fresh("motor")
        return JointState(
            positions=[float(motor["Position"])],
            velocities=[float(motor.get("Speed", 0.0))],  # rad/s
            currents_mA=[float(motor.get("Current", 0.0))],  # phase current
        )

    def status(self) -> int:
        return status_bits(self._fresh("motorstatus").get("Status", 0))

    def enable_status(self) -> list[bool]:
        return [bool(self.status() & ENABLED)]

    def read_health(self) -> Health:
        status = self._fresh("motorstatus")
        code = status_bits(status.get("Status", 0))
        faults = [text for bit, text in STATUS_ERRORS.items() if code >> bit & 1]
        if self.enabled and not code & ENABLED:
            faults.append("motor disabled")
        temperature = max(
            float(status.get("MotorTemp", 0)), float(status.get("DriverTemp", 0))
        )
        return Health(
            hardware_error=[code & ~(ENABLED | HOMED)],
            temperature_c=[temperature],
            faults=[f"gripper: {f}" for f in faults],
        )

    # -- writing ------------------------------------------------------------------

    def write_positions(self, values: list[float]) -> None:
        if len(values) != 1:
            raise ValueError("the Pika Gripper takes one position (rad)")
        self.link.send(POSITION, values[0])

    def enable_torque(self) -> None:
        self.link.send(CURRENT_LIMIT, self.current_limit_A)
        deadline = self.clock() + self.enable_timeout_s
        while not all(self.enable_status()):
            if self.clock() >= deadline:
                raise RuntimeError(
                    f"Pika Gripper on {self.port}: did not enable within "
                    f"{self.enable_timeout_s:.0f} s"
                )
            self.link.send(ENABLE)
            self.sleep(0.02)
        self.enabled = True

    def disable_torque(self) -> None:
        """Disable the motor: the gripper lets go of what it holds."""
        self.enabled = False
        self.link.send(DISABLE)

    def close(self) -> None:
        """Stop reading; the motor stays as it is (enabled: it keeps its target)."""
        self.link.close()


def probe(port: str, *, seconds: float = 1.0) -> str:
    """Read-only look at one gripper: version, angle, status bits, temperatures, voltage
    and feedback rates. Never enables or moves it (it only asks for the version)."""
    bus = PikaGripperBus(port, current_limit_A=1.0)  # the limit is sent only on enable
    try:
        link = bus.link
        before = {k: link.count(k) for k in FEEDBACK}
        link.send_line("GET_INFO")
        time.sleep(seconds)
        rates = {k: (link.count(k) - before[k]) / seconds for k in FEEDBACK}
        version = link.latest("Version")
        state = bus.read_state()
        status = bus._fresh("motorstatus")
        code = status_bits(status.get("Status", 0))
        health = bus.read_health()
        return "\n".join(
            [
                f"Pika Gripper on {port}: version "
                + (str(version[0]) if version else "unknown (no reply to GET_INFO)"),
                (
                    f"angle {state.positions[0]:+.4f} rad, speed "
                    f"{(state.velocities or [0.0])[0]:+.3f} rad/s, current "
                    f"{(state.currents_mA or [0.0])[0]:.0f} mA"
                ),
                (
                    f"status 0x{code:02X}: enabled {bool(code & ENABLED)}, homed "
                    f"{bool(code & HOMED)}"
                ),
                (
                    f"voltage {float(status.get('Voltage', 0)):.1f} V, temperature "
                    f"(C) motor {float(status.get('MotorTemp', 0)):.0f}, driver "
                    f"{float(status.get('DriverTemp', 0)):.0f}"
                ),
                "feedback Hz: " + ", ".join(f"{k} {r:.0f}" for k, r in rates.items()),
                "faults: " + ("; ".join(health.faults) if health.faults else "none"),
            ]
        )
    finally:
        bus.close()
