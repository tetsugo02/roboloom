# Controllers (controllers)

Keys of the node YAML under `controllers:`. A controller turns an input (or a policy) into follower commands. For how to use each one, see [Controllers](../../controllers/index.md).

## Keys of every controller { #common }

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `type` | text | required | — | `joint`, `parts`, `pose_ik`, `policy` or `module:Class` |
| `followers` | list of text | required | — | Names of the followers it drives ([Followers and controllers](#followers)) |
| `command_deadline_ms` | number | required | ms | How long a command is valid; after it the follower holds |
| `follower_timeout_ms` | number | `150` | ms | When a follower's state gets older than this, commands to all its followers stop |

### Followers and controllers { #followers }

Each controller lists the followers it drives under `followers:`. Each follower is driven by exactly one controller.

| Controller | Followers it drives |
| --- | --- |
| `joint` | Exactly one (maps the leader's joints onto one follower's joints) |
| `pose_ik` | One arm and optionally one gripper (a hand-held device's pose onto the arm's joints through IK) |
| `parts` | Exactly one, through inner controllers that each drive some of its joints |
| `policy` | Every follower, in configuration order. The recorded `action` and `observation.state` join all followers, so the policy's output has the same layout; it is split in that order and sent to each follower |

A controller of several followers sends nothing until every one of them has reported its state. When any of its followers latches `FAULT` or `ESTOP`, or its state gets older than `follower_timeout_ms`, the controller stops commanding all of them. A follower without commands keeps holding its target. The controller sends no further command until it has re-aligned. A `policy` controller stops running the policy for the current episode when a follower's state gets stale. The controller's row on the screen shows why it stopped (`stopped_by`) and the followers it waits for (`waiting_state`).

## joint { #joint }

Maps a leader's joints onto one follower's joints. Its input is a joint input (such as `rakuda_mini`). It first aligns (waits until leader and follower are within `alignment_tolerance`), then follows with a speed limit.

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `input` | text | required | — | Name of the input node |
| `alignment_tolerance` | number | required | follower unit | Leader-follower difference allowed before following starts and at every episode start |
| `max_speed` | number | required | follower unit/s | How far a teleoperation target may move per period ([Units](index.md#units)) |
| `input_timeout_ms` | number | required | ms | Commands stop when the input gets older than this |
| `unit` | text | — | — | If written, the input's and the follower's unit; with a `scale` on every joint the input's unit may differ |
| `joints` | list | joint to the joint of the same name | — | The joint map ([below](#joint-map)) |
| `couplings` | list | `[]` | — | Adds another joint's displacement to a target ([below](#couplings)) |
| `home` | mapping | — | — | Saved pose ([home](control.md#home)) |
| `feedback` | mapping | — | — | Force feedback ([below](#feedback)) <span class="status status--mock">Mock only</span> |

### Joint map (joints) { #joint-map }

An input with the follower's joint names and unit (Rakuda-mini and Rakuda2) needs no map: each follower joint follows the input joint of the same name. For other names, directions or offsets, write one entry per follower joint, in the follower's order. `follower = sign × scale × leader + offset`.

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `leader` | text | required | — | The input's joint |
| `follower` | text | required | — | The follower's joint (in the follower's order) |
| `sign` | `1` or `-1` | required | — | Direction |
| `offset` | number | required | follower unit | Offset |
| `scale` | positive number | `1.0` | follower unit / input unit | Gear ratio or unit conversion; not together with `feedback` |

### Joint compensation (couplings) { #couplings }

`couplings` adds another follower joint's measured displacement from `reference` to a mapped target (before the speed limit), for example to keep the head camera's direction while the torso turns. It is independent of the leader's `control` (locked joints and so on). See the [Leader configuration examples](../../controllers/leader.md).

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `joint` | text | required | — | Follower joint whose target gets the addition; each at most once |
| `source` | text | required | — | Follower joint whose displacement is measured (not `joint`) |
| `scale` | number | required | — | Factor applied to the displacement |
| `reference` | number | required | follower unit | `source` position at which nothing is added |
| `lead_ms` | number | `0` | ms | Looks ahead along `source`'s velocity by this long (for the lag of `joint`'s position loop); 0 to 500 |

```yaml
# nodes/controller.yaml
type: joint
input: leader
followers: [follower]
alignment_tolerance: 300
max_speed: 2048
command_deadline_ms: 100
input_timeout_ms: 150
couplings:
- {joint: head_yaw, source: torso_yaw, scale: -1.0, reference: 2048, lead_ms: 70}
```

## parts <span class="status status--mock">Mock only</span> { #parts }

With a `type: parts` controller, a follower with many joints, such as Rakuda2 (17 joints on one bus), can be driven by several inputs, each with its own joints: a hand-held device per arm, or a leader for one arm only. The follower still gets one command from one controller, so its safety checks, the recorded `action` and the dataset do not change. This has been checked with mock devices only.

A follower names its parts ([the follower's `parts`](followers.md#parts)).

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `parts` | list of paths | required | — | Files of the inner controllers, relative to this file's directory; each is named after its file (without extension) |
| `input_timeout_ms` | number | `150` | ms | Commands stop when an input gets older than this |

```yaml
# nodes/controller.yaml
type: parts
followers: [follower]
command_deadline_ms: 100
parts: [right_hand.yaml, left_hand.yaml]   # controller files next to this one
```

```yaml
# nodes/right_hand.yaml: any controller type; its followers are parts, <follower>.<part>
type: joint
input: leader
followers: [follower.right_arm]
alignment_tolerance: 300
max_speed: 2048
command_deadline_ms: 100
input_timeout_ms: 150
```

- Each inner controller sees its part as a follower of its own (the same unit and rate, its joints' limits) and follows its own input. Several inner controllers may follow the same input.
- A joint is driven by at most one inner controller. Joints no part drives stay where the follower holds them.
- The follower gets one command with all its joints, so a command caused by one input also carries the other parts' targets. It does so only while such a target is valid: within the inner controller's `command_deadline_ms` after it was commanded, and not after that controller has withheld a command. A part whose input stopped, was released or could not be reached by the IK gets the target the follower holds, so it never keeps moving toward an old target.
- When the follower latches `FAULT` or `ESTOP`, every part re-aligns before it commands again.
- Inner controllers cannot set `home` or `feedback` yet, and a parts controller cannot be a policy's `teleop:` controller.
- The controller's row shows `following` once any part commands; `parts` lists each inner controller's state.

## pose_ik <span class="status status--dev">In development</span> { #pose-ik }

Turns a hand-held device's pose into arm joints through inverse kinematics. Its input is a pose input (`pika_sense`). The mapping is relative: when the operator engages the clutch, the input's pose and the arm's tool pose at that moment become the reference, and the hand's motion from there moves the tool. See [Pika Sense and IK](../../controllers/pose-ik.md).

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `input` | text | required | — | Name of the pose input |
| `arm` | text | required | — | The arm follower (or part) whose IK is solved; it needs a kinematic model |
| `gripper` | text | — | — | A one-joint follower (or part) set from the jaw angle |
| `tool_offset` | `{xyz, rpy}` | required | m, rad | Tool frame seen from the flange |
| `workspace` | `{min, max}` | required | m | Target box in the arm's base frame; nothing is sent outside it |
| `max_input_jump` | `{position_m, rotation_rad}` | required | m, rad | An input that jumps more than this between samples counts as lost and stops teleoperation |
| `ik` | mapping | table below | — | IK settings |
| `gripper_map` | `{scale, offset}` | `{scale: 1.0, offset: 0.0}` | — | gripper = `scale` × jaw angle + `offset` |
| `max_speed` | `{follower: value}` | required | follower unit/s | Speed limit per follower |
| `input_timeout_ms` | number | required | ms | Teleoperation stops when the input gets older than this |
| `home` | `{follower: home}` | — | — | Saved poses ([home](control.md#home)) |

| `ik` key | Default | Unit |
| --- | --- | --- |
| `iterations` | `30` | iterations |
| `damping` | `0.001` | — |
| `position_tolerance_m` | `0.005` | m |
| `rotation_tolerance_rad` | `0.05` | rad |

## policy { #policy }

A learned policy is the controller. It drives every follower in configuration order ([Followers and controllers](#followers)) and has no input. Its keys are on [The policy controller](policy.md).

## Force feedback (feedback) <span class="status status--mock">Mock only</span> { #feedback }

!!! warning "Not verified on hardware"
    This is the path that returns the external force on the follower to the leader. Only the mock tests pass. See [Bilateral control design](../../contribution/bilateral.md) for the design and the remaining stages.

Add `estimators` to the configuration ([Estimators](#estimators)) and reference the estimator from the controller's `feedback`. In the template, the option `bilateral` adds `estimators.effort` and replaces the leader, controller, and follower with the node files for feedback. You do not write edges; the path below follows from each node's references.

```text
leader ──sample──► controller ──command──► follower ──state──► estimator
  ▲                    │  ▲                                  │
  └──── feedback ──────┘  └────────────── estimate ──────────┘
```

`feedback` is available only on a `joint` controller of one follower, and not with a joint map that has `scale`. The leader's side is [`feedback` in control](control.md#feedback).

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `estimator` | text | required | — | Name of the estimator node |
| `deadline_ms` | number | required | ms | Deadline after the follower state the estimate came from |
| `unit` | text | required | — | `<leader unit>/<estimator unit>` (e.g. `mA/mA`) |
| `gain` | `{follower joint: gain}` | required | — | Joints fed back and their gains (0 or more) |

```yaml
feedback:
  estimator: effort
  deadline_ms: 100
  unit: mA/mA          # leader unit / estimator unit
  gain:                # follower joint name -> gain (0 or more)
    r_arm_el_yaw: 0.1
```

The current sent to the leader is `−gain × sign × residual` (`sign` is the sign of the `joints` mapping). The controller asks for the feedback to be applied (gate) only while the estimate is valid and in contact, the follower is `ACTIVE`, and the controller is `following`. The deadline is `deadline_ms` after the follower state the estimate came from. An estimate that arrives after that deadline is not sent, and the controller status shows the reason in `feedback_error`. The leader accepts it only on joints of current-mode groups (`gravity_comp`, `impedance`) that have `feedback:`.

At load time, roboloom checks that references exist, that the estimator and the controller use the same follower, the units, and that the leader accepts the feedback. Mismatched settings are refused before start. Joints that are targets of `couplings` also receive feedback through the `joints` mapping. The Python API (`InProcessSession`) does not handle estimators.

## Estimators (estimators) <span class="status status--mock">Mock only</span> { #estimators }

`estimators:` is one of the top-level roles. An estimator computes a per-joint residual (measured − predicted for free motion) from the effort signal the follower declares (Rakuda2: `currents_mA`, in mA). External force acts opposite to the residual.

```yaml
estimators:
  effort: nodes/effort.yaml
```

Estimator (`nodes/effort.yaml`):

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `type` | text | required | — | `none` (never estimates; for checking the path) or `model_residual` |
| `follower` | text | required | — | Name of the follower node whose state it reads |
| `joints` | list of text | required | — | Follower joints to estimate |
| `models` | list of paths | required (`model_residual`) | — | Gravity models for `model_residual` (one per arm). Their output joints together must equal `joints` exactly |
| `smoothing_alpha` | number | `1.0` | — | Exponential moving average factor (greater than 0, at most 1; 1 = no smoothing) |
| `contact_on` | number | `0` | estimator unit | Contact when the L1 norm of the residual reaches this |
| `contact_off` | number | `0` | estimator unit | While in contact, contact ends below this (hysteresis). `contact_off` ≤ `contact_on`; both 0 means always in contact |
| `record` | boolean | `false` | — | `true` records the estimate in the dataset; `recorder.max_age_ms` needs an entry for this estimator |

`model_residual` is `residual = measured current − g(q)`, where `g(q)` is a gravity model identified on the follower; no training is needed. Friction, inertia and position tracking error stay in the residual, so it is not 0 while the arm moves freely. Watch `residual_l1` (the value the contact thresholds compare) in the estimator node's status while moving the follower freely and while pushing it, and put `contact_on` between the two. Build the gravity model with the same `identify-gravity` as the leader, from a follower calibration (`calibration/follower_<side>.yaml`).

```bash
uv run roboloom calibrate-joints .roboloom/rakuda2/calibration/follower_right.yaml
uv run roboloom identify-gravity .roboloom/rakuda2/calibration/follower_right.yaml \
    --out .roboloom/rakuda2/calibration/effort_gravity_right.yaml --collect
```

Because the follower arm mixes XM540 and XM430 motors, each joint is identified separately (`shared_parameters: false`), which needs more poses than the leader. Stop the follower node during identification.

An estimator with `record: true` records `observation.effort_ext` (external effort = −residual, in the estimator's unit), `observation.effort_ext.valid` and `observation.contact`. Frames without an estimate hold 0. Several recorded estimators are joined in configuration order; the `names` of `observation.effort_ext` are `<follower>.<joint>`, those of the other two the estimator names. Estimators with different units cannot share one vector and are refused at load.
