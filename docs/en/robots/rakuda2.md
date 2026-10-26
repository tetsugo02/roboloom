# Rakuda2

Rakuda2 has **17 joints**: 3 torso/head joints, plus 6 arm joints and 1 gripper joint on each of the left and right sides. Joint values are raw Dynamixel position counts, and current is in mA.

The follower is `type: rakuda2_follower` and the operator input is `type: rakuda2_leader`. The leader and follower use separate Dynamixel buses, each owned exclusively by its node. Create the configuration with `roboloom init rakuda2`.

## Supported controllers

The current operation guide covers the [Leader](../controllers/leader.md). Joint positions are read via `inputs.leader`, and a `type: joint` controller converts them for the follower.

- Standard leader: the arms, torso, and head have torque off; the trigger is controlled as a spring.
- Leader with gravity compensation: the left and right arms are controlled with `gravity_comp`, using the identified gravity model, range of motion, and tuning values.
- Selected leader joints can be locked at their startup pose with `position`. Configure torso-yaw compensation for the neck camera through `couplings` in the `joint` controller. Both standard and gravity-compensated leaders can use these options; they are disabled by default. See the [examples and limitations](../controllers/leader.md). The combination has been verified only in mock environments.
- Align the leader and follower before starting. While in `aligning`, start is refused and the joint differences are shown as a warning. You can retry after aligning.

## Supported sensors

| Sensor | Node name | Config | Recorded values |
| --- | --- | --- | --- |
| [RealSense](../sensors/realsense.md) | `camera` | `nodes/camera.yaml` | RGB image (depth is not captured) |
| [DIGIT](../sensors/digit.md) | `digit_left`, `digit_right` | `nodes/digit_left.yaml`, `nodes/digit_right.yaml` | Left and right tactile RGB images |

Set the sensor serial numbers to match the hardware. Sensor names are also used as feature names in the dataset.

## Experiment combinations

| Experiment | Leader | Sensors |
| --- | --- | --- |
| `rakuda2` / `rakuda2/experiment` | Standard | RealSense + left/right DIGIT |
| `rakuda2/experiment_camera` | Standard | RealSense |
| `rakuda2/experiment_gravity` | With gravity compensation | RealSense |

To use gravity compensation together with DIGIT, add the following to `sensors` in the generated `experiment_gravity.yaml`.

```yaml
sensors:
  camera: nodes/camera.yaml
  digit_left: nodes/digit_left.yaml
  digit_right: nodes/digit_right.yaml
```

When adding them, also change `repo_id` and `output`, for example to `local/rakuda2-gravity-digit` and `datasets/rakuda2-gravity-digit`. Because the image features change, you cannot append to an existing RealSense-only dataset.

## Checks before launch

Verify ports, motor IDs, models, EEPROM, joint ranges, and speed/current limits on the hardware. The template has `torque` set to `true`, so if you want to check the pipeline the first time without moving the follower, **change `nodes/robot.yaml` to `torque: false` before launch**. Leader-side control is independent; the trigger and gravity compensation are energized.

For the steps from setup to data collection, see [Rakuda2 Quick start](../quick-start/rakuda2.md); for the meaning of the control values, see [Gravity tuning](../reference/gravity-tuning.md).
