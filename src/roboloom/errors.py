"""Errors a user can act on. The CLI prints their message without a traceback."""

from __future__ import annotations


class RoboloomError(Exception):
    """Base of every error caused by configuration, setup or the robot, not by a bug."""


class ConfigError(RoboloomError, ValueError):
    """An experiment or calibration file is invalid or still has SET_ values."""


class SetupError(RoboloomError):
    """A measurement or fit cannot proceed, or its result is not good enough to save."""


class HardwareError(RoboloomError, RuntimeError):
    """The devices are not in the state a command needs (torque on, wrong mode, ...)."""


class Cancelled(RoboloomError):
    """The operator declined a confirmation; nothing was written."""
