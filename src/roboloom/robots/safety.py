"""Final command check at the bus boundary and the follower mode state machine.

Modes: IDLE -> HOLD <-> ACTIVE; FAULT, ESTOP and RELEASED are latched.
HOLD keeps writing one fixed target (the last sent command, or the pose at
stop/start), never the freshly measured pose, so a gravity-loaded joint does not
creep. Small overshoots are clamped to `max_speed`; NaN, stale, out-of-range or
`max_jump` commands are rejected.
"""

from __future__ import annotations

import time

from ..core.checks import positions
from ..core.protocol import Envelope, Publisher
from ..drivers.base import JointState, disable_torque, read_health, read_state

MAX_CLAMP_DT_S = 0.1  # a stalled tick never widens the speed clamp beyond this


def make_command(
    publisher: Publisher,
    *,
    robot_id: str,
    unit: str,
    target: list[float],
    now_ns: int,
    deadline_ms: float,
    **extra: object,
) -> Envelope:
    """RobotCommand: target, unit and absolute deadline, validated again by FollowerSafety."""
    payload = {
        "robot_id": robot_id,
        "unit": unit,
        "positions": target,
        "deadline_ns": now_ns + int(deadline_ms * 1e6),
        **extra,
    }
    return publisher.make("command", payload, now_ns)


class FollowerSafety:
    """Checks every write at the bus boundary."""

    LATCHED = ("FAULT", "ESTOP", "RELEASED")

    def __init__(self, cfg: dict, bus):
        self.cfg, self.bus = cfg, bus
        self.dim = len(cfg["limits"])
        self.names = [
            limit.get("name", str(i)) for i, limit in enumerate(cfg["limits"])
        ]
        self.last_reject = (
            ""  # why the latest command was refused, for the operator screen
        )
        self.health = cfg.get("health") or {}
        self.period_s = 1 / cfg.get("control_hz", 30)
        self.publisher = Publisher(cfg.get("name", "robot"))
        self.mode = "IDLE"
        self.reason = ""
        self.pending: Envelope | None = None
        self.last_boot: str | None = None
        self.last_seq = -1
        self.state: JointState | None = None
        self.hold_target: list[float] | None = None
        self.last_sent: list[float] | None = None
        self.last_tick_ns: int | None = None
        self.ticks = 0
        self.over_current_since: list[int | None] = [None] * self.dim
        self.armed = False

    @property
    def current(self) -> list[float] | None:
        return self.state.positions if self.state else None

    def _read(self) -> JointState:
        state = read_state(self.bus)
        positions(state.positions, self.dim)
        self.state = state
        return state

    def _latch(self, mode: str, reason: str) -> None:
        self.mode, self.reason = mode, reason
        self.pending = None
        self.armed = False

    def start(self) -> None:
        state = self._read()
        if not self.cfg.get("torque", True):
            self._latch("RELEASED", "configured without torque")
            return
        self.hold_target = list(state.positions)
        self.bus.write_positions(self.hold_target)  # seed the goal before torque
        self.bus.enable_torque()
        self.mode = "HOLD"

    def accept(self, command: Envelope) -> None:
        if not self.armed or self.mode in self.LATCHED:
            return
        if (
            command.kind != "command"
            or command.payload.get("robot_id") != self.cfg["robot_id"]
            or command.payload.get("unit") != self.cfg.get("unit", "dynamixel_count")
        ):
            return
        if command.boot_id != self.last_boot:
            self.last_boot, self.last_seq = command.boot_id, -1
        if command.seq <= self.last_seq:
            return
        self.last_seq = command.seq
        self.pending = command  # latest only

    def stop(self, estop: bool = False) -> None:
        self.pending = None
        self.armed = False
        if self.mode in self.LATCHED:
            return
        try:
            self.hold_target = list(self.last_sent or self._read().positions)
            self.bus.write_positions(self.hold_target)
        except Exception as exc:  # noqa: BLE001 - every bus failure must latch FAULT
            self._latch("FAULT", f"bus: {exc}")
            return
        self.mode = "ESTOP" if estop else "HOLD"

    def release(self) -> None:
        """Torque off. Only when not moving; the operator must support the arm."""
        if self.armed or self.mode == "ACTIVE":
            raise RuntimeError("stop the robot before release")
        disable_torque(self.bus)
        self._latch("RELEASED", "operator release")

    def arm(self) -> None:
        if self.mode not in self.LATCHED:
            self.armed = True

    def _check_health(self, now: int) -> str | None:
        self.ticks += 1
        if not self.health or self.ticks % self.health["every_ticks"]:
            return None
        health = read_health(self.bus)
        if health is not None:
            if health.watchdog_fired:
                return "bus watchdog fired"
            if any(health.hardware_error):
                return f"hardware error {health.hardware_error}"
            limit = self.health.get("max_temperature_c")
            if limit is not None and max(health.temperature_c, default=0) > limit:
                return f"temperature {max(health.temperature_c)} C > {limit} C"
        limits = self.health.get("max_current_mA")
        currents = self.state.currents_mA if self.state else None
        if limits and currents:
            for i, (current, limit) in enumerate(zip(currents, limits, strict=True)):
                if abs(current) <= limit:
                    self.over_current_since[i] = None
                    continue
                since = self.over_current_since[i] = self.over_current_since[i] or now
                if now - since > self.health["over_current_s"] * 1e9:
                    return f"joint {i} current {current:.0f} mA > {limit} mA"
        return None

    def _checked(
        self, command: Envelope, now: int, dt: float
    ) -> tuple[list[float] | None, bool, str]:
        """Return (target, clamped, reject reason). Out-of-range joints are clipped to the range
        (as YAM does); NaN, stale commands and jumps beyond `max_jump` are rejected."""
        try:
            target = positions(command.payload["positions"], self.dim)
        except (KeyError, ValueError) as exc:
            return None, False, f"bad positions: {exc}"
        deadline = command.payload.get("deadline_ns", 0)
        if not command.t_ready_ns <= now <= deadline:
            return (
                None,
                False,
                f"stale command ({(now - command.t_ready_ns) / 1e6:.0f} ms old)",
            )
        reference = self.last_sent or self.hold_target or self.current or target
        clamped = False
        out = []
        for name, x, ref, bound in zip(
            self.names, target, reference, self.cfg["limits"], strict=True
        ):
            inside = min(bound["max"], max(bound["min"], x))
            if abs(inside - ref) > bound["max_jump"]:
                return (
                    None,
                    False,
                    f"{name} jumps {inside - ref:+.0f} > max_jump {bound['max_jump']}",
                )
            step = bound["max_speed"] * dt
            limited = min(ref + step, max(ref - step, inside))
            clamped = clamped or limited != x
            out.append(limited)
        return out, clamped, ""

    def tick(self, now_ns: int | None = None) -> tuple[Envelope, Envelope]:
        now = time.monotonic_ns() if now_ns is None else now_ns
        dt = min(
            MAX_CLAMP_DT_S,
            self.period_s
            if self.last_tick_ns is None
            else (now - self.last_tick_ns) / 1e9,
        )
        sent, clamped, sent_ns, seq = False, False, 0, -1
        command: Envelope | None = None
        try:
            self._read()
            problem = self._check_health(now) if self.mode not in self.LATCHED else None
            if problem:
                self._latch("FAULT", problem)
            command, self.pending = self.pending, None
            if self.mode not in self.LATCHED and command is not None:
                target, clamped, why = self._checked(command, now, max(dt, 0.0))
                if target is None:
                    self.mode, self.last_reject = "HOLD", why
                else:
                    self.bus.write_positions(target)
                    sent, seq = True, command.seq
                    sent_ns = time.monotonic_ns() if now_ns is None else now
                    self.last_sent = self.hold_target = target
                    self.mode = "ACTIVE"
            if not sent and self.mode not in self.LATCHED:
                if self.hold_target is None:
                    self.hold_target = list(self.current or [])
                self.bus.write_positions(self.hold_target)
                self.mode = "HOLD"
        except Exception as exc:  # noqa: BLE001 - every bus failure must latch FAULT
            self._latch("FAULT", f"bus: {exc}")
        interval = 0.0 if self.last_tick_ns is None else (now - self.last_tick_ns) / 1e6
        self.last_tick_ns = now
        state = self.state or JointState(self.hold_target or [0.0] * self.dim)
        state_msg = self.publisher.make(
            "robot_state",
            {
                "positions": state.positions,
                "velocities": state.velocities,
                "currents_mA": state.currents_mA,
                "mode": self.mode,
                "reason": self.reason,
                "tick_interval_ms": interval,
                "target": self.hold_target,
                "rejected": bool(
                    command is not None and not sent and self.mode == "HOLD"
                ),
            },
            now,
        )
        action = self.publisher.make(
            "action",
            {
                "positions": self.last_sent if sent else [0.0] * self.dim,
                "valid": sent,
                "clamped": clamped,
                "command_seq": seq,
                "t_sent_ns": sent_ns,
            },
            now,
        )
        return state_msg, action
