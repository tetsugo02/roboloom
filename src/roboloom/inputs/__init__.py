"""Operator inputs selected by `inputs.<name>.type`. Register new devices here.

Devices get one subpackage each, named for the device, not for the role it plays in
an experiment (e.g. `rakuda_mini`, an arm used as a leader); a device built for one
robot imports that robot's shared description from `roboloom.robots.<model>.spec`.
Each input class fixes what its samples mean (its Envelope `kind`): `JointInput`
publishes joint intents. Pose (VR) and twist (SpaceMouse) inputs add their own
base classes next to it, and controllers state which of them they accept.
"""

from ..core.registry import Registry
from .base import InputDevice

INPUTS: Registry[InputDevice] = Registry(
    "input",
    {
        "rakuda_mini": "roboloom.inputs.rakuda_mini.arm:RakudaMini",
    },
)
