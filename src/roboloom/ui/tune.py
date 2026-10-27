"""Textual gravity tuning entry point; the backend owns the device lifecycle."""

from collections.abc import Callable

from ..control.tuning import TuningSession
from ..errors import HardwareError
from .app import run_backend
from .tuning_backend import TuningBackend


def run(open_session: Callable[[], TuningSession], title: str) -> str:
    backend = TuningBackend(open_session, title)
    outcome = run_backend(backend)
    if outcome == "failed":
        raise HardwareError(backend.failure)
    return outcome
