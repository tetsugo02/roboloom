"""Follower effort estimators selected by `estimators.<name>.type`. Register new ones here.

Estimators that work for any robot live in this package; one written for a single robot
model lives in `roboloom.robots.<model>` and is registered here too.
"""

from ..core.registry import Registry
from .base import Estimator

ESTIMATORS: Registry[Estimator] = Registry(
    "estimator",
    {
        "none": "roboloom.estimators.base:NoEstimator",
    },
)
