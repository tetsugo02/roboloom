# Leader

For the Rakuda2 leader, the `rakuda2_leader` node in `inputs` reads joint positions, and the `joint` node in `controllers` converts them into follower targets. The mapping, signs, and offsets between leader joints and follower joints are specified in `joints` in `nodes/controller.yaml`.

```yaml
type: joint
input: leader
robot: robot
unit: dynamixel_count
alignment_tolerance: 150
max_speed_counts_per_s: 2048
command_deadline_ms: 100
input_timeout_ms: 150
# The actual configuration also needs the joints mapping table for all 17 joints.
```

These are the values from the distributed template. Set them after checking the robot's range of motion, communication cycle, and stopping behavior.

| Key | Meaning |
| --- | --- |
| `alignment_tolerance` | Allowed joint difference between leader and follower before start (counts) |
| `max_speed_counts_per_s` | Upper limit on the rate of change of the target |
| `command_deadline_ms` | Validity period of commands sent to the robot |
| `input_timeout_ms` | Time until leader input is judged stale |

When `aligning` appears on screen, align the leader with the follower while watching the displayed joint differences. Run `start <task>` once it is `following`. If the input is stale, the state becomes `input_stale`, and following does not continue without new input.

The leader trigger is configured with `law: spring`, and gravity compensation with `law: gravity_comp`. These are motor control laws executed by the leader node itself. On hardware, run them in the `Session` / CLI dataflow. `Experiment.from_yaml()` does not accept a leader that executes control laws.

The concrete setup is in [Rakuda2 Quick start](../quick-start/rakuda2.md).
