"""Follower robots selected by `robots.<name>.type`. Register new models here.

Each robot model has its own subpackage (e.g. `rakuda2`) holding its follower and
its joint/motor description (`spec`). Its leader arm, if any, is an input in
`roboloom.inputs.<model>` and reuses that `spec`.
"""

from ..core.registry import Registry
from .base import Robot

ROBOTS: Registry[Robot] = Registry("robot", {
    "rakuda2_follower": "roboloom.robots.rakuda2.follower:RakudaFollower",
})
