"""Input -> robot conversions selected by `controllers.<name>.type`. Register new ones here.

A controller class is written for one family of inputs and checks at config load
that its input and robot fit, so unsupported pairs fail before any device opens.
"""

from ..core.registry import Registry
from .base import Controller

CONTROLLERS: Registry[Controller] = Registry("controller", {
    "joint": "roboloom.controllers.joint:JointController",
})
