# Teleoperation with Pika Sense and IK (in development, not tested on hardware)

!!! warning "In development"
    Notes on teleoperating the PiPER by turning the pose of a hand-held AgileX Pika Sense into joint angles with IK. It has been checked only with a mock Sense and tests against fake devices, never on hardware. The protocol and the frame transforms were read from the source of AgileX's pika_sdk, pika_ros and PikaAnyArm.

## Parts

| Part | Role |
| --- | --- |
| Pika Sense (`pika_sense` input) | The hand-held device. Its Vive tracker gives the pose; its serial link gives the jaw angle and the engage/disengage button (`Command`) |
| Base stations (Lighthouse) | Needed to track the pose. libsurvive calibrates them |
| `pose_ik` controller | Turns the Sense's pose into PiPER joint angles (IK) and its jaw angle into the Pika Gripper's angle |
| PiPER and Pika Gripper followers | [PiPER follower](piper.md), [Pika Gripper follower](pika-gripper.md) |

One Sense drives one arm and one gripper. Two arms use two Senses and two controllers. The cameras are covered in [Pika wrist cameras](pika-cameras.md).

## Requirements

- The IK runs on pinocchio. Install it with `uv add 'roboloom[ik]'` (in this repository, `uv sync --extra ik`).
- The tracker is read through libsurvive (`pysurvive` in Python). Installing libsurvive and its udev rules (`81-vive.rules`) needs sudo, so ask an administrator. Without pysurvive, the Sense's node stops and says why.
- The Sense's serial link is handled directly through pyserial, as for the Pika Gripper. Name the port with `/dev/serial/by-path/...`.

## Configuration

```yaml
# nodes/left_sense.yaml
type: pika_sense
port: /dev/serial/by-path/pci-0000:00:14.0-usb-0:3:1.0-port0
tracker: {name: WM0}     # the tracker's name in libsurvive
stale_ms: 100            # optional: older pose or serial feedback counts as lost
```

```yaml
# nodes/left_ik.yaml
type: pose_ik
input: left_sense
followers: [left, left_gripper]
arm: left                # the arm the IK drives (a follower with a kinematic model)
gripper: left_gripper    # optional: a one-joint follower driven by the jaw angle
tool_offset: {xyz: [0.0, 0.0, 0.19], rpy: [0.0, -1.5708, 0.0]}  # tool frame seen from the flange (link6)
workspace: {min: [0.05, -0.45, 0.05], max: [0.6, 0.45, 0.6]}    # m, in the arm's base frame (base_link)
max_input_jump: {position_m: 0.05, rotation_rad: 0.5}
ik: {iterations: 30, damping: 0.001, position_tolerance_m: 0.005, rotation_tolerance_rad: 0.05}
gripper_map: {scale: 1.0, offset: 0.0}
max_speed: {left: 1.0, left_gripper: 3.0}
home: {left: {pose: ../poses/left/ready.yaml, max_speed: 0.5, tolerance: 0.02}}
command_deadline_ms: 100
input_timeout_ms: 150
```

| Key | Meaning |
| --- | --- |
| `tracker.name` | The name libsurvive gives the tracker (e.g. `WM0`). `args` adds arguments for libsurvive |
| `tool_offset` | The transform from the flange to the tool tip. The value above is the one AgileX uses for its own gripper; measure it with the Pika Gripper mounted |
| `workspace` | No command is sent while the target position is outside this box |
| `max_input_jump` | Teleoperation stops when the Sense's pose jumps by more than this between two samples |
| `ik` | Iterations, damping, and the position and rotation tolerances counted as reached. Nothing is sent when the IK does not reach the target |
| `gripper_map` | Gripper angle = `scale`·jaw angle + `offset`, kept inside the gripper's range |
| `max_speed` | Speed limit per follower (unit/s). Time spent without commands is not saved up: one command moves at most `input_timeout_ms` worth |
| `home` | The saved pose "Move home" goes to, per follower |

The dataset gains `observation.<name>` per Sense (`x, y, z, qx, qy, qz, qw, gripper, engaged`, in the tracker's world frame). `action` stays the followers' joint commands.

## Mapping

The mapping is relative, as in AgileX's teleoperation.

- When the Sense engages, the controller keeps the Sense's pose T_s0 and the arm's tool pose T_a0 (forward kinematics of the target the arm holds).
- From then on, `T_a0 · inv(T_s0) · T_s` is the tool's target. The hand's motion, in the Sense's own frame, moves the tool in the tool's frame.
- No calibration between the tracker's world and the arm's base is needed.

## Engaging and stopping

- Each change of the Sense's `Command` engages or disengages (a double-click in AgileX's software).
- In the following cases teleoperation stops and nothing moves until the Sense disengages and engages again.
  - The pose is lost or stale (the base stations cannot see it), or the serial link stopped
  - The pose jumped by more than `max_input_jump`
  - A follower latched `FAULT` or `ESTOP`, or the input went stale (including a gap between inputs longer than `input_timeout_ms`)
  - A follower is moving home ("Move home")
- While the target is outside `workspace` or the IK cannot reach it, nothing is sent and the arm holds. Teleoperation stays engaged and continues once the target is back.
- The PiPER's power-on pose (all joints 0, folded) is singular and the IK can hardly solve from there. Use "Move home" to go to the `home` pose before engaging.

## Checking with mock devices

`.roboloom/piper-mock/` drives two mock PiPER arms and two Pika Grippers with two mock Senses. A mock Sense engages 2 s after opening, then repeats 10 s engaged and 2 s disengaged.

```bash
uv run roboloom run piper-mock                     # after Launch, Move home
uv run roboloom run piper-mock --with demo_policy  # the demo policy instead of the Senses
```

## First steps on hardware

1. Ask an administrator to install libsurvive (with pysurvive) and its udev rules.
2. Place the base stations and calibrate them with libsurvive (`survive-cli --force-calibrate`). Find the tracker's name (`WM0` or another).
3. Check the Sense's serial link by reading only. Only `GET_INFO`, which asks for the version, is sent.

    ```bash
    uv run roboloom probe /dev/serial/by-path/... --device pika_sense
    ```

    It shows the version, the jaw angle, `Command` and the feedback rates.

4. Measure `tool_offset`, narrow `workspace` to the table and its surroundings, then try one arm first.

## What to check on hardware

- The tracker's name and serial, and the pose rate and latency.
- Whether two Senses can be read through libsurvive from separate processes. If not, read both in one input node.
- How `Command` changes (whether a double-click swaps 0 and 1).
- The jaw angle's direction and range, and how it maps to the Pika Gripper's angle (`gripper_map`).
- Whether the SDK's transform from the tracker to the Sense's centre (`inputs/pika_sense/spec.py`) is right for your units.
- `tool_offset` (how the Pika Gripper is mounted).
- The PiPER's firmware version. The URDF matches the DH of S-V1.6-3 and later.
