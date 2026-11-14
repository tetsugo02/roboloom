"""PiPER follower: the follower node's exclusive owner of one arm's CAN interface."""

from __future__ import annotations

from ...core.checks import identity, positive
from ...drivers.mock import MockBus
from ...kinematics.spec import KinematicSpec
from ..base import FOLLOWER_KEYS, Follower, JointBus, SafetyTraits
from .spec import JOINTS, MODEL, REST, UNIT, check_within_range


class PiperFollower(Follower):
    """Joint position control through the arm's own controller (MOVE J).

    Keys besides the common follower ones: `can` (the CAN interface, e.g. `can_left`),
    `speed_percent` (1..100, the firmware's joint speed scale), `stale_ms` (optional,
    default 50: older feedback latches FAULT). `health:` is required: the arm reports its
    own faults (teach button, collision, driver errors) only through it.
    """

    model = "piper"
    keys = (*FOLLOWER_KEYS, "can", "speed_percent", "stale_ms")
    effort_signal = ("efforts_Nm", "N·m")
    # The arm falls when its motors are disabled (no brakes). Whether it keeps its target
    # once nothing commands it (process gone, CAN closed) is not established: measure it
    # per unit with `roboloom check-hold`, which records `unattended:` in the YAML.
    safety_traits = SafetyTraits(torque_off="falls", unattended="unknown")

    def __init__(self, name: str, cfg: dict):
        if "control" in cfg:
            raise ValueError(
                f"{name}.control: the PiPER runs its own position control; remove control"
            )
        super().__init__(name, cfg, JOINTS, UNIT)
        if not self.health:
            raise ValueError(
                f"{name}.health: required for PiPER (e.g. every_ticks: 10); the arm "
                "reports teach mode, collisions and driver faults only there"
            )
        check_within_range(self.limits, name)
        self.can = identity(cfg.get("can"), f"{name}.can")
        speed = cfg.get("speed_percent")
        if (
            not isinstance(speed, int)
            or isinstance(speed, bool)
            or not 1 <= speed <= 100
        ):
            raise ValueError(f"{name}.speed_percent: an integer 1..100")
        self.speed_percent = speed
        self.stale_ms = positive(cfg.get("stale_ms", 50), f"{name}.stale_ms")

    def device_ids(self) -> tuple[str, ...]:
        return (self.can,)

    def kinematics(self, part: str | None = None) -> KinematicSpec:
        return MODEL

    def open_bus(self, mock: bool) -> JointBus:
        if mock:
            bus = MockBus(dimension=len(JOINTS))
            bus.values = list(REST)
            return bus
        from ...drivers.piper import PiperBus

        return PiperBus(self.can, self.speed_percent, stale_ms=self.stale_ms)
