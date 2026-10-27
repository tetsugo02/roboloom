# Rakuda-2 project

Created by `roboloom init rakuda2`. Everything measured on *this* robot is written into
these files; values still to fill are `SET_...` and every command refuses to run until
they are set. Commit the YAML files; `.roboloom/.gitignore` keeps out the raw
measurements (`*.npz`), logs and datasets.

## Installation and project directory

Run commands from your own uv project root, which contains `pyproject.toml` and
`.roboloom/`. Set `project.requires-python` to `">=3.12,<3.13"` and add roboloom from GitHub:

```bash
uv add git+https://github.com/tetsugo02/roboloom.git --extra record --extra hardware
uv run roboloom --help
```

This README and the robot configuration are copied from the installed package by
`uv run roboloom init rakuda2`. Package updates do not overwrite existing configuration.

The [Rakuda2 Quick start](https://tetsugo02.github.io/roboloom/en/quick-start/rakuda2/)
([日本語](https://tetsugo02.github.io/roboloom/ja/quick-start/rakuda2/)) walks through setup,
gravity compensation, and teleoperation recording. Sensor/controller combinations are in
[Rakuda2](https://tetsugo02.github.io/roboloom/en/robots/rakuda2/).
Before the first run, change `nodes/robot.yaml` from its default `torque: true` to
`torque: false` to check the recording path without moving the follower. This does not
disable the leader's trigger or gravity-compensation motors. Support both arms at startup
and shutdown. Set `torque: true` only after validating the follower's limits and stop behavior.

| file | what | filled by |
| --- | --- | --- |
| `experiment.yaml` | leader teleop + RealSense + 2 DIGIT | — |
| `experiment_camera.yaml` | the same without DIGIT | — |
| `experiment_gravity.yaml` | camera set, gravity-compensated leader | — |
| `experiment_policy.yaml`, `nodes/policy.yaml` | a policy drives the follower (inference) | your policy |
| `nodes/robot.yaml`, `nodes/leader*.yaml` | port, EEPROM registers | step 1 |
| `nodes/camera.yaml`, `nodes/digit_*.yaml` | sensor serials | step 1 |
| `calibration/leader_<side>.yaml` | joint map for gravity identification | step 4 |
| `calibration/gravity_<side>.yaml` | identified gravity model | step 4 |
| `calibration/travel_<side>.yaml` | joint travel (runaway check) | step 5 |
| `calibration/gravity_tuning_<side>.yaml` | gain and hold per joint | step 7 |

Experiments are named relative to `.roboloom`: `roboloom run rakuda2 --hardware` runs
`experiment.yaml`, `roboloom run rakuda2/experiment_gravity --hardware` the gravity one.

## Teleoperation and recording

1. **Ports, registers, serials.**
   `ls /dev/serial/by-id/` gives the two U2D2 ports (`SET_FOLLOWER_PORT`, `SET_LEADER_PORT`).
   `uv run roboloom probe <port>` prints each motor's EEPROM; copy per-joint `homing_offset`
   values that are not 0 into `registers.homing_offset` of `robot.yaml` and `leader*.yaml`
   (startup refuses to run on any mismatch and lists them). Check the FTDI latency timer;
   if it needs system configuration, ask the machine administrator. `rs-enumerate-devices` and the DIGIT labels give the
   sensor serials.
   `probe` also prints the bus read times and a rough limit for `control_hz` / `poll_hz`
   (120 Hz here, which needs latency_timer 1 ms); lower both if probe shows less, and check
   `work_ms` on the run screen (docs: Reference >
   Configuration, Control rate).
2. `uv run roboloom validate rakuda2`, then `uv run roboloom run rakuda2/experiment_camera --hardware`
   (operator screen, many episodes), or one fixed-length episode:
   `uv run roboloom record rakuda2/experiment_camera --task "pick up the cup" --seconds 30 --hardware`.
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
`quit` then select Hold, or by hand after `release`); each becomes `poses/<name>.yaml`:
`uv run roboloom capture-pose rakuda2/experiment_gravity ready --hardware`.
Choose one with `home:` in `nodes/controller.yaml` (see the comment there) and type `home`
on the run screen (or `record ... --home`): leader and follower move slowly
(`max_speed`) to it; one second after arriving the leader is back on gravity
compensation. A gravity leader's arm groups
need `homing:` (set in `leader_gravity.yaml`). Hands off the arms while they move.

## Gravity-compensated leader (optional)

3. `calibration/leader_<side>.yaml`: set `port`, check the joint map, set `confirmed: true`.
4. `uv run roboloom identify-gravity .roboloom/rakuda2/calibration/leader_right.yaml --out .roboloom/rakuda2/calibration/gravity_right.yaml --collect --hardware`
   (about 40 poses; hands off the arm while it measures). The same for `left`.
5. `uv run roboloom measure-travel .roboloom/rakuda2/calibration/leader_right.yaml --out .roboloom/rakuda2/calibration/travel_right.yaml`, and `left`.
6. Arms supported, dataflow stopped: `uv run roboloom commission rakuda2/experiment_gravity leader --hardware`
   (current mode and low Current Limits, EEPROM). Back to the plain leader: commission `rakuda2/experiment_camera`.
7. `uv run roboloom tune-gravity rakuda2/experiment_gravity leader right_arm --hardware`, then `left_arm`:
   joint by joint, set how much weight is removed (gain) and how hard a push must be before
   the arm moves (hold). What the numbers mean: [Gravity tuning](https://tetsugo02.github.io/roboloom/en/reference/gravity-tuning/).

`experiment_gravity.yaml` includes RealSense only. To record DIGIT as well, add
`digit_left: nodes/digit_left.yaml` and `digit_right: nodes/digit_right.yaml` under
`sensors`, fill their serials, and use a separate `repo_id` and `output` because the
dataset features change. To finish an operator-screen run: `stop`, `save` or `discard`,
support the leader and follower arms, `quit`, then select Hold or supported Release.
Cancel is initially selected, so Enter alone cancels.

## Inference

8. `uv run roboloom infer rakuda2/experiment_policy --seconds 20 --hardware` first runs the
   template's `hold` policy, which keeps the arm where it is: it checks the inference path.
   Then pass yours: `--policy my_lab.policies:load --policy-kwargs '{"checkpoint": "..."}'`
   (or set `factory`/`kwargs` in `nodes/policy.yaml`). Add `--task` to record the run into
   `datasets/rakuda2_eval`.

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
