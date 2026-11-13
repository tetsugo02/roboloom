# Rakuda2 with Pika Sense and IK (in development)

!!! warning "In development, mock only"
    The option `pika` of the Rakuda2 template has been checked with mock devices only. The joint map of the arms (zero counts and directions), the gripper map, the tool offset and the workspace are first guesses, and the arm's inverse kinematics is poorly conditioned in some directions (see [Limitations](#limitations)). Do not run it on hardware before the checks under [Before hardware](#before-hardware).

One Pika Sense per arm drives Rakuda2 through inverse kinematics, in place of the leader. It is the first use of two mechanisms that are not specific to Rakuda2 or the Pika: [parts of a follower](../reference/configuration.md#parts-of-a-follower) and kinematics in the follower's own joint unit.

## How it is put together

| Node | File | What |
| --- | --- | --- |
| tracker `lighthouse` | `nodes/lighthouse.yaml` | libsurvive, one node for both Senses |
| inputs `right_sense`, `left_sense` | `nodes/right_sense.yaml`, `nodes/left_sense.yaml` | the hand poses and jaw angles ([Pika Sense](pika-sense.md)) |
| controller `controller` | `nodes/controller_pika.yaml` | `type: parts`: owns the two controllers below and sends the follower one command with all 17 joints |
| inside it | `nodes/pika_right.yaml`, `nodes/pika_left.yaml` | `type: pose_ik` on `follower.right_arm` + `follower.right_gripper` (and the left ones) |
| follower `follower` | `nodes/follower.yaml` | unchanged; its `kinematics:` names the joint map of each arm |

```bash
uv run roboloom run --with pika --mock
```

- The torso and head (part `body`) are driven by no controller and stay where the follower holds them. Poses are relative to the frame that turns with the torso.
- The mapping is relative, as on PiPER: when the operator engages, the hand's motion from then on moves the tool from where the arm was. Nothing is sent while the target is outside `workspace` or the IK does not reach it.
- The follower's safety checks, the recorded `action` (17 counts) and the dataset layout are those of leader teleoperation; the dataset name gets `-pika` because the recorded inputs differ.
- The IK works in the URDF's rad. The arm's counts are converted at both ends with the joint map in `calibration/follower_<side>.yaml` (`urdf`, `zero`, `direction` per joint): rad = direction × (count − zero) × 2π / 4096.
- The gripper is a one-joint part in counts: counts = `gripper_map.scale` × jaw angle (rad) + `gripper_map.offset`.

## Before hardware

1. Check each arm joint's `zero` and `direction` in `calibration/follower_<side>.yaml` on the robot (`roboloom calibrate-joints`), then set `confirmed: true`. With `confirmed: false`, hardware refuses to start with this option; mock devices start.
2. Measure the gripper counts when the Sense's jaw is closed and open, and fill `SET_<SIDE>_GRIPPER_CLOSED_COUNT` and `SET_<SIDE>_GRIPPER_COUNTS_PER_RAD` in `nodes/pika_<side>.yaml`.
3. Set `tool_offset` and `workspace` for this robot, start with a low `max_speed`, and follow "First things on hardware" of [Pika Sense](pika-sense.md).

## Limitations

- **Conditioning of the arm's IK.** With the shipped URDF (`assembly_2.urdf`, a CAD export) the smallest singular value of the arm's Jacobian was between 0.001 and 0.02 m/rad at the poses sampled, so there is usually one direction of translation the arm can hardly produce while keeping the tool's orientation. In such a direction the controller reports `unreachable` and holds. Whether this is the arm's real geometry or an error in the URDF or the joint map has not been checked. A solver that weights position over orientation is not implemented.
- Inner controllers of `type: parts` have no `home` yet: bring the arms to a bent pose by other means before engaging (the straight arm is singular).
- The option cannot be combined with `policy`, and a parts controller cannot be a policy's `teleop:` controller.

## Other inputs and a simulator

The pieces above are meant to be reused; none of the following is implemented.

- **VR controllers, UMI-like grippers.** A device that gives a pose becomes a subclass of `PoseInput` (`roboloom.inputs.base`: position, quaternion, optional gripper angle, `tracking`, `engaged`), registered in `roboloom.inputs.INPUTS`. `pose_ik` and `parts` then work unchanged. A device read on another computer must stamp samples with the receiving host's clock.
- **A leader shaped like the follower.** `type: joint` needs no joint table when the names and unit agree ([Leader](../controllers/leader.md)); other arms write `joints:`.
- **Another robot.** A follower model declares its joints, unit, safety traits and, when it has an arm chain, `kinematics()` with the map from its unit to rad (identity for a robot that speaks rad, as PiPER). `PARTS` is only for followers several controllers should share. The control laws under `control:` (`roboloom.control`) assume a Dynamixel-like bus (counts, mA, operating modes); a robot with its own position control, like PiPER, does not use them.
- **A simulator.** A follower's `open_bus` returns a `JointBus` (`read_positions`, `write_positions`, `enable_torque`, `close`, optionally `read_state`). A simulated bus behind the same follower model keeps controllers, IK, safety checks and recording unchanged. If it speaks the real follower's unit (counts for Rakuda2, through the same joint map), datasets and policies are interchangeable with the robot's.
