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

- **Conditioning of the arm's IK.** With the shipped URDF (`assembly_2.urdf`, a CAD export) there is usually one direction of translation the arm can hardly produce while keeping the tool's orientation. In such a direction the controller reports `unreachable` and holds. Whether this is the arm's real geometry or an error in the URDF or the joint map has not been checked, and a solver that weights position over orientation is not implemented. The numbers, the likely causes and the options are in [IK conditioning in detail](#ik-conditioning-in-detail).
- Inner controllers of `type: parts` have no `home` yet: bring the arms to a bent pose by other means before engaging (the straight arm is singular).
- The option cannot be combined with `policy`, and a parts controller cannot be a policy's `teleop:` controller.

## IK conditioning in detail

This section is for whoever picks the problem up next. Everything in it is computed from the shipped URDF and the unconfirmed joint map; nothing was measured on the robot. Reproduce it with:

```bash
uv run python scripts/ik_conditioning.py rakuda2
uv run python scripts/ik_conditioning.py .roboloom/piper-mock/config.yaml   # for comparison
```

**What is measured.** `pose_ik` asks the six arm joints for a full pose: three numbers of position and three of orientation, so no freedom is left over. The script samples 3000 joint poses (within ±1.5 rad of the URDF's zero pose, seed 1) and takes the smallest singular value of the tool Jacobian: how far the tool moves, in its worst direction, per radian of joint motion. Near zero, the damped least squares solver (`roboloom.kinematics.ik.ArmModel.solve`: 30 iterations, damping 0.001, at most 0.2 rad per iteration) does not get within the tolerances (5 mm, 0.05 rad) and the controller reports `unreachable`.

| Smallest singular value, 5% / median / 95% | Rakuda2 right arm | Rakuda2 left arm | PiPER |
| --- | --- | --- | --- |
| position + orientation (m/rad) | 0.0004 / 0.0089 / 0.0448 | 0.0004 / 0.0100 / 0.0481 | 0.0019 / 0.0341 / 0.1230 |
| position only (m/rad) | 0.0176 / 0.0546 / 0.0857 | 0.0168 / 0.0524 / 0.0845 | 0.0568 / 0.1296 / 0.1998 |
| orientation only | 0.72 / 1.06 / 1.30 | 0.70 / 1.06 / 1.29 | 0.64 / 1.02 / 1.22 |
| reach from the first joint to the tool at the zero pose | 0.30 m | 0.30 m | — |

**What the numbers say.**

- For the position alone Rakuda2 is about 2.4 times worse than PiPER at the median. A shorter arm explains a difference of this kind: the same joint motion moves a shorter lever less.
- With the orientation constrained too, Rakuda2 is about 4 times worse at the median, and at one pose in twenty it is below 0.0004 m/rad. The size does not explain this part; the order of the joints does. The weakest direction is always mostly a translation (at the right arm's zero pose: `[vx vy vz] = [-0.16, 0.30, 0.94]`): the arm can turn the tool, but cannot move it that way without also turning it.
- At the URDF's zero pose the right arm is exactly singular (0.0005): the axis of `elbow_yaw_right_dof` (motor `r_arm_sh_pitch2`) and the axis of `wrist_yaw_right_dof` (motor `r_arm_wr_roll`) are parallel, both `[0.06, 0.46, 0.89]` in the base frame. The mock follower starts there (2048 counts on every joint).
- **The two arms are not mirror images at the zero pose.** On the left, the same two axes are `[0.07, -0.40, 0.92]` and `[-0.28, 0.05, 0.96]`, and the smallest singular value there is 0.011. A CAD export fixes the zero pose wherever the assembly happened to stand, so the URDF's zero is probably not the pose where the motors read 2048. The joint map's `zero: 2048` for every joint is therefore suspect, joint by joint. This is the first thing to check on the robot.
- The motor names and the URDF names disagree in kind (`r_arm_sh_pitch2` ↔ `elbow_yaw_right_dof`, `r_arm_el_yaw` ↔ `elbow_pitch_right_dof`, `r_arm_wr_roll` ↔ `wrist_yaw_right_dof`, `r_arm_wr_yaw` ↔ `wrist_pitch_right_dof`). The map in `calibration/leader_<side>.yaml` was written for gravity identification, where `identify-gravity` tries sign combinations; it was copied to `follower_<side>.yaml` unchecked. Which name is right is not known.

**What is not known.** Whether the URDF's link lengths and axes match the real arm; the zero count and direction of each follower joint; whether the real robot shows the same weak directions. A wrong zero or direction changes which poses are singular, but not the fact that six joints have nothing to spare for a full pose.

**What can be done, in the order of effort.**

1. *On the robot, no code:* confirm the joint map (`roboloom calibrate-joints .roboloom/rakuda2/calibration/follower_right.yaml`, then compare a few poses with `ArmModel.fk`), then rerun the script.
2. *By the operator:* engage with the elbow bent and do not stretch the arm. This avoids the worst poses only; the median is still poor.
3. *In the configuration:* raise `ik.rotation_tolerance_rad` and `ik.damping` in `nodes/pika_<side>.yaml`. Not tried. Note that the solver still weighs orientation and position errors alike, so this trades accuracy for fewer refusals rather than fixing the cause.
4. *In the solver (the real fix, not implemented):* weight the position over the orientation (a weighted damped least squares on the 6-vector of errors, or a position task with the orientation in its null space), or drop one orientation component (a 5-degree-of-freedom task: the rotation about the tool's own axis). The position alone is conditioned about as well as a short arm can be.
5. *In the chain (not implemented):* add the torso yaw as a seventh joint. Both arms hang from it, so two controllers would have to share it; `type: parts` gives each joint one owner today.
6. *Not possible by tuning:* the arm's own geometry.

**Where the code is.** `src/roboloom/kinematics/ik.py` (`ArmModel`, the solver), `src/roboloom/kinematics/spec.py` (`KinematicSpec`: the unit map), `src/roboloom/robots/rakuda2/follower.py` (`kinematics`), `src/roboloom/robots/rakuda2/spec.py` (`ARM_BASE`, `ARM_TIP`, `PARTS`), `src/roboloom/controllers/pose_ik.py`, `src/roboloom/robots/rakuda2/model/assembly_2.urdf`, `tests/test_rakuda_kinematics.py`, `tests/test_rakuda_pika.py` (its test moves the hand along x because z is not reachable from the pose it uses).

## Other inputs and a simulator

The pieces above are meant to be reused; none of the following is implemented.

- **VR controllers, UMI-like grippers.** A device that gives a pose becomes a subclass of `PoseInput` (`roboloom.inputs.base`: position, quaternion, optional gripper angle, `tracking`, `engaged`), registered in `roboloom.inputs.INPUTS`. `pose_ik` and `parts` then work unchanged. A device read on another computer must stamp samples with the receiving host's clock.
- **A leader shaped like the follower.** `type: joint` needs no joint table when the names and unit agree ([Leader](../controllers/leader.md)); other arms write `joints:`.
- **Another robot.** A follower model declares its joints, unit, safety traits and, when it has an arm chain, `kinematics()` with the map from its unit to rad (identity for a robot that speaks rad, as PiPER). `PARTS` is only for followers several controllers should share. The control laws under `control:` (`roboloom.control`) assume a Dynamixel-like bus (counts, mA, operating modes); a robot with its own position control, like PiPER, does not use them.
- **A simulator.** A follower's `open_bus` returns a `JointBus` (`read_positions`, `write_positions`, `enable_torque`, `close`, optionally `read_state`). A simulated bus behind the same follower model keeps controllers, IK, safety checks and recording unchanged. If it speaks the real follower's unit (counts for Rakuda2, through the same joint map), datasets and policies are interchangeable with the robot's.
