"""Controller mapping and follower safety state machine."""

from __future__ import annotations

import math
import time

from .config import JOINTS
from .protocol import Envelope, Publisher


def positions(value: object, dimension: int = len(JOINTS)) -> list[float]:
    if not isinstance(value, (tuple, list)) or len(value) != dimension:
        raise ValueError(f"expected {dimension} joint positions")
    out = [float(x) for x in value]
    if not all(math.isfinite(x) for x in out):
        raise ValueError("joint positions must be finite")
    return out


class JointController:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.publisher = Publisher("controller")
        self.last_input_ns = 0
        self.last_seq = -1
        self.last_boot: str | None = None
        self.last_target: list[float] | None = None
        self.last_target_ns = 0
        self.aligned = False

    def update(
        self, leader: Envelope, follower: list[float], now_ns: int | None = None
    ) -> Envelope | None:
        now = time.monotonic_ns() if now_ns is None else now_ns
        if (
            leader.kind != "leader"
            or now - leader.t_ready_ns > self.cfg["input_timeout_ms"] * 1e6
            or leader.t_ready_ns > now
        ):
            self.aligned = False
            return None
        if leader.boot_id != self.last_boot:
            self.last_boot, self.last_seq = leader.boot_id, -1
            self.aligned = False
        if leader.seq <= self.last_seq:
            return None
        self.last_seq = leader.seq
        incoming = positions(leader.payload["positions"])
        by_name = dict(zip(JOINTS, incoming, strict=True))
        target = [
            by_name[j["leader"]] * j["sign"] + j["offset"] for j in self.cfg["joints"]
        ]
        current = positions(follower)
        if not self.aligned:
            if (
                max(abs(a - b) for a, b in zip(target, current, strict=True))
                > self.cfg["alignment_tolerance"]
            ):
                return None
            self.aligned = True
            self.last_target = current
            self.last_target_ns = now
        dt = max((now - self.last_target_ns) / 1e9, 1e-6)
        step = self.cfg["max_speed_counts_per_s"] * dt
        previous = self.last_target
        if previous is None:
            raise RuntimeError("controller target missing after alignment")
        limited = [
            max(p - step, min(p + step, t))
            for p, t in zip(previous, target, strict=True)
        ]
        self.last_target, self.last_target_ns = limited, now
        deadline = now + int(self.cfg["command_deadline_ms"] * 1e6)
        return self.publisher.make(
            "command",
            {
                "robot_id": self.cfg["robot_id"],
                "unit": "dynamixel_count",
                "positions": limited,
                "deadline_ns": deadline,
                "leader_seq": leader.seq,
            },
            now,
        )


class FollowerSafety:
    """Checks every write at the bus boundary. FAULT and ESTOP are latched."""

    def __init__(self, cfg: dict, bus):
        self.cfg, self.bus = cfg, bus
        self.publisher = Publisher("robot")
        self.mode = "IDLE"
        self.pending: Envelope | None = None
        self.last_boot: str | None = None
        self.last_seq = -1
        self.current: list[float] | None = None
        self.last_sent: list[float] | None = None
        self.last_tick_ns: int | None = None
        self.armed = False

    def start(self) -> None:
        self.current = positions(self.bus.read_positions(), len(self.cfg["limits"]))
        self.bus.write_positions(self.current)  # seed current goal before torque
        self.bus.enable_torque()
        self.mode = "HOLD"

    def accept(self, command: Envelope) -> None:
        if not self.armed or self.mode in ("FAULT", "ESTOP"):
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
        if self.mode not in ("FAULT", "ESTOP"):
            try:
                self.current = positions(
                    self.bus.read_positions(), len(self.cfg["limits"])
                )
                self.bus.write_positions(self.current)
            except Exception:  # noqa: BLE001 - every bus failure must latch FAULT
                self.mode = "FAULT"
                return
            self.mode = "ESTOP" if estop else "HOLD"

    def arm(self) -> None:
        if self.mode not in ("FAULT", "ESTOP"):
            self.armed = True

    def tick(self, now_ns: int | None = None) -> tuple[Envelope, Envelope]:
        now = time.monotonic_ns() if now_ns is None else now_ns
        sent = False
        sent_ns = 0
        seq = -1
        try:
            current = positions(self.bus.read_positions(), len(self.cfg["limits"]))
            self.current = current
            command = self.pending
            self.pending = None
            if self.mode not in ("FAULT", "ESTOP") and command is not None:
                target = positions(
                    command.payload["positions"], len(self.cfg["limits"])
                )
                if not (
                    command.t_ready_ns <= now <= command.payload["deadline_ns"]
                ) or any(
                    x < bound["min"]
                    or x > bound["max"]
                    or abs(x - p) > bound["max_step"]
                    for x, p, bound in zip(
                        target, current, self.cfg["limits"], strict=True
                    )
                ):
                    self.mode = "HOLD"
                else:
                    self.bus.write_positions(target)
                    sent, seq = True, command.seq
                    sent_ns = time.monotonic_ns() if now_ns is None else now
                    self.last_sent = target
                    self.mode = "ACTIVE"
            if not sent and self.mode not in ("FAULT", "ESTOP"):
                self.bus.write_positions(current)
                self.mode = "HOLD"
        except Exception:  # noqa: BLE001 - every bus failure must latch FAULT
            self.mode = "FAULT"
            self.pending = None
            current = self.current or [0.0] * len(self.cfg["limits"])
        interval = 0.0 if self.last_tick_ns is None else (now - self.last_tick_ns) / 1e6
        self.last_tick_ns = now
        state = self.publisher.make(
            "robot",
            {"positions": current, "mode": self.mode, "tick_interval_ms": interval},
            now,
        )
        action = self.publisher.make(
            "action",
            {
                "positions": self.last_sent
                if sent
                else [0.0] * len(self.cfg["limits"]),
                "valid": sent,
                "command_seq": seq,
                "t_sent_ns": sent_ns,
            },
            now,
        )
        return state, action
