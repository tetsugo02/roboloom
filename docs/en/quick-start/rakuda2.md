# Rakuda2 Quick start

This assumes you have added roboloom and the hardware-collection extras (`record` / `hardware`) to your own uv project following [Installation](installation.md). Commands and configuration paths are relative to your project root. For supported devices and configurations, see [Rakuda2](../robots/rakuda2.md).

## 1. Robot configuration and read check

```bash
uv run roboloom init rakuda2
ls /dev/serial/by-id/
```

If `.roboloom/rakuda2/` already exists, `init` does not overwrite it. Review the existing robot configuration and use it.

Identify the leader / follower U2D2 ports and read them while no other process is using them. Replace the `<...>` below with the actual ports.

```bash
uv run roboloom probe /dev/serial/by-id/<follower-U2D2>
uv run roboloom probe /dev/serial/by-id/<leader-U2D2>
```

| File (in `.roboloom/rakuda2/`) | What to set and check |
| --- | --- |
| `nodes/robot.yaml` | Follower `port`, IDs and models, `registers`, measured safe `limits`, velocity, current, and temperature limits |
| `nodes/leader.yaml`, `nodes/leader_gravity.yaml` | Leader `port`, IDs and models, `registers`, control law |
| `nodes/camera.yaml` | RealSense `serial` |
| `nodes/digit_left.yaml`, `nodes/digit_right.yaml` | Left and right DIGIT `serial` |
| `calibration/leader_right.yaml`, `calibration/leader_left.yaml` | Leader `port`, joint-to-URDF mapping, zero points, directions |

Apply values such as each joint's `homing_offset` from the `probe` results to the configuration. Gravity compensation deliberately changes the operating mode and Current Limit, so do not copy the current EEPROM as-is; check the difference from the configuration with `commission`, described below.

Template values are not a safety guarantee for your robot. In particular, the follower's `limits.min/max` are wide initial values. Narrow them to the measured safe range, and verify the stop and torque-off methods on each robot unit. Even with the standard leader, the trigger is powered.

For the first path check, **change `torque: true` to `torque: false` in `nodes/robot.yaml`**. Support the arms while the follower torque is off. This setting does not cut power on the leader side.

## 2. Check the collection path with the standard leader

You can start with the RealSense-only configuration. This experiment does not reference DIGIT, even if DIGIT is not connected yet.

```bash
uv run roboloom validate rakuda2/experiment_camera
```

If `SET_...` remains in a referenced configuration, its location is shown. Fill it in and validate again. `validate` does not open devices, so the hardware EEPROM and stop behavior must be checked separately.

If the EEPROM differs from the intended configuration, stop the dataflow and run `commission` while supporting both arms. Review the displayed changes before approving. This operation writes the EEPROM and reads it back.

```bash
uv run roboloom commission rakuda2/experiment_camera robot --hardware
uv run roboloom commission rakuda2/experiment_camera leader --hardware
uv run roboloom run rakuda2/experiment_camera --hardware
```

IDs, models, and EEPROM are also checked at startup, and startup is refused on a mismatch. Check the status of all nodes and the sensor acquisition rates on the screen. Align the leader to the follower's pose, and once the controller is `following`, enter the following in order.

```text
start pipeline check
stop
save
release
quit
```

At the `release` confirmation, support the follower arms. `quit` also releases the leader's torque, so support the leader arms as well before exiting. At this stage, keep the follower at `torque: false` and check the observation and recording path.

## 3. Set zero points, directions, and travel for gravity compensation

From here on, work with the dataflow stopped and no other tool holding the leader bus open. Support the arms and confirm torque is off. Check the mapping between motor IDs and URDF joints in the left and right calibration YAMLs, place the arm in the URDF zero pose, and measure.

```bash
uv run roboloom calibrate-joints .roboloom/rakuda2/calibration/leader_right.yaml
uv run roboloom calibrate-joints .roboloom/rakuda2/calibration/leader_left.yaml
```

Check the saved `zero` and each joint's `direction` (`1` or `-1`), and once the mapping, zero points, and directions are verified, set `confirmed: true` in each file. Do not approve template zero points or signs without checking them.

Slowly move the torque-off leader by hand to measure the left and right travel.

```bash
uv run roboloom measure-travel .roboloom/rakuda2/calibration/leader_right.yaml --out .roboloom/rakuda2/calibration/travel_right.yaml
uv run roboloom measure-travel .roboloom/rakuda2/calibration/leader_left.yaml --out .roboloom/rakuda2/calibration/travel_left.yaml
```

This operation only reads positions from the bus, but saves the result to YAML. This range is used to detect leader runaway; do not use it as a substitute for the follower's safety limits.

## 4. Identify the gravity model

`identify-gravity --collect` **powers the motors** to measure holding current. Check the surroundings and how the arm is supported, and follow the on-screen instructions for pose placement and releasing your hands.

```bash
uv run roboloom identify-gravity .roboloom/rakuda2/calibration/leader_right.yaml --out .roboloom/rakuda2/calibration/gravity_right.yaml --collect --hardware
uv run roboloom identify-gravity .roboloom/rakuda2/calibration/leader_left.yaml --out .roboloom/rakuda2/calibration/gravity_left.yaml --collect --hardware
```

Check the output fit and warnings. Saving is refused if joint directions or measurement quality are inadequate. Fix the cause and measure again; do not proceed with a model that was not generated. Errors remain depending on the configuration and measured poses, so tune gain and hold next.

## 5. Configure and tune gravity compensation mode

`nodes/leader_gravity.yaml` references the left and right `gravity_<side>.yaml`, `travel_<side>.yaml`, and `gravity_tuning_<side>.yaml`. After checking the current limits, watchdog, and travel, validate the configuration and check the EEPROM changes.

```bash
uv run roboloom validate rakuda2/experiment_gravity
uv run roboloom commission rakuda2/experiment_gravity leader --hardware
uv run roboloom tune-gravity rakuda2/experiment_gravity leader right_arm --hardware
uv run roboloom tune-gravity rakuda2/experiment_gravity leader left_arm --hardware
```

Support both arms when tuning starts. The side not being tuned has torque off.

| Key | Action |
| --- | --- |
| `↑` / `↓` | Select a joint |
| `[` / `]` | Decrease / increase the gain that cancels weight |
| `-` / `=` | Decrease / increase the holding force at motion onset, `hold_mA` |
| `0` | Toggle gravity compensation for the selected joint to compare |
| `s` | Save the tuned values |
| `q` | Quit |

If the arm drops, increase gain; if it rises, decrease it. If starting to move feels heavy, decrease hold. If the current stays pinned at the limit, stop tuning and review the configuration. Details and constraints are in [Gravity tuning](../reference/gravity-tuning.md). Current Limit and the watchdog are separate protections; do not assume that the XC330 watchdog triggering alone brings the current to zero.

## 6. Collect data with teleoperation

Before collecting, optionally configure [leader joint locking and torso-yaw compensation](../controllers/leader.md). Edit `control` in the active `leader*.yaml` and `couplings` in `controller.yaml`. Align the leader joints to be locked with the follower before launch. These settings work with both standard and gravity-compensated configurations, but the combination has not been tested on hardware.

The default for the gravity-compensated configuration is **RealSense only**. To also record DIGIT, change the sensors and save location following the [Rakuda2 configuration examples](../robots/rakuda2.md). For the standard leader + RealSense + DIGIT, specify `rakuda2`.

Before moving the follower, verify the robot's safe range, low-speed following, stop, and torque off, then change `nodes/robot.yaml` to `torque: true`. Support both arms, and start after completing the EEPROM check with the dataflow stopped.

```bash
uv run roboloom validate rakuda2/experiment_gravity
uv run roboloom run rakuda2/experiment_gravity --hardware
```

1. Check the robot status, sensor acquisition rates, and recorder.
2. Align the leader to the follower and confirm the controller is `following`. While an `aligning` warning is shown, match the pose and retry starting.
3. Start following and recording with `start pick up the cup`, and operate with the leader.
4. Stop with `stop`. `stop` holds the follower and does not turn off torque.
5. Save with `save`, or discard with `discard`. Check the saved result's warnings for missing-data rate, valid-command rate, and control period.
6. Collect another episode with the next `start <task>`.
7. To finish, do `stop` → save or discard → support the arms and `release` → support the leader too and `quit`, in that order.

`estop` on a fault is latched and does not recover automatically. Operate with physical support and stop means available.

Fixed-duration collection can also be done with the following. After the controller is ready, follow the on-screen instructions and press Enter to start.

```bash
uv run roboloom record rakuda2/experiment_gravity --task "pick up the cup" --seconds 30 --episodes 3 --hardware
```

The same dataflow can be used from Python.

```python
from roboloom import Session

with Session.launch("rakuda2/experiment_gravity", hardware=True) as session:
    session.wait_ready()
    result = session.record("pick up the cup", seconds=30)
    print(result.index, result.frames, result.warnings)
```

The arms must be supported when the script ends as well. To build in manual stop and release, see [Python API](../reference/python-api.md).

The default save location is `.roboloom/rakuda2/datasets/rakuda2-camera` (`output` is relative to the experiment YAML). Logs are kept in `.roboloom/rakuda2/logs/`. Keep the configuration, calibration, and tuning YAMLs under management, and you can resume collection into a dataset with the same configuration, FPS, and features.
