"""Setup and measurement steps for one robot, callable from Python and the CLI.

Each step returns its result as data and raises a `roboloom.errors` exception when it
cannot proceed. Steps that need the person at the robot take an `Operator`
(`TerminalOperator` in the CLI, `ScriptedOperator` in scripts and tests). Steps that
take a configuration accept a path, a robot name or a loaded `RobotConfig` (load it
with `load_config(..., options=..., mock=...)` to choose its options and mode).
"""

from ..control.tuning import TuningSession
from .calibration import Calibration, Travel, calibrate_joints, measure_travel
from .commission import CommissionPlan, apply_commission, plan_commission
from .gravity import (
    GravityCheck,
    GravityFit,
    collect_holding_currents,
    fit_gravity,
    gravity_check,
    identify_gravity,
    open_tuning,
    release_trial,
)
from .hold import HoldResult, check_hold, hold_trial
from .pose import capture_pose
from .watchdog import WatchdogResult, watchdog_test, watchdog_trial

__all__ = [
    "Calibration",
    "CommissionPlan",
    "GravityCheck",
    "GravityFit",
    "HoldResult",
    "Travel",
    "TuningSession",
    "WatchdogResult",
    "apply_commission",
    "calibrate_joints",
    "capture_pose",
    "check_hold",
    "collect_holding_currents",
    "fit_gravity",
    "gravity_check",
    "hold_trial",
    "identify_gravity",
    "measure_travel",
    "open_tuning",
    "plan_commission",
    "release_trial",
    "watchdog_test",
    "watchdog_trial",
]
