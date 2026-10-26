"""Robot data collection and policy inference on dora-rs, saved as LeRobotDataset.

- `Session`: run an experiment's dataflow and direct it (episodes, tasks, inference).
- `roboloom.setup`: setup and measurement steps (commission, gravity, travel, ...).
- `Experiment`: everything in this process, for tests and simple robots.
"""

from .api import Experiment
from .config import load_experiment, resolve_experiment
from .core.source import Sample
from .errors import ConfigError, HardwareError, RoboloomError, SetupError
from .policy import Policy
from .project import init_project
from .runtime.session import EpisodeInfo, EpisodeResult, Session, SessionError

__all__ = [
    "ConfigError",
    "EpisodeInfo",
    "EpisodeResult",
    "Experiment",
    "HardwareError",
    "Policy",
    "RoboloomError",
    "Sample",
    "Session",
    "SessionError",
    "SetupError",
    "init_project",
    "load_experiment",
    "resolve_experiment",
]
