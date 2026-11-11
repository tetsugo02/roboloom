# Rakuda-2 project

Created by `roboloom init rakuda2`. Everything measured on *this* robot is written into
these files; values still to fill are `SET_...` and every command refuses to run until
they are set. Commit the YAML files; `.roboloom/.gitignore` keeps out the raw
measurements (`*.npz`), logs and datasets.

## Installation and project directory

Run commands from your own uv project root, which contains `pyproject.toml` and
`.roboloom/`. Set `project.requires-python` to `">=3.12,<3.13"` and add roboloom from GitHub:

```bash
uv add git+https://github.com/tetsugo02/roboloom.git --extra rakuda2 --extra record --extra hardware --extra digit
uv run roboloom --help
```

This README and the robot configuration are copied from the installed package by
`uv run roboloom init rakuda2`. Package updates do not overwrite existing configuration.

The [Rakuda2 Quick start](https://tetsugo02.github.io/roboloom/en/quick-start/rakuda2/)
([日本語](https://tetsugo02.github.io/roboloom/ja/quick-start/rakuda2/)) walks through setup,
gravity compensation, and teleoperation recording. Sensor/controller combinations are in
[Rakuda2](https://tetsugo02.github.io/roboloom/en/robots/rakuda2/).
Before the first run, change `nodes/follower.yaml` from its default `torque: true` to
`torque: false` to check the recording path without moving the follower. This does not
disable the leader's trigger or gravity-compensation motors. Support both arms at startup
and shutdown. Set `torque: true` only after validating the follower's limits and stop behavior.

| file | what | filled by |
| --- | --- | --- |
| `config.yaml` | the one configuration: leader teleop + RealSense, and the launch `options:` below | — |
| `nodes/policy.yaml` | the policy that drives the follower (option `policy`) | your policy |
| `nodes/follower.yaml`, `nodes/leader*.yaml` | port, EEPROM registers | step 1 |
| `nodes/camera.yaml`, `nodes/digit_*.yaml` | sensor serials | step 1 |
| `calibration/leader_<side>.yaml` | joint map for gravity identification | step 4 |
| `calibration/gravity_<side>.yaml` | identified gravity model | step 4 |
| `calibration/travel_<side>.yaml` | joint travel (runaway check) | step 5 |
| `calibration/gravity_tuning_<side>.yaml` | gain and hold per joint | step 7 |

Options in `config.yaml` add, replace or remove node files. Enabling one also enables what
it `requires` and disables what it `conflicts` with. An option with `dataset:` appends that
name to `repo_id` and `output`, so a different set of recorded features goes into its own
dataset:

| option | default | what | dataset |
| --- | --- | --- | --- |
| (none) | — | leader teleop + RealSense | `local/rakuda2` |
| `digit` | off | add the left/right DIGIT sensors (fill their serials) | `local/rakuda2-digit` |
| `gravity` | off | gravity-compensated leader (after steps 3-7) | same as without it |
| `bilateral` | off | force feedback to the leader; requires `gravity`; **not verified on hardware** | `local/rakuda2-bilateral` |
| `policy` | off | a policy drives the follower; DIGIT optional, conflicts with `gravity`; `infer` turns it on | `local/rakuda2-eval` (`-digit-eval` with `digit`) |

Real hardware is the default; `--mock` uses mock devices (`--hardware` is gone and errors).
`uv run roboloom` alone opens the launcher: pick the robot (from the robots under
`.roboloom/`; Back returns to this list), then run, record or infer, tick the options,
choose mock or hardware, and see the dataset name before starting. `run`, `record` and
`infer` in a terminal show it first too, unless `--with a,b`, `--without a,b` or `--plain`
is given. The last choice is kept in `logs/last_launch.yaml`. Options are not switched
while running; quit the operator screen with "Quit and choose options again" to return to
the launcher. With only one robot under `.roboloom/`, the configuration name can be left
out (`uv run roboloom run` or `uv run roboloom run rakuda2`).

Before a hardware launch from a terminal, the CLI compares the EEPROM (Operating Mode,
Current Limit) of the leader and follower with the chosen options, shows the differences,
and writes them only after you confirm. Switching `gravity` on or off therefore needs no
separate `commission` step; `uv run roboloom commission <node> --with ...` is still there.

## Teleoperation and recording

1. **Ports, registers, serials.**
   `ls /dev/serial/by-id/` gives the two U2D2 ports (`SET_FOLLOWER_PORT`, `SET_LEADER_PORT`).
   `uv run roboloom probe <port>` prints each motor's EEPROM; copy per-joint `homing_offset`
   values that are not 0 into `registers.homing_offset` of `nodes/follower.yaml` and `nodes/leader*.yaml`
   (startup refuses to run on any mismatch and lists them). Check the FTDI latency timer;
   if it needs system configuration, ask the machine administrator. `rs-enumerate-devices` and the DIGIT labels give the
   sensor serials.
   `probe` also prints the bus read times and a rough limit for `control_hz` / `poll_hz`
   (120 Hz here, which needs latency_timer 1 ms); lower both if probe shows less, and check
   `work_ms` on the run screen (docs: Reference >
   Configuration, Control rate).
2. `uv run roboloom validate`, then `uv run roboloom run` (the launcher first, then the
   operator screen for many episodes), or one fixed-length episode:
   `uv run roboloom record --task "pick up the cup" --seconds 30`.
   From Python, `roboloom.Session` does the same and can name tasks automatically
   ([Python API](https://tetsugo02.github.io/roboloom/en/reference/python-api/)).

## Lock selected leader joints and compensate torso yaw (optional)

Both options are disabled by default. They have been checked with mock buses and
controllers; check motor directions, travel, and tracking on your robot before use.
Existing projects are not changed by a package update.

In the active `nodes/leader.yaml` or `nodes/leader_gravity.yaml`, replace `body` with:

```yaml
- group: body
  law: free
  joints: [torso_yaw]
- group: fixed_head
  law: position
  joints: [head_yaw, head_pitch]
```

Keep the arm and trigger groups. In older files, remove these three joints from
`hand` instead. Every joint must occur exactly once. `position` seeds the measured
startup pose before torque enable and holds it; align these leader joints with the
follower before launch. Locking starts at Session launch, persists through `stop`,
and releases on `estop`, `release`, or `quit`. The motors must already be in position
mode (3); startup checks this without changing EEPROM. Use the normal `commission`
workflow if the modes differ. Follower `torque: false` does not disable leader locking.

In `nodes/controller.yaml`, replace `couplings: []` with:

```yaml
couplings:
  - joint: head_yaw
    source: torso_yaw
    scale: -1.0
    reference: 2048
    lead_ms: 70
```

The controller subtracts the measured follower torso displacement from `reference`
(the torso count facing forward) from the mapped head target. This example assumes
matching yaw axis signs and count units. The reference is fixed, not the pose at
alignment, so the alignment tolerance does not offset the head; align the follower
camera heading with the leader's neck before launch. `lead_ms` places the head target
ahead along the measured torso velocity, for the head's own position-loop lag (about
70 ms on Rakuda2). Speed and robot safety limits still apply, so limits and
tracking lag leave camera heading errors. This is relative yaw compensation, not full
camera stabilization. It applies to joint teleoperation, not policy outputs. Other
robots can use their own joint names and scale. Details: [Leader](https://tetsugo02.github.io/roboloom/en/controllers/leader/)
([日本語](https://tetsugo02.github.io/roboloom/ja/controllers/leader/)).

## Initial pose (optional)

Save poses by name while the dataflow is stopped (follower posed by teleoperation then
`quit` then select Hold, or by hand after `release`); each becomes `poses/<follower>/<name>.yaml`:
`uv run roboloom capture-pose ready`.
Choose one with `home:` in `nodes/controller.yaml` (see the comment there) and type `home`
on the run screen (or `record ... --home`): leader and follower move slowly
(`max_speed`) to it; one second after arriving the leader is back on gravity
compensation. A gravity leader's arm groups
need `homing:` (set in `leader_gravity.yaml`). Hands off the arms while they move.

## Gravity-compensated leader (optional)

3. `calibration/leader_<side>.yaml`: set `port`, check the joint map, set `confirmed: true`.
4. `uv run roboloom measure-travel .roboloom/rakuda2/calibration/leader_right.yaml --out .roboloom/rakuda2/calibration/travel_right.yaml`, and `left`.
5. `uv run roboloom identify-gravity .roboloom/rakuda2/calibration/leader_right.yaml --out .roboloom/rakuda2/calibration/gravity_right.yaml --collect`
   (about 40 poses; you confirm before it moves; hands off the arm while it measures). The same for `left`.
6. Arms supported, dataflow stopped: `uv run roboloom commission leader --with gravity`
   (current mode and low Current Limits, EEPROM), or just launch with the `gravity` option
   and confirm the EEPROM write. Launching without `gravity` offers to write the plain
   leader's values back the same way.
7. `uv run roboloom tune-gravity leader right_arm --with gravity`, then `left_arm`:
   joint by joint, set how much weight is removed (gain) and how hard a push must be before
   the arm moves (hold). What the numbers mean: [Gravity tuning](https://tetsugo02.github.io/roboloom/en/reference/gravity-tuning/).

Then run with `uv run roboloom run --with gravity` (or tick it in the launcher). To record
DIGIT as well, fill the serials in `nodes/digit_*.yaml` and enable the `digit` option
(`--with gravity,digit`); it records into its own dataset (`local/rakuda2-digit`). To finish an operator-screen run: `stop`, `save` or `discard`,
support the leader and follower arms, `quit`, then select Hold or supported Release.
Cancel is initially selected, so Enter alone cancels.

## Bilateral teleoperation (not verified)

The `bilateral` option (`--with bilateral`, which also enables `gravity`) returns the
external force on the follower to the leader. It
is **not verified on hardware**; check every step with the arms supported. Files:

| file | what |
| --- | --- |
| `nodes/follower_bilateral.yaml` | follower arms in current-based position control (Mode 5): set `SET_FOLLOWER_ARM_GOAL_CURRENT_mA` |
| `nodes/leader_bilateral.yaml` | `leader_gravity.yaml` with `feedback:` on the arm groups (needs the gravity steps above) |
| `nodes/controller_bilateral.yaml` | `controller.yaml` with `feedback:` (one joint, small gain) |
| `nodes/effort.yaml` | the follower effort estimator (`model_residual`: measured current - g(q)) |
| `calibration/follower_<side>.yaml` | joint map for identifying the follower's g(q) |

1. Identify the follower's gravity model per arm (follower node stopped, arm supported):
   `uv run roboloom calibrate-joints .roboloom/rakuda2/calibration/follower_right.yaml`, set
   `confirmed: true` after checking the map, then
   `uv run roboloom identify-gravity .roboloom/rakuda2/calibration/follower_right.yaml --out .roboloom/rakuda2/calibration/effort_gravity_right.yaml --collect`
   (same for left). This works on the motors as `nodes/follower.yaml` commissioned them
   (position mode). Do it first: every command with `--with bilateral`, `commission`
   included, loads `nodes/effort.yaml` and stops while `effort_gravity_<side>.yaml` is missing.
2. Fill `SET_FOLLOWER_ARM_GOAL_CURRENT_mA` (mA) in `nodes/follower_bilateral.yaml`, then write
   Operating Mode 5 and the Current Limit: `uv run roboloom commission follower --with bilateral`
   (or confirm the EEPROM write when launching with `bilateral`). Launching without
   `bilateral` offers to write Mode 3 back; `nodes/follower.yaml` refuses to start on Mode 5 motors.
3. `uv run roboloom run --with bilateral`: the follower should track and
   hold as before, and stop pushing at the goal current when it meets an obstacle. Watch
   `residual_l1` of the `effort` node while moving freely and while pushing, then set
   `contact_on` / `contact_off` in `nodes/effort.yaml` between the two.
4. Check the feedback on one joint: `nodes/controller_bilateral.yaml` returns only
   `r_arm_el_yaw` with gain 0.05. Push the follower's right elbow while following: the
   leader's `feedback` status should show `gate` rising to 1 and a small `mA` on the elbow,
   and the leader elbow should be pushed the same way as the follower. If it pushes the
   other way, stop (`estop`) and report it; do not raise the gain or add joints before the
   direction is right. `feedback.max_mA` in `nodes/leader_bilateral.yaml` caps it.

## Inference

8. `uv run roboloom infer --seconds 20` (turns on the `policy` option, uses joint state
   and RealSense by default, and turns `gravity` off) first runs the
   template's `hold` policy, which keeps the arm where it is: it checks the inference path.
   Then pass yours: `--policy my_lab.policies:load --policy-kwargs '{"checkpoint": "..."}'`
   (or set `factory`/`kwargs` in `nodes/policy.yaml`). Add `--task` to record the run into
   `datasets/rakuda2-eval` (`datasets/rakuda2-digit-eval` with `--with digit`).

Set `observe` in `nodes/policy.yaml` to the sources used during training: `[camera]`
(default), `[camera, digit_left, digit_right]` with the `digit` option, or `[]` for
joint state only. Enabling `digit` alone only adds sensors for recording; it does not
change the policy inputs. To avoid opening an unused sensor, also remove its node
from `sensors` in `config.yaml`. LeRobot checkpoints requiring missing inputs are
refused before an episode starts. Use `action_horizon: 1` with LeRobot `mode: step`.

Existing project files are not overwritten by package updates. To migrate an older
configuration, remove `requires: [digit]` from `options.policy` in `config.yaml` and
set `observe: [camera]` in `nodes/policy.yaml`.

## Operator screen

Interactive run, record, infer, and tune-gravity use Textual: Ctrl-L command input,
Tab/Shift-Tab completion, Up/Down history, Ctrl-N/Ctrl-P panes, Ctrl-G emergency stop,
and Ctrl-C/Ctrl-Q exit confirmation. Logs always has its own tab; Operations stays visible with more space.
Below 100 columns, the node list and details use separate tabs. Drag the vertical
divider between nodes and details, or the horizontal divider above Operations,
to resize panes. Double-click a divider to reset it. Ctrl-N/Ctrl-P can focus
a divider for arrow-key resizing and Ctrl-R reset. Proportions persist for the
session across tab changes and terminal resizing; they are not saved to disk. Node selection changes the display only; experiment
operations target all configured nodes. Record/infer show readiness, remaining
time, episode count, and results; select Start for each episode. `record --home`
moves home before every episode. Inference saves only with `--task`.

`run --plain` uses line input; `record --plain` and `infer --plain` run without
key input. Non-TTY runs select these paths automatically. Tuning requires a TTY
before device open. Tuning commands are `joint <name>`, `gain + / -`, `hold + / -`,
`compare`, `resume`, `save`, `estop`, and `quit`. Tuning exit offers Save, Discard,
and Cancel; Cancel is initially selected. Changes made during saving remain dirty.
Ctrl-G latches tuning ESTOP until restart; resume cannot bypass it.

Python `Session.launch(..., screen="auto")` keeps its input-free Rich display
and existing operator prompts. See [Operator screen](https://tetsugo02.github.io/roboloom/en/reference/operator-screen/)
([日本語](https://tetsugo02.github.io/roboloom/ja/reference/operator-screen/)).
This screen migration is verified with mocks; hardware operation needs separate validation.


Sensors can be selected individually with `--sensors camera,audio`; policy inputs
are selected separately with `--observe camera`. Empty strings select none.
Rakuda2 audio is off by default; configure nodes/audio.yaml and install the audio
extra to use PCM or mel numeric observations with a custom policy.
Dataset schema mismatches require a manually chosen repo_id/output.
Physical microphone capture is unverified.
