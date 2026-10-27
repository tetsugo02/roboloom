# Leader

For Rakuda2 teleoperation, the `leader` node in `inputs` (device `type: rakuda_mini`, the Rakuda-mini arm) reads joint positions, and the `joint` node in `controllers` converts them into follower targets. The mapping, signs, and offsets between leader joints and follower joints are specified in `joints` in `nodes/controller.yaml`.

```yaml
type: joint
input: leader
robot: robot
unit: dynamixel_count
alignment_tolerance: 300
max_speed_counts_per_s: 2048
command_deadline_ms: 100
input_timeout_ms: 150
# The actual configuration also needs the joints mapping table for all 17 joints.
```

`leader` is the node's role in the experiment and `type` names the device. To use another arm as the leader, change only `type`.

These are the values from the distributed template. Set them after checking the robot's range of motion, communication cycle, and stopping behavior.

| Key | Meaning |
| --- | --- |
| `alignment_tolerance` | Allowed joint difference between leader and follower before following begins and before every episode `start` (counts); `start` is refused above it |
| `max_speed_counts_per_s` | Upper limit on the rate of change of the target |
| `command_deadline_ms` | Validity period of commands sent to the robot |
| `input_timeout_ms` | Time until leader input is judged stale |

When `aligning` appears on screen, align the leader with the follower while watching the displayed joint differences. Run `start <task>` once it is `following`. If the input is stale, the state becomes `input_stale`, and following does not continue without new input.

The leader trigger is configured with `law: spring`, and gravity compensation with `law: gravity_comp`. These are motor control laws executed by the leader node itself. On hardware, run them in the `Session` / CLI dataflow. `Experiment.from_yaml()` does not accept a leader that executes control laws.

The concrete setup is in [Rakuda2 Quick start](../quick-start/rakuda2.md).

## Lock leader joints

In `control` of the active `nodes/leader.yaml` or `nodes/leader_gravity.yaml`, move the joints to lock into a `law: position` group. For example, replace the template's `body` group with these two groups to leave the torso free and lock neck yaw and pitch. Keep the arm and trigger groups. In older configurations where the torso and head belong to `hand`, remove these three joints from `hand`. Every joint must belong to exactly one group.

```yaml
control:
  - group: body
    law: free
    joints: [torso_yaw]
  - group: fixed_head
    law: position
    joints: [head_yaw, head_pitch]
  # Keep the existing arm and trigger groups below.
```

`position` writes the measured pose immediately before enabling torque, then enables only the selected joints. It does not move to an old Goal Position. Since the leader receives no external targets, it holds that pose. Locking begins when the Session launches, continues when `stop` ends collection, and releases on `estop`, `release`, or `quit`. Align the leader joints to be locked with the follower before launching.

The motors need position control and the corresponding bus APIs. The Operating Mode is read back and must match `position` (3 on Rakuda2); a mismatch prevents torque enable. If a change is needed, stop the dataflow, support the robot, and use the existing `roboloom commission <exp> leader --hardware`. Setting `torque: false` in `robot.yaml` does not disable leader locking.

## Configure joint compensation

`couplings` in `nodes/controller.yaml` adds another follower joint's **measured displacement** to a target after the joint mapping, signs, and offsets. The default is `[]` (disabled). For Rakuda2 torso yaw and neck yaw, when equal count changes represent rotations in the same direction, use:

```yaml
couplings:
  - joint: head_yaw
    source: torso_yaw
    scale: -1.0
    reference: 2048
```

```text
head target = head target mapped from the leader
            - (current follower torso position - reference)
```

`reference` is the torso position (counts) at which the head target mapped from the leader is used unchanged. Set it to the position where the torso faces forward. For example, a torso rotation of +100 counts from `reference` adds -100 counts to the head target. Combined with joint locking above, this compensates for torso rotation while the leader's neck stays fixed. If the leader's neck is free, compensation is added to the operator's head input.

- `joint` and `source` name follower joints. Self-coupling, unknown joints, repeated `joint` entries, and nonfinite `scale` values are rejected when loading the configuration.
- The reference is a configured constant, not the pose at alignment. Alignment accepts differences within `alignment_tolerance`, so a reference taken at that moment would offset the head by that difference for the whole session. Re-alignment and leader restarts keep the same reference.
- Alignment compares the compensated head target with the follower's head. If the follower camera starts far from forward, `head_yaw` exceeds the tolerance and the controller stays `aligning`. Align the follower camera heading with the leader's neck before launch.
- Using measured torso position rather than its target avoids commanding the neck ahead of a torso that has not caught up. Existing speed limits and robot-side range, deadline, and jump checks still apply after compensation.
- `joint`, `source`, `scale`, and `reference` are all required.
- This is linear compensation between specified joints. It does not stabilize the full camera orientation, use IMU feedback, or compensate for base rotation. It assumes parallel axes and correct signs and unit ratios. On another robot, set `scale` to account for axis signs and unit ratios. Speed limits, travel limits, and tracking lag leave errors in camera direction.
- It applies to `type: joint` teleoperation, not policy-controller outputs. Joint names are not embedded in the implementation, so other robots' joint controllers can use it too.

Joint locking and compensation have been verified with mock buses and controllers. Hardware direction, travel, and tracking accuracy remain unverified. Existing `.roboloom/` directories are not updated automatically; copy the examples into the active YAML files.
