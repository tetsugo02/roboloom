# Setup and measurement: `roboloom.setup`

Functions return dataclasses and raise `ConfigError`, `SetupError`, `HardwareError` or
`Cancelled` (declined; nothing written). Human steps (support the arm, place a pose, press
Enter) go through an `Operator`:

```python
from roboloom.operator import TerminalOperator, ScriptedOperator

op = TerminalOperator()  # what the CLI uses
# ScriptedOperator(...) answers from a list, for scripts and tests
```

Functions taking a configuration accept a robot name, a path or a `RobotConfig`; to pick
options or mode, pass `load_config(..., options=..., mock=...)`. **All of these talk to
real hardware** (except `capture_pose` reading only); run them only when the user asks.
The Dynamixel-only steps refuse non-Dynamixel nodes; `plan_commission`, `watchdog_test`,
`check_hold`, `gravity_check` refuse a mock configuration. Never open the same bus while a
dataflow runs.

| Step | CLI | Python | Touches hardware |
| --- | --- | --- | --- |
| read a bus | `probe <port>` (`--device pika` / `pika_sense`; CAN name for PiPER) | `roboloom.probe.probe(port, ids, baudrate, device=...)` | reads only |
| align EEPROM | `commission [robot] <node>` | `plan = setup.plan_commission(cfg, node)`; `plan.lines()`; `setup.apply_commission(plan, op)` | writes EEPROM after confirmation, reads back |
| zero pose | `calibrate-joints <calibration>` | `setup.calibrate_joints(cal, op, joints=None)` | reads; torque must be off; writes local YAML |
| range of motion | `measure-travel <calibration> --out <path>` | `setup.measure_travel(cal, out, op)` | reads; torque off |
| gravity model | `identify-gravity <calibration> --out <path> --collect` | `setup.identify_gravity(cal, out, op, collect=True)` | **energizes** |
| check compensation | `gravity-check [robot] leader <group> --with gravity` | `setup.gravity_check(cfg, node, group, op)` | **energizes** |
| tune compensation | `tune-gravity [robot] leader <group> --with gravity` (TTY only) | `setup.open_tuning(cfg, node, group)` → `TuningSession` | **energizes** |
| watchdog bench test | `watchdog-test [robot] <node> <joint>` | `setup.watchdog_test(cfg, node, joint, op)` | **energizes** |
| unattended behaviour | `check-hold [robot] <follower> --tolerance <v>` | `setup.check_hold(cfg, follower, op, tolerance)` | **energizes**, writes `unattended:` after confirmation |
| save a home pose | `capture-pose [robot] [follower] <name>` | `setup.capture_pose(cfg, name, follower=None, force=False)` | reads only; writes `poses/<follower>/<name>.yaml` |

## Rakuda2 order (leader gravity compensation)

1. `probe` each U2D2 port; fill ports, IDs, `registers`, safe `limits` in node YAML.
2. `validate`; `commission follower`, `commission leader` (arms supported).
3. First collection path check with follower `torque: false`.
4. `calibrate-joints` (URDF zero pose) for `calibration/leader_<side>.yaml`; check
   `direction`, set `confirmed: true`.
5. `measure-travel ... --out calibration/travel_<side>.yaml`.
6. `identify-gravity ... --out calibration/gravity_<side>.yaml --collect`.
7. `--with gravity`: `tune-gravity` (gain, hold → `gravity_tuning_<side>.yaml`),
   optionally `gravity-check`.

Sent current = clip(ramp × (gain × g(q) + hold − kd × velocity) + range push-back). The
gravity model uses only URDF joint axes and holding currents, not CAD masses. On the lab
robot `g(q)` came out about half of the current actually needed (gear static friction), so
gain 1.0 under-compensated there – tune gain per joint with `tune-gravity`, don't assume.

```python
from roboloom import load_config, setup
from roboloom.operator import TerminalOperator

op = TerminalOperator()
gravity = load_config("rakuda2", options=["gravity"])
plan = setup.plan_commission(gravity, "leader")
print("\n".join(plan.lines()))
setup.apply_commission(plan, op)

fit = setup.identify_gravity(
    ".roboloom/rakuda2/calibration/leader_right.yaml",
    ".roboloom/rakuda2/calibration/gravity_right.yaml",
    op,
    collect=True,
)
for joint in fit.joints:
    print(joint.joint, f"{joint.explained:.0%}")
```

Tuning without the screen:

```python
import time

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
