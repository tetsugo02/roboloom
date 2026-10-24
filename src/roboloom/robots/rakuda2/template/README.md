# Rakuda-2 project

Created by `roboloom init rakuda2`. Everything measured on *this* robot is written into
these files; values still to fill are `SET_...` and every command refuses to run until
they are set. Commit the YAML files; `.roboloom/.gitignore` keeps out the raw
measurements (`*.npz`), logs and datasets.

| file | what | filled by |
| --- | --- | --- |
| `experiment.yaml` | leader teleop + RealSense + 2 DIGIT | — |
| `experiment_camera.yaml` | the same without DIGIT | — |
| `experiment_gravity.yaml` | camera set, gravity-compensated leader | — |
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
   (startup refuses to run on any mismatch and lists them). Set the FTDI latency timer to
   1 ms (`echo 1 | sudo tee /sys/bus/usb-serial/devices/ttyUSB*/latency_timer`). `rs-enumerate-devices` and the DIGIT labels give the
   sensor serials.
2. `uv run roboloom validate rakuda2`, then `uv run roboloom run rakuda2/experiment_camera --hardware`.

## Gravity-compensated leader (optional)

3. `calibration/leader_<side>.yaml`: set `port`, check the joint map, set `confirmed: true`.
4. `uv run roboloom identify-gravity .roboloom/rakuda2/calibration/leader_right.yaml --out .roboloom/rakuda2/calibration/gravity_right.yaml --collect --hardware`
   (about 40 poses; hands off the arm while it measures). The same for `left`.
5. `uv run roboloom measure-travel .roboloom/rakuda2/calibration/leader_right.yaml --out .roboloom/rakuda2/calibration/travel_right.yaml`, and `left`.
6. Arms supported, dataflow stopped: `uv run roboloom commission rakuda2/experiment_gravity leader --hardware`
   (current mode and low Current Limits, EEPROM). Back to the plain leader: commission `rakuda2/experiment_camera`.
7. `uv run roboloom tune-gravity rakuda2/experiment_gravity leader right_arm --hardware`, then `left_arm`:
   joint by joint, set how much weight is removed (gain) and how hard a push must be before
   the arm moves (hold). What the numbers mean: docs/gravity-tuning.md in the roboloom repository.
