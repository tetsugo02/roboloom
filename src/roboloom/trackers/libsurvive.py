"""Lighthouse (Vive) tracking through libsurvive: one context for every tracker.

Keys: `type: libsurvive`, `args` (optional: extra libsurvive arguments, e.g.
`[--lighthouse-gen, "2"]`), `poll_hz` (optional). Objects are identified by their serial
number (`LHR-...`), which libsurvive learns once it has read the device's configuration;
names like `WM0` follow the enumeration order and may swap between runs.
"""

from __future__ import annotations

from ..core.checks import identity
from .base import MockTrackerReader, Tracker, TrackerReader


class Libsurvive(Tracker):
    keys = (*Tracker.keys, "args")
    world_frame = "libsurvive"  # the frame calibrated with `--force-calibrate`

    def __init__(self, name: str, cfg: dict):
        super().__init__(name, cfg)
        args = cfg.get("args", [])
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise ValueError(f"trackers.{name}.args: expected a list of strings")
        for arg in args:
            identity(arg, f"trackers.{name}.args")  # refuses SET_ placeholders
        self.args = list(args)

    def device_ids(self) -> tuple[str, ...]:
        # libsurvive claims every Lighthouse USB device it finds: one context per host
        return ("libsurvive",)

    def open(self, mock: bool) -> TrackerReader:
        if mock:
            return MockTrackerReader()
        from ..drivers.survive import SurviveSystem

        return SurviveSystem(self.args)
