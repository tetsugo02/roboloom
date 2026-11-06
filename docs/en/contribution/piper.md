# PiPER follower (in development, not verified on hardware)

!!! warning "In development"
    A record of the driver, in development, that runs an AgileX PiPER as a follower. It is checked only with the mock bus and tests against a stand-in for piper_sdk; it has not run on hardware. There is no robot template (`roboloom init`) or Quick start yet.

## Requirements

- piper_sdk (`uv add git+https://github.com/tetsugo02/roboloom.git --extra piper`). The V2 interface of the stable 0.6 line is used. Only joint position control (MOVE J), state and enabling are used, and their frames are the same with V3 firmware.
- One CAN interface (1 Mbps) per arm, named for the arm, such as `can_left` and `can_right`. Creating the interfaces and naming them by USB port needs sudo; ask an administrator.

## Configuration

```yaml
type: piper_follower
can: can_left            # this arm's CAN interface
control_hz: 100
speed_percent: 30        # share of the firmware's joint speed (1-100)
stale_ms: 50             # optional; older feedback latches FAULT
torque: true
record_effort: true      # record joint torque (N·m) in observation.effort
health:
  every_ticks: 10        # required: teach button, collisions and driver faults show only here
  max_temperature_c: 70
limits:                  # rad; each joint inside the PiPER range
  - {name: joint1, min: -2.6, max: 2.6, max_speed: 1.0, max_jump: 0.3}
  # ... joint2 to joint6
```

| Key | Meaning |
| --- | --- |
| `can` | The CAN interface name; a `SET_` placeholder is refused |
| `speed_percent` | Required; an integer 1-100. The share of speed at which the firmware moves to a target in MOVE J |
| `stale_ms` | Default 50. Feedback older than this latches FAULT as a bus failure (the SDK keeps returning the last values after a cable is pulled) |
| `health` | Required. The state is read every `every_ticks` |
| `limits` | rad. Values beyond the PiPER joint range (joint1 ±150°, joint2 0-180°, joint3 −170-0°, joint4 ±100°, joint5 ±70°, joint6 ±120°) are refused |
| `unattended` | Optional; the measured behaviour when left alone (see "Safety traits" below) |

`control:` (control-law groups) is not available: the PiPER runs position control on its own controller. The unit is fixed to `rad`.

## Behaviour

- Opening waits up to 2 s until joint, motor, driver and status feedback has arrived since opening. Before the first frame the SDK reports zeros, and a hold target taken from them would jump to 0 rad.
- Every command first sends CAN control, MOVE J and `speed_percent`, then the joint targets.
- Enabling repeats until all six joints report enabled (at most 5 s). The target is written at the current pose before enabling.
- These latch FAULT:
  - The control mode is not CAN (the teach button, for example)
  - The arm status is not normal (emergency stop, collision, joint communication error, over-temperature and others)
  - A joint communication error
  - A driver fault (low voltage, over-temperature, over-current, collision protection, stall)
  - A joint that became disabled after enabling
- `release` disables the motors. The arm falls.
- Ending the dataflow (closing the bus) does not disable the motors.

## Safety traits

| Trait | Value |
| --- | --- |
| `torque_off` | `falls` (it falls when the motors are disabled) |
| `unattended` | `unknown` (whether it holds when commands stop has not been checked) |

Because of `unknown`, the exit confirmation offers no "quit with followers holding". It offers supporting the arms and quitting with the torque off, or quitting without releasing (the arms may fall). The values are explained in "Behaviour without torque and when left alone" in [Configuration](../reference/configuration.md).

## Observation and action (`.roboloom/piper-mock/`)

With two PiPER arms and two Pika Grippers, the recorded dataset and the policy's inputs and outputs share the same order and units. The order is that of `followers:`.

| Name | Entries | Unit |
| --- | --- | --- |
| `observation.state`, `action` | 14 (`left.joint1` … `left.joint6`, `right.joint1` … `right.joint6`, `left_gripper.gripper`, `right_gripper.gripper`) | rad (the gripper's motor angle) |
| `observation.effort` | 12 (the two arms only) | N·m |
| `observation.images.camera`, `observation.images.left_wrist`, `observation.images.right_wrist` | 48×64×3 in the mock (RGB) | — |
| `observation.left_sense`, `observation.right_sense` | 10 (in teleoperation only; [Pika Sense](pika-sense.md)) | m, quaternion, rad |

- The grippers' current (mA) cannot share one `observation.effort` with the arms' N·m, so it is not recorded.
- The policy (option `policy`) observes `camera` and the two wrist cameras, and `infer` returns targets for the 14 entries in rad: one step `[14]` or a chunk `[H, 14]`. `max_speed` is in rad/s per follower.
- The inference configuration has no Senses, so a policy cannot use `observation.left_sense` and the like. How to write a policy and LeRobot policies are in [Driving with a policy](../controllers/policy.md).

## Checking the screen with mock devices

`.roboloom/piper-mock/` configures two mock PiPER arms (`left`, `right`), two Pika Grippers (`left_gripper`, `right_gripper`) and a camera, so the operator screen can be checked without hardware. The arms and grippers are teleoperated by mock Pika Senses ([Teleoperation with Pika Sense and IK](pika-sense.md)). After Launch, "Move home" brings the arms to their starting pose; the mock Senses then engage and the arms move. With `--with policy`, the demo policy in the same directory (`demo_policy.py`) moves them instead.

```bash
uv run roboloom run piper-mock
uv run roboloom run piper-mock --with policy
```

## First steps on hardware

1. Ask an administrator to create the CAN interfaces (1 Mbps, one name per arm).
2. With the arm powered, check its state read-only. Nothing is enabled or moved.

    ```bash
    uv run roboloom probe can_left
    ```

    It shows the firmware, joint angles (rad and degrees), control mode, enabling, temperatures, faults and feedback rates.

3. Measure whether it holds when left alone. Be ready to support the arm and clear the space around it. It holds the current pose for 2 s, stops writing with the motors enabled, and only reads the joints for up to `--seconds` (the state after quitting with holding, an ESTOP or a FAULT). The bus stays open, because closing and reopening CAN within one process is not reliable with piper_sdk; the PiPER driver does not disable the motors on close, so closing leaves the same state. A short `--seconds` can miss an arm that sags slowly. A change beyond `--tolerance` (rad) or a disabled motor means `torque_off`; otherwise `holds`. Typing `record` writes `unattended:` to the follower YAML. Finally, choose `release` to turn the torque off, or leave it as it is.

    ```bash
    uv run roboloom check-hold left --tolerance 0.02
    ```

## To check on hardware

- Whether the joint signs and zeros match the SDK's description.
- Whether the arm holds when commands stop with the motors enabled (`check-hold`).
- Whether the firmware takes a `JointCtrl` sent while the motors are disabled as its target on enabling. If so, the current pose written just before enabling becomes that target.
- What happens when enabling stops halfway (only some joints enabled). Today it gives up after 5 s with an error and leaves the enabled joints as they are.
- A single CAN frame of a message (for example joints 3-4) that stops alone goes unnoticed (the SDK keeps one receive time per message).
- How fast the loop runs on 1 Mbps CAN when every command is preceded by the control mode, to choose `control_hz`.
- The sign and size of the joint torque (`efforts_Nm`).
