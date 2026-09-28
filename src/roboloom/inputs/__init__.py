"""Operator inputs selected by `inputs.<name>.type`. Register new devices here.

Devices get one subpackage each (e.g. `rakuda2` for its leader arm); a leader
imports its robot's shared description from `roboloom.robots.<model>.spec`.
Each input class fixes what its samples mean (its Envelope `kind`): `JointInput`
publishes joint intents. Pose (VR) and twist (SpaceMouse) inputs add their own
base classes next to it, and controllers state which of them they accept.
"""

from ..core.registry import Registry
from .base import InputDevice

INPUTS: Registry[InputDevice] = Registry("input", {
    "rakuda2_leader": "roboloom.inputs.rakuda2.leader:RakudaLeader",
})
