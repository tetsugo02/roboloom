"""A follower of your own, next to the configuration that uses it.

`nodes/follower.yaml` names it by reference (`type: my_arm:MyArm`); every node process
imports it from this directory. Start from this file for a robot roboloom does not
ship: give it your joints and unit, and return your bus from `open_bus`.
"""

from __future__ import annotations

from roboloom.core.traits import SafetyTraits
from roboloom.drivers.mock import MockBus
from roboloom.robots.base import FOLLOWER_KEYS, Follower, JointBus

JOINTS = ("shoulder", "elbow")


class MyArm(Follower):
    model = "my_arm"
    # the keys of its YAML this class reads; any other key is refused on loading
    keys = (*FOLLOWER_KEYS, "address")
    # what the joints do without torque, and when nothing commands them any more
    safety_traits = SafetyTraits(torque_off="falls", unattended="holds")

    def __init__(self, name: str, cfg: dict):
        super().__init__(name, cfg, JOINTS, "rad")
        self.address = str(cfg.get("address"))

    def device_ids(self) -> tuple[str, ...]:
        return (self.address,)  # no two nodes may open the same device

    def open_bus(self, mock: bool) -> JointBus:
        """The bus the follower node owns: `read_positions`, `write_positions`,
        `enable_torque`, `close` (roboloom.drivers.base.JointBus)."""
        if mock:
            return MockBus(initial=0.0, dimension=len(JOINTS))
        raise NotImplementedError(f"{self.name}: connect to {self.address} here")
