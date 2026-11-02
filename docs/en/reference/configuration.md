# Configuration

## Specifying the configuration

`roboloom init rakuda2` creates configuration, node, and calibration YAML in `.roboloom/rakuda2/`. It does not overwrite an existing directory. Each robot has one configuration (`config.yaml`); combinations of features are chosen with launch options. The robot name `rakuda2` refers to `.roboloom/rakuda2/config.yaml`. When `.roboloom/` holds a single robot it can be omitted; you can also specify a file path.

## Configuration YAML

```yaml
repo_id: local/rakuda2
output: datasets/rakuda2
dataset_fps: 15
inputs:
  leader: nodes/leader.yaml
controllers:
  controller: nodes/controller.yaml
followers:
  follower: nodes/follower.yaml
sensors:
  camera: nodes/camera.yaml
recorder: nodes/recorder.yaml
session: nodes/session.yaml
options:
  # see the next section
```

`mode` is optional and defaults to `hardware`; `mode: mock` is also valid. The CLI's `--mock` and the Python API's `mock=` take precedence over the YAML's `mode`.

Node YAML paths and `output` are relative to the configuration file's directory. With no option enabled, the output location above is `.roboloom/rakuda2/datasets/rakuda2`.

The only top-level keys are `repo_id`, `output`, `dataset_fps`, `mode`, the roles (`inputs`, `controllers`, `followers`, `sensors`, `estimators`), `recorder`, `session` and `options`; any other key is refused at load. The robot's name is the configuration's directory name (`rakuda2` for `.roboloom/rakuda2/`) and is also the dataset's `robot_type`.

`followers` lists the devices that move on command (arms, grippers, ...). One configuration may hold several followers. Each follower needs exactly one controller that drives it.

Node names are used as dora IDs and as dataset feature names. Use letters, digits, `-` and `_` only. `recorder`, `session`, `action` and `tick`, names starting with `action_` and names ending in `_status` are used by the dataflow and cannot be node names.

Each node's `type` selects the implementation. `SET_...` are robot-specific unset values; execution is refused if any remain in a referenced configuration. `validate` checks the consistency of the configuration and dataflow without opening devices. It does not check that EEPROM matches the hardware, image capture, or stopping behavior.

## Launch options

`options:` names the features chosen at launch (gravity compensation, extra sensors, and so on). Each option replaces, adds, or removes node files. The node files under `nodes/` stay split by feature; an option only chooses which of them are used.

| Key | Meaning |
| --- | --- |
| `help` | Description shown in the launcher |
| `default` | `true` enables it when nothing is specified (default `false`) |
| `requires` | List of options enabled together with it |
| `conflicts` | List of options that cannot be used at the same time |
| `set` | Maps `<role>.<node>` (role one of `inputs`, `controllers`, `followers`, `sensors`, `estimators`) to a node file; `null` removes that node |
| `dataset` | Short name appended to the dataset name while the option is enabled |

The rules are:

- Enabling an option also enables the options in its `requires` and disables those in `conflicts`. Disabling one also disables the options that require it.
- Two enabled options setting the same node to different files is an error, unless one has the other in its `requires`; then the requiring (dependent) one wins. In the template, `bilateral`'s leader replaces `gravity`'s.
- Unknown option names are an error.
- The `dataset` names of the enabled options are appended with `-`, in declaration order, to `repo_id` and `output`, so episodes of different shapes do not mix in one dataset.
- Loading is refused when an option without `dataset` changes the recorded features.

The options of the template (`src/roboloom/robots/rakuda2/template/config.yaml`):

```yaml
options:
  digit:
    help: record the left/right DIGIT tactile sensors
    set:
      sensors.digit_left: nodes/digit_left.yaml
      sensors.digit_right: nodes/digit_right.yaml
    dataset: digit
  gravity:
    help: gravity-compensated leader arms (after the measurement steps of README.md)
    set:
      inputs.leader: nodes/leader_gravity.yaml
  bilateral:
    help: force feedback from the follower to the leader (NOT verified on hardware)
    requires: [gravity]
    set:
      inputs.leader: nodes/leader_bilateral.yaml
      controllers.controller: nodes/controller_bilateral.yaml
      followers.follower: nodes/follower_bilateral.yaml
      estimators.effort: nodes/effort.yaml
    dataset: bilateral
  policy:
    help: a learned policy drives the follower (`roboloom infer` turns this on)
    requires: [digit]  # nodes/policy.yaml observes the DIGIT sensors
    conflicts: [gravity]
    set:
      inputs.leader: null
      controllers.controller: null
      controllers.policy: nodes/policy.yaml
    dataset: eval
```

| Enabled options | `repo_id` |
| --- | --- |
| none | `local/rakuda2` |
| `digit` | `local/rakuda2-digit` |
| `digit`, `policy` | `local/rakuda2-digit-eval` |
| `gravity`, `bilateral` | `local/rakuda2-bilateral` |

`output` gets the same name (for example `datasets/rakuda2-digit`). Check which options are enabled and what the dataset is called with, for example, `roboloom validate --with digit`. See [CLI](cli.md) for choosing options and [Rakuda2](../robots/rakuda2.md) for the combinations and limitations on Rakuda2.

## Joint locking and compensation

The leader node's `control` selects a law per joint group, such as `free` (torque off), `position` (holds the torque-enable pose on a leader), `spring`, or `gravity_comp`. Specify every joint exactly once. The `joint` controller's `couplings` (default `[]`) is a list of `{joint, source, scale, reference}` (optionally `lead_ms`) entries that add another follower joint's measured displacement from `reference` to a target. These settings are independent. See the [Leader configuration examples](../controllers/leader.md).

## Force feedback (not verified on hardware)

!!! warning "Not verified on hardware"
    This is the path that returns the external force on the follower to the leader. Only the mock tests pass. See [Bilateral control design](../contribution/bilateral.md) for the design and the remaining stages.

Add `estimators` to the configuration and reference the estimator from the controller's `feedback`. In the template, the option `bilateral` adds `estimators.effort` and replaces the leader, controller, and follower with the node files for feedback. You do not write edges; the path below follows from each node's references.

```text
leader ──sample──► controller ──command──► follower ──state──► estimator
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
| `type` | `none` (never estimates; for checking the path) or `model_residual` |
| `models` | Gravity models for `model_residual` (one per arm). Their output joints together must equal `joints` exactly |
| `follower` | Name of the follower node whose state it reads |
| `joints` | Follower joints to estimate |
| `smoothing_alpha` | Exponential moving average factor (greater than 0, at most 1; default 1 = no smoothing) |
| `contact_on` / `contact_off` | Contact detection with hysteresis on the L1 norm of the residual. `contact_off` ≤ `contact_on`. Both default to 0, which means always in contact |
| `record` | `true` records the estimate in the dataset (default `false`). `recorder.max_age_ms` needs an entry for this estimator |

An estimator computes a per-joint residual (measured − predicted for free motion) from the effort signal the follower declares (Rakuda2: `currents_mA`, in mA). External force acts opposite to the residual.

`model_residual` is `residual = measured current − g(q)`, where `g(q)` is a gravity model identified on the follower; no training is needed. Friction, inertia and position tracking error stay in the residual, so it is not 0 while the arm moves freely. Watch `residual_l1` (the value the contact thresholds compare) in the estimator node's status while moving the follower freely and while pushing it, and put `contact_on` between the two. Build the gravity model with the same `identify-gravity` as the leader, from a follower calibration (`calibration/follower_<side>.yaml`).

```bash
uv run roboloom calibrate-joints .roboloom/rakuda2/calibration/follower_right.yaml
uv run roboloom identify-gravity .roboloom/rakuda2/calibration/follower_right.yaml \
    --out .roboloom/rakuda2/calibration/effort_gravity_right.yaml --collect
```

Because the follower arm mixes XM540 and XM430 motors, each joint is identified separately (`shared_parameters: false`), which needs more poses than the leader. Stop the follower node during identification.

The controller's `feedback`:

```yaml
feedback:
  estimator: effort
  deadline_ms: 100
  unit: mA/mA          # leader unit / estimator unit
  gain:                # follower joint name -> gain (0 or more)
    r_arm_el_yaw: 0.1
```

The current sent to the leader is `−gain × sign × residual` (`sign` is the sign of the `joints` mapping). The controller asks for the feedback to be applied (gate) only while the estimate is valid and in contact, the follower is `ACTIVE`, and the controller is `following`. The deadline is `deadline_ms` after the follower state the estimate came from. An estimate that arrives after that deadline is not sent, and the controller status shows the reason in `feedback_error`. The leader accepts it only on joints of current-mode groups (`gravity_comp`, `impedance`) that have `feedback:`. Position-mode groups and `free` cannot have it.

```yaml
- group: right_arm
  law: gravity_comp
  # ...
  feedback:
    max_mA: 20     # limit of the feedback alone (a per-joint list also works)
    ramp_s: 0.3    # time the gate takes to open or close (default 0.3)
    kd: 0.0        # damping added while the feedback is on, mA/(count/s) (default 0)
```

Every tick, the leader adds the following to the law's output, then clips the sum at `max_current_mA`.

```text
gate × (clip(received current, ±max_mA) − kd × velocity)
```

`gate` is a value from 0 to 1. It moves toward 1 over `ramp_s` while the controller asks for the feedback and the message is within its deadline (`deadline_ms`), and toward 0 otherwise. It never jumps. Estop, release, quit, going limp, and a detected runaway set it to 0 at once. Joints that take feedback are checked for runaway (`max_velocity`, out of range) even with gravity gain 0. `tune-gravity` and `gravity-check` run without feedback. On hardware, roboloom checks `max_mA` ≤ `max_current_mA`. The leader status shows `gate`, the feedback current per joint (`mA`) and the number received under `feedback`; the trace (`<leader name>_trace.npz`) keeps it as `feedback_mA`.

The feedback current stays inside the same `max_current_mA` and EEPROM Current Limit as gravity compensation, so near the limit it is clipped. Raising the Current Limit also raises the force left on the arm if the host stops (an XC330 does not stop its current when the Bus Watchdog fires).

An estimator with `record: true` records `observation.effort_ext` (external effort = −residual, in the estimator's unit), `observation.effort_ext.valid` and `observation.contact`. Frames without an estimate hold 0. Several recorded estimators are joined in configuration order; the `names` of `observation.effort_ext` are `<follower>.<joint>`, those of the other two the estimator names. Estimators with different units cannot share one vector and are refused at load.

At load time, roboloom checks that references exist, that the estimator and the controller use the same follower, the units, and that the leader accepts the feedback. Mismatched settings are refused before start. Joints that are targets of `couplings` also receive feedback through the `joints` mapping. The Python API (`InProcessSession`) does not handle estimators.

## Control rate

`control_hz` in `follower.yaml` and the leader's `poll_hz` are the rates at which those nodes read and write their bus. The work of one period (reading the state, computing control laws, writing goals) must fit in the period. A higher rate makes the leader's current control and the follower's tracking finer.

Choose the rate as follows.

1. Run `roboloom probe <port>` on each port. It shows the state read time and a rough rate limit (reading and writing take 70% of the period). `probe` never writes.
2. Set `control_hz` and `poll_hz` and check on the `run` screen. `work … ms (max …)` on the follower and leader rows is the time one period's work takes. If the maximum stays around 70% of the period or less and `tick` matches the period, the node keeps up.
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

With several followers, the following features are one vector joining all followers in configuration order. Their `names` tell which follower each entry belongs to, as `<follower>.<joint>` (for example `follower.r_arm_sh_pitch1`).

| Feature | Content |
| --- | --- |
| `observation.state` | Each follower's joint positions |
| `observation.effort` | The effort of the followers with `record_effort: true`; followers with different units cannot be mixed |
| `action` | The first command each follower sent in the row's interval, in the order of `observation.state` |
| `action.valid` | 1 in rows where every follower sent a command |
| `action.clamped` | 1 in rows where any follower limited its command |
| `action.meta.<follower>.valid` / `clamped` / `seq` / `sent_ns` | Each follower's own: command present, limited, command number, send time |

A follower that sent no command fills its part with the target it held (its state's `target`); filling with zeros would teach a policy a jump to 0. LeRobot training does not read `action.valid`, so select rows by `action.valid` when you only want valid ones. A row is final once every follower's commands have passed its interval, or after `grace_ms` (default 500 ms).

You can append further episodes to the same dataset. On resume, FPS and feature compatibility are checked. Give an option that changes the recorded features a `dataset`, so it gets a dataset of its own (see "Launch options").

Thresholds for quality warnings can be set with `max_missing_rate`, `min_action_valid_rate`, and `max_interval_ms` in `recorder.quality`. Check the metrics and warnings in the save result. `control_interval_ms` and `action_missing_rate` (the share of rows without a command) are per follower, and warnings name the follower.

## Managing logs and configuration

Logs are placed in `logs/<dataset name>-<time>/` next to the configuration file (for example `logs/rakuda2-digit-20261102-101500/`); the dataset name tells which options were enabled. When the node ends, the leader's current control is written to `<leader name>_trace.npz`, and each follower's per-tick state (positions, velocities, currents, target, mode) to `<follower name>_trace.npz`. Manage YAML configuration, gravity models, ranges of motion, tuning values, and saved initial poses (`poses/<follower>/`) with Git; raw data `*.npz`, logs, datasets, and FIFOs (`config.fifo`) are excluded by the generated `.roboloom/.gitignore`.

API details are in [Python API](python-api.md), and commands are in [CLI](cli.md).
