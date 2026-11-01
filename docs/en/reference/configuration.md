# Configuration

## Specifying an experiment

`roboloom init rakuda2` creates experiment, node, and calibration YAML in `.roboloom/rakuda2/`. It does not overwrite an existing directory. The experiment name `rakuda2` refers to `experiment.yaml`, and `rakuda2/experiment_gravity` refers to `experiment_gravity.yaml`. You can also specify a file path.

## Experiment YAML

```yaml
robot_id: rakuda2
repo_id: local/rakuda2
output: datasets/rakuda2
mode: hardware
dataset_fps: 15
inputs:
  leader: nodes/leader.yaml
controllers:
  controller: nodes/controller.yaml
robots:
  robot: nodes/robot.yaml
sensors:
  camera: nodes/camera.yaml
  digit_left: nodes/digit_left.yaml
  digit_right: nodes/digit_right.yaml
recorder: nodes/recorder.yaml
session: nodes/session.yaml
```

Node YAML paths and `output` are relative to the experiment file's directory. The output location above is `.roboloom/rakuda2/datasets/rakuda2`. Node names are used as dora IDs and as dataset feature names. Currently, each experiment has one robot and one corresponding controller.

Each node's `type` selects the implementation. `SET_...` are robot-specific unset values; execution is refused if any remain in a referenced configuration. `validate` checks the consistency of the configuration and dataflow without opening devices. It does not check that EEPROM matches the hardware, image capture, or stopping behavior.

## Joint locking and compensation

The leader node's `control` selects a law per joint group, such as `free` (torque off), `position` (holds the torque-enable pose on a leader), `spring`, or `gravity_comp`. Specify every joint exactly once. The `joint` controller's `couplings` (default `[]`) is a list of `{joint, source, scale, reference}` (optionally `lead_ms`) entries that add another follower joint's measured displacement from `reference` to a target. These settings are independent. See the [Leader configuration examples](../controllers/leader.md).

## Force feedback (not verified on hardware)

!!! warning "Not verified on hardware"
    This is the path that returns the external force on the follower to the leader. Only the mock tests pass. The only estimator so far is `none` (never estimates), so the current returned to the leader is 0. See [Bilateral control design](../contribution/bilateral.md) for the design and the remaining stages.

Add `estimators` to the experiment YAML and reference the estimator from the controller's `feedback`. You do not write edges; the path below follows from each node's references.

```text
leader ──sample──► controller ──command──► robot ──state──► estimator
  ▲                    │  ▲                                  │
  └──── feedback ──────┘  └────────────── estimate ──────────┘
```

```yaml
estimators:
  effort: nodes/effort.yaml
```

Estimator (`nodes/effort.yaml`):

| Key | Meaning |
| --- | --- |
| `type` | `none` |
| `robot` | Name of the robot node whose state it reads |
| `joints` | Follower joints to estimate |
| `smoothing_alpha` | Exponential moving average factor (greater than 0, at most 1; default 1 = no smoothing) |
| `contact_on` / `contact_off` | Contact detection with hysteresis on the L1 norm of the residual. `contact_off` ≤ `contact_on`. Both default to 0, which means always in contact |

An estimator computes a per-joint residual (measured − predicted for free motion) from the effort signal the robot declares (Rakuda2: `currents_mA`, in mA). External force acts opposite to the residual.

The controller's `feedback`:

```yaml
feedback:
  estimator: effort
  deadline_ms: 100
  unit: mA/mA          # leader unit / estimator unit
  gain:                # follower joint name -> gain (0 or more)
    r_arm_el_yaw: 0.1
```

The current sent to the leader is `−gain × sign × residual` (`sign` is the sign of the `joints` mapping). The controller asks for the feedback to be applied (gate) only while the estimate is valid and in contact, the follower is `ACTIVE`, and the controller is `following`. The leader accepts it only on joints of current-mode groups (`gravity_comp`, `impedance`) that have `feedback:`. Position-mode groups and `free` cannot have it.

```yaml
- group: right_arm
  law: gravity_comp
  # ...
  feedback: {}
```

At load time, roboloom checks that references exist, that the estimator and the controller use the same robot, the units, and that the leader accepts the feedback. Mismatched settings are refused before start. Joints that are targets of `couplings` also receive feedback through the `joints` mapping. The Python API (`Experiment`) does not handle estimators.

## Control rate

`control_hz` in `robot.yaml` and the leader's `poll_hz` are the rates at which those nodes read and write their bus. The work of one period (reading the state, computing control laws, writing goals) must fit in the period. A higher rate makes the leader's current control and the follower's tracking finer.

Choose the rate as follows.

1. Run `roboloom probe <port>` on each port. It shows the state read time and a rough rate limit (reading and writing take 70% of the period). `probe` never writes.
2. Set `control_hz` and `poll_hz` and check on the `run` screen. `work … ms (max …)` on the robot and leader rows is the time one period's work takes. If the maximum stays around 70% of the period or less and `tick` matches the period, the node keeps up.
3. If not, lower the rate.

A Dynamixel bus switches to Fast Sync Read (one reply packet for all motors) at startup when every motor's firmware is v45 or later. Otherwise it keeps the plain read and prints why at startup.

Measured on Rakuda2 (2026-10-27, 17 motors, 1 Mbps, FTDI latency timer 1 ms):

| Read | Time |
| --- | --- |
| State (position, velocity, current), plain Sync Read | 5.0 ms |
| State, Fast Sync Read | 4.0 ms |
| Bus Watchdog (one register), Fast Sync Read | 2.0 ms |

The wait the Dynamixel SDK does before every send (`flush`) is also skipped. It alone took about 1.9 ms of each leader period. Packets stay in order.

To save time, these reads are not done every period:

- Leader Bus Watchdog: read when goal writes have paused for half of `bus_watchdog_ms` or more, and every 100 ms. If it fired, the current-controlled joints go limp as before.
- Follower `health`: every `every_ticks` periods, one of Bus Watchdog, hardware error and temperature is read, in turn. Each value is refreshed every three times `every_ticks` periods.

The templates use 120 Hz, verified on Rakuda2 hardware (2026-10-27, 121 s):

| | Work per period (mean, max) | Period interval |
| --- | --- | --- |
| Leader (gravity compensation) | 4.3 ms, 6.8 ms | median 8.0 ms, p99.9 10.1 ms |
| Follower | 3.7 ms, 6.1 ms | 7.7 ms |

There was one stall of about 120 ms during the run. Stalls of the same size also happen at 60 Hz and are unrelated to the rate. 120 Hz assumes an FTDI latency timer of 1 ms and Fast Sync Read. If `probe` shows a lower limit, or the maximum `work` exceeds 70% of the period, lower `control_hz` and `poll_hz` (e.g. to 60).

## Recording and resuming

With the `record` extra, data is saved as LeRobotDataset 0.6.1. Monotonic-clock timestamps for capture, availability, reception, and command sending are kept distinct for alignment, and missing data is represented by zero values and validity flags. `task` is recorded in each frame.

You can append further episodes to the same dataset. On resume, FPS and feature compatibility are checked. If you change the sensor configuration, use a separate `repo_id` / `output`.

Thresholds for quality warnings can be set with `max_missing_rate`, `min_action_valid_rate`, and `max_interval_ms` in `recorder.quality`. Check the metrics and warnings in the save result.

## Managing logs and configuration

Logs are placed in `logs/<experiment name>-<time>/` next to the experiment file. Manage YAML configuration, gravity models, ranges of motion, tuning values, and saved initial poses (`poses/`) with Git; raw data `*.npz`, logs, datasets, and FIFOs are excluded by the generated `.roboloom/.gitignore`.

API details are in [Python API](python-api.md), and commands are in [CLI](cli.md).
