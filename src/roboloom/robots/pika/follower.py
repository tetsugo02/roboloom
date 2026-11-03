"""Pika Gripper follower: the follower node's exclusive owner of one gripper's serial port."""

from __future__ import annotations

from ...core.checks import identity, positive
from ...drivers.mock import MockBus
from ..base import Follower, JointBus, SafetyTraits
from .spec import JOINTS, MAX_CURRENT_A, REST, UNIT, check_within_range


class PikaGripperFollower(Follower):
    """Position control of the gripper's motor angle by its own driver.

    Keys besides the common follower ones: `port` (the serial port; a stable
    `/dev/serial/by-path/...` path), `current_limit_A` (the motor current limit sent
    before enabling, 0 < x <= 2), `stale_ms` (optional, default 100: older feedback
    latches FAULT). `health:` is required: the gripper reports over-current, temperature
    and driver faults only through it.
    """

    model = "pika_gripper"
    effort_signal = ("currents_mA", "mA")
    # Without torque the gripper lets go of what it holds (assumed: it has no brake).
    # Whether it keeps its target once nothing commands it is not established: measure
    # it per unit with `roboloom check-hold`, which records `unattended:` in the YAML.
    safety_traits = SafetyTraits(torque_off="lets_go", unattended="unknown")

    def __init__(self, name: str, cfg: dict):
        if "control" in cfg:
            raise ValueError(
                f"{name}.control: the Pika Gripper runs its own position control; "
                "remove control"
            )
        super().__init__(name, cfg, JOINTS, UNIT)
        if not self.health:
            raise ValueError(
                f"{name}.health: required for the Pika Gripper (e.g. every_ticks: 10); "
                "it reports over-current and driver faults only there"
            )
        check_within_range(self.limits, name)
        self.port = identity(cfg.get("port"), f"{name}.port")
        limit = cfg.get("current_limit_A")
        if (
            not isinstance(limit, (int, float))
            or isinstance(limit, bool)
            or not 0 < limit <= MAX_CURRENT_A
        ):
            raise ValueError(
                f"{name}.current_limit_A: the motor current limit in A, "
                f"0 < x <= {MAX_CURRENT_A}"
            )
        self.current_limit_A = float(limit)
        self.stale_ms = positive(cfg.get("stale_ms", 100), f"{name}.stale_ms")

    def device_ids(self) -> tuple[str, ...]:
        return (self.port,)

    def open_bus(self, mock: bool) -> JointBus:
        if mock:
            bus = MockBus(dimension=len(JOINTS))
            bus.values = list(REST)
            return bus
        from ...drivers.pika_gripper import PikaGripperBus

        return PikaGripperBus(self.port, self.current_limit_A, stale_ms=self.stale_ms)
