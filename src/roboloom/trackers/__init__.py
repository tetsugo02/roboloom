"""Tracking systems selected by `trackers.<name>.type`. Register new systems here.

A tracking system (e.g. Lighthouse base stations read by libsurvive) runs in one node
and publishes the poses of every tracked object it sees, keyed by the object's serial
number. Inputs that hold a tracked object (e.g. `pika_sense`) name the system and their
object's serial, and read their pose from that node; several inputs share one system,
so the hardware (one USB receiver, one calibrated world frame) is opened once.
"""

from ..core.registry import Registry
from .base import Tracker

TRACKERS: Registry[Tracker] = Registry(
    "tracker",
    {
        "libsurvive": "roboloom.trackers.libsurvive:Libsurvive",
    },
)
