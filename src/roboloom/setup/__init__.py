"""Setup and measurement steps for one robot, callable from Python and the CLI.

Each step returns its result as data and raises a `roboloom.errors` exception when it
cannot proceed. Steps that need the person at the robot take an `Operator`
(`TerminalOperator` in the CLI, `ScriptedOperator` in scripts and tests). Steps that
torque motors or write EEPROM also need `hardware=True`.
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
from .pose import capture_pose
from .watchdog import WatchdogResult, watchdog_test, watchdog_trial

__all__ = [
    "Calibration",
    "CommissionPlan",
    "GravityCheck",
    "GravityFit",
    "Travel",
    "TuningSession",
    "WatchdogResult",
    "apply_commission",
    "calibrate_joints",
    "capture_pose",
    "collect_holding_currents",
    "fit_gravity",
    "gravity_check",
    "identify_gravity",
    "measure_travel",
    "open_tuning",
    "plan_commission",
    "release_trial",
    "watchdog_test",
    "watchdog_trial",
]
