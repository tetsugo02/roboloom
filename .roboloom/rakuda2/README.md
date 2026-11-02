# Rakuda-2 project

Created by `roboloom init rakuda2`. Everything measured on *this* robot is written into
these files; values still to fill are `SET_...` and every command refuses to run until
they are set. Commit the YAML files; `.roboloom/.gitignore` keeps out the raw
measurements (`*.npz`), logs and datasets.

| file | what | filled by |
| --- | --- | --- |
| `config.yaml` | the one configuration: leader teleop + RealSense, and the launch `options:` below | — |
| `nodes/follower.yaml`, `nodes/leader*.yaml` | port, EEPROM registers | step 1 |
| `nodes/camera.yaml`, `nodes/digit_*.yaml` | sensor serials | step 1 |
| `calibration/leader_<side>.yaml` | joint map for gravity identification | step 4 |
| `calibration/gravity_<side>.yaml` | identified gravity model | step 4 |
| `calibration/travel_<side>.yaml` | joint travel (runaway check) | step 5 |
| `calibration/gravity_tuning_<side>.yaml` | gain and hold per joint | step 7 |

`config.yaml` replaces `experiment.yaml`, `experiment_camera.yaml`, `experiment_gravity.yaml`
and `experiment_head_compensation.yaml`. Options add, replace
or remove node files; enabling one also enables what it `requires` and disables what it
`conflicts` with. An option with `dataset:` appends that name to `repo_id` and `output`:

| option | default | what | dataset |
| --- | --- | --- | --- |
| (none) | — | leader teleop + RealSense | `datasets/rakuda2` |
| `gravity` | **on** | gravity-compensated leader (steps 3-7 done) | same as without it |
| `head_compensation` | off | cancel the torso yaw on the head camera, neck held (trial); requires `gravity` | `datasets/rakuda2-head-compensation` |
| `digit` | off | add the left/right DIGIT sensors | `datasets/rakuda2-digit` |

The camera + gravity episodes recorded before were in `datasets/rakuda2-camera`; that set
is now `datasets/rakuda2`. To keep appending to them, rename it once (the dataset does not
store its repo_id): `mv .roboloom/rakuda2/datasets/rakuda2-camera .roboloom/rakuda2/datasets/rakuda2`.
`datasets/rakuda2-head-compensation` keeps its name.

Real hardware is the default; `--mock` uses mock devices (`--hardware` is gone and errors).
`uv run roboloom` alone opens the launcher: pick the robot (from the robots under
`.roboloom/`; Back returns to this list), then run, record or infer, tick the options,
choose mock or hardware, and see the dataset name. `run`, `record` and `infer` in a
terminal show it first too, unless `--with a,b`, `--without a,b` or `--plain` is given;
the last choice is kept in `logs/last_launch.yaml`. Options are not switched while running;
quit the operator screen with "Quit and choose options again" to return to the launcher.
Before a hardware launch from a terminal, the CLI compares the leader and follower EEPROM
(Operating Mode, Current Limit) with the chosen options and writes the differences only
after you confirm, so switching `gravity` on or off needs no separate `commission` step.

## Teleoperation and recording

1. **Ports, registers, serials.**
   `ls /dev/serial/by-id/` gives the two U2D2 ports (`SET_FOLLOWER_PORT`, `SET_LEADER_PORT`).
   `uv run roboloom probe <port>` prints each motor's EEPROM; copy per-joint `homing_offset`
   values that are not 0 into `registers.homing_offset` of `robot.yaml` and `leader*.yaml`
   (startup refuses to run on any mismatch and lists them). Set the FTDI latency timer to
   1 ms (`echo 1 | sudo tee /sys/bus/usb-serial/devices/ttyUSB*/latency_timer`). `rs-enumerate-devices` and the DIGIT labels give the
   sensor serials.
2. `uv run roboloom validate --without gravity`, then `uv run roboloom run --without gravity`
   (before the gravity steps below; afterwards just `uv run roboloom run` or `uv run roboloom`).

## Gravity-compensated leader (optional)

3. `calibration/leader_<side>.yaml`: set `port`, check the joint map, set `confirmed: true`.
4. `uv run roboloom identify-gravity .roboloom/rakuda2/calibration/leader_right.yaml --out .roboloom/rakuda2/calibration/gravity_right.yaml --collect`
   (about 40 poses; you confirm before it moves; hands off the arm while it measures). The same for `left`.
5. `uv run roboloom measure-travel .roboloom/rakuda2/calibration/leader_right.yaml --out .roboloom/rakuda2/calibration/travel_right.yaml`, and `left`.
6. Arms supported, dataflow stopped: `uv run roboloom commission leader --with gravity`
   (current mode and low Current Limits, EEPROM), or just launch with `gravity` and confirm
   the EEPROM write. Launching `--without gravity` offers to write the plain leader's values back.
7. `uv run roboloom tune-gravity leader right_arm --with gravity`, then `left_arm`:
   joint by joint, set how much weight is removed (gain) and how hard a push must be before
   the arm moves (hold). What the numbers mean: docs/gravity-tuning.md in the roboloom repository.
