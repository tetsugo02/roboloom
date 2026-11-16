# Setup

`roboloom.setup` runs the measurement and setup steps (EEPROM, zeros, travel, gravity, poses, bench tests) from Python. Usage examples come first, followed by the descriptions generated from the docstrings.

## Usage { #usage }

- The measurement functions return results as dataclasses and report failures as exceptions.
  - `ConfigError`: configuration error.
  - `SetupError`: measurement preconditions not met, or insufficient accuracy.
  - `HardwareError`: device state does not match, e.g. torque is enabled.
  - `Cancelled`: confirmation was declined. Nothing has been written.
- Steps that need human action query an `Operator`.
  - Supporting the arm, placing a pose, pressing Enter, etc.
  - The CLI passes a `TerminalOperator`.
  - In scripts and tests, you can pass a `ScriptedOperator` with a list of answers.
- Functions that take a configuration accept a path, a robot name, or a loaded `RobotConfig`. To choose options or the mode, load it with `load_config(..., options=..., mock=...)` and pass that.
- `plan_commission`, `watchdog_test`, and `gravity_check` refuse a mock configuration.

The command for each step is in [CLI](../cli.md#commands).

```python
from roboloom import setup
from roboloom.operator import TerminalOperator

op = TerminalOperator()
from roboloom import load_config

gravity = load_config("rakuda2", options=["gravity"])
plan = setup.plan_commission(gravity, "leader")
for line in plan.lines():
    print(line)
setup.apply_commission(plan, op)  # write after confirmation

fit = setup.identify_gravity(
    ".roboloom/rakuda2/calibration/leader_right.yaml",
    ".roboloom/rakuda2/calibration/gravity_right.yaml",
    op,
    collect=True,
)
for joint in fit.joints:
    print(joint.joint, f"{joint.explained:.0%}")
```

```python
# tune gravity compensation without the screen (e.g. automation that tries values in turn)
tuning = setup.open_tuning(gravity, "leader", "right_arm")
try:
    tuning.start()
    tuning.key("]")  # gain +0.1 for the selected joint
    for _ in range(120):
        tuning.step()
        time.sleep(tuning.period_s)
    print([(r.joint, r.gain, r.sent_mA) for r in tuning.rows()])
finally:
    tuning.close()
```

## EEPROM { #commission }

::: roboloom.setup.plan_commission
    options:
      heading_level: 3

::: roboloom.setup.apply_commission
    options:
      heading_level: 3

::: roboloom.setup.CommissionPlan
    options:
      heading_level: 3

## Zeros and travel { #calibration }

::: roboloom.setup.calibrate_joints
    options:
      heading_level: 3

::: roboloom.setup.Calibration
    options:
      heading_level: 3

::: roboloom.setup.measure_travel
    options:
      heading_level: 3

::: roboloom.setup.Travel
    options:
      heading_level: 3

## Gravity { #gravity }

::: roboloom.setup.identify_gravity
    options:
      heading_level: 3

::: roboloom.setup.collect_holding_currents
    options:
      heading_level: 3

::: roboloom.setup.fit_gravity
    options:
      heading_level: 3

::: roboloom.setup.GravityFit
    options:
      heading_level: 3

::: roboloom.setup.gravity_check
    options:
      heading_level: 3

::: roboloom.setup.release_trial
    options:
      heading_level: 3

::: roboloom.setup.GravityCheck
    options:
      heading_level: 3

::: roboloom.setup.open_tuning
    options:
      heading_level: 3

::: roboloom.setup.TuningSession
    options:
      heading_level: 3

## Poses { #poses }

::: roboloom.setup.capture_pose
    options:
      heading_level: 3

## Bench tests { #bench-tests }

::: roboloom.setup.check_hold
    options:
      heading_level: 3

::: roboloom.setup.hold_trial
    options:
      heading_level: 3

::: roboloom.setup.HoldResult
    options:
      heading_level: 3

::: roboloom.setup.watchdog_test
    options:
      heading_level: 3

::: roboloom.setup.watchdog_trial
    options:
      heading_level: 3

::: roboloom.setup.WatchdogResult
    options:
      heading_level: 3

## Operator { #operator }

::: roboloom.operator.Operator
    options:
      heading_level: 3

::: roboloom.operator.TerminalOperator
    options:
      heading_level: 3

::: roboloom.operator.ScriptedOperator
    options:
      heading_level: 3
