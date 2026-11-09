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

- For PiPER + Pika hardware, choose both robot extras. `piper` includes the PiPER SDK and Pinocchio for IK; `pika` includes `pysurvive` and the wrist-camera dependency.
    - In your own project: `uv add git+https://github.com/tetsugo02/roboloom.git --extra piper --extra pika` (add `--extra record` to save episodes)
    - In a checkout of the roboloom repository: `uv sync --extra piper --extra pika`
- The tracker is read through libsurvive (`pysurvive` in Python). The `pika` extra installs a wheel (Linux x86_64) built by a fork of libsurvive; nothing is built at install time. Ask an administrator for the tracker's udev rules (`81-vive.rules`). See [Installation](../quick-start/installation.md) for details. Without pysurvive, the Sense's node stops and says why.
- `pysurvive` is required for real Sense tracker poses only: PiPER joint control, Pika serial/camera access and mocks do not use it. For mock `pose_ik` and `roboloom validate`, the standalone `ik` extra is sufficient (`uv sync --extra ik` in the checkout).
- The Sense's serial link is handled directly through pyserial, as for the Pika Gripper. Name the port with `/dev/serial/by-path/...`.

## Configuration

```yaml
# config.yaml (excerpt): one tracking system node serves both Senses
trackers:
  lighthouse: nodes/lighthouse.yaml
inputs:
  left_sense: nodes/left_sense.yaml
  right_sense: nodes/right_sense.yaml
```

```yaml
# nodes/lighthouse.yaml
type: libsurvive
args: []                 # optional: extra libsurvive arguments, e.g. [--lighthouse-gen, "2"]
# poll_hz: 200           # optional: how often the poses are published
```

```yaml
# nodes/left_sense.yaml
type: pika_sense
port: /dev/serial/by-path/pci-0000:00:14.0-usb-0:3:1.0-port0
tracker: {system: lighthouse, serial: LHR-0123ABCD}  # the tracker's serial number
stale_ms: 100            # optional, default 100: older pose or serial feedback counts as lost
# poll_hz: 100           # optional; required in a configuration without followers
```

```yaml
# nodes/left_ik.yaml
type: pose_ik
input: left_sense
followers: [left, left_gripper]
arm: left                # the arm the IK drives (a follower with a kinematic model)
gripper: left_gripper    # optional: a one-joint follower driven by the jaw angle
tool_offset: {xyz: [0.0, 0.0, 0.19], rpy: [0.0, -1.5708, 0.0]}  # required: tool frame seen from the flange (link6)
workspace: {min: [0.05, -0.45, 0.05], max: [0.6, 0.45, 0.6]}    # required: m, in the arm's base frame (base_link)
max_input_jump: {position_m: 0.05, rotation_rad: 0.5}             # required
ik: {iterations: 30, damping: 0.001, position_tolerance_m: 0.005, rotation_tolerance_rad: 0.05}  # optional; these are the defaults
gripper_map: {scale: 1.0, offset: 0.0}                            # optional; these are the defaults
max_speed: {left: 1.0, left_gripper: 3.0}                         # required: one value per follower
home: {left: {pose: ../poses/left/ready.yaml, max_speed: 0.5, tolerance: 0.02}}  # optional
command_deadline_ms: 100 # required
input_timeout_ms: 150    # required
```

`pika_sense`:

| Key | Meaning |
| --- | --- |
| `port` | Required. The Sense's serial port. A value left as `SET_` is refused |
| `tracker.system` | Required. The tracking system node under `trackers:` that reads this Sense's tracker |
| `tracker.serial` | Required. The tracker's serial number (`LHR-...`; see "First steps on hardware"). Names like `WM0` follow the order libsurvive finds the trackers in and may swap, so they are not used. A value left as `SET_` is refused. The older keys `tracker.name` and `tracker.args` are refused with a pointer to these |
| `stale_ms` | Default 100. A pose or serial feedback older than this counts as lost |
| `poll_hz` | Optional. The rate at which the input is read. Without it, the input runs at the fastest `control_hz` of the followers its controllers drive. Required in a configuration without followers ([Hand-held collection with Pika Sense](pika-handheld.md)) |

`libsurvive` (a node under `trackers:`): one libsurvive context opens the USB receivers once and serves every Sense, and both trackers' poses come in one calibrated world frame. libsurvive claims the receivers, so a second context in another process would find no tracker. Its single thread keys poses by serial; a rotation libsurvive reports as all zeros (lost tracking) marks that tracker lost (`tracking` 0, the Sense disengages) until the next good pose. The node is not recorded; its status shows the serials it sees, how often tracking was lost, and an error if libsurvive stopped.

| Key | Meaning |
| --- | --- |
| `args` | Optional. A list of strings passed to libsurvive |
| `poll_hz` | Optional. How often the poses are published. Without it, as fast as the fastest Sense that reads it |

`pose_ik`:

| Key | Meaning |
| --- | --- |
| `arm`, `gripper` | `arm` is required: a follower with a kinematic model (the PiPER). `gripper` is optional: a one-joint follower. Together they must name exactly the controller's `followers` |
| `tool_offset` | Required. The transform from the flange to the tool tip (`xyz` in m, `rpy` in rad). The value above is the one AgileX uses for its own gripper; measure it with the Pika Gripper mounted |
| `workspace` | Required. `min` and `max` (m, `min` below `max` on every axis). No command is sent while the target position is outside this box |
| `max_input_jump` | Required. `position_m` and `rotation_rad`. Teleoperation stops when the Sense's pose jumps by more than this between two samples |
| `ik` | Optional. Iterations (default 30), damping (default 0.001), and the position (default 0.005 m) and rotation (default 0.05 rad) tolerances counted as reached. Unknown keys are refused. Nothing is sent when the IK does not reach the target |
| `gripper_map` | Optional. Gripper angle = `scale`·jaw angle + `offset` (defaults 1.0 and 0.0), kept inside the gripper's range |
| `max_speed` | Required, one value per follower. Speed limit (unit/s). Time spent without commands is not saved up: one command moves at most `input_timeout_ms` worth |
| `home` | Optional. The saved pose "Move home" goes to, per follower. Each entry needs `pose`, `max_speed` (not above that follower's `max_speed`) and `tolerance`; `timeout_s` defaults to 30 |
| `command_deadline_ms` | Required. How long a command stays valid. A follower refuses an older command and holds |
| `input_timeout_ms` | Required. A gap between inputs longer than this stops teleoperation (see "Engaging and stopping" below) |

The dataset gains `observation.<name>` per Sense (`x, y, z, qx, qy, qz, qw, gripper, tracking, engaged`, in the tracker's world frame). `action` stays the followers' joint commands.

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

`.roboloom/piper-mock/` is part of the roboloom repository, not of the installed package (`roboloom init` has only the `rakuda2` template). Run the commands below from the root of a checkout of the repository. In your own project, you can copy the directory from [the repository](https://github.com/tetsugo02/roboloom) into your `.roboloom/` and run it the same way. It is a mock configuration (`mode: mock`); do not reuse its ports, CAN interfaces, tracker names, `limits`, `tool_offset` or `workspace` on hardware.

```bash
uv run roboloom run piper-mock                     # after Launch, Move home
uv run roboloom run piper-mock --with policy       # the demo policy instead of the Senses
```

Running a policy trained on the recorded data is described in [Driving with a policy](../controllers/policy.md). Collecting with Senses held in the hands, without a robot, is described in [Hand-held collection with Pika Sense](pika-handheld.md).

## First steps on hardware

1. Install the `pika` extra (above); ask an administrator for the tracker's udev rules.
2. Place the base stations and calibrate them with libsurvive. The Python package does not include `survive-cli`, so open libsurvive from Python with `--force-calibrate`. Keep the tracker still where the base stations see it, and stop with Ctrl-C once poses appear. Each line shows the tracker's serial number (`LHR-...`), which goes into `tracker.serial`, and its current name. This procedure has not been verified on hardware.

    ```bash
    uv run python - <<'EOF'
    import time
    import pysurvive

    ctx = pysurvive.SimpleContext(["calibrate", "--force-calibrate"])
    try:
        while ctx.Running():
            updated = ctx.NextUpdated()
            if updated:
                serial = pysurvive.simple_serial_number(updated.ptr) or b""
                print(serial.decode(), updated.Name().decode(), updated.Pose()[0].Pos[:])
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    EOF
    ```

3. Check the Sense's serial link by reading only. Only `GET_INFO`, which asks for the version, is sent.

    ```bash
    uv run roboloom probe /dev/serial/by-path/... --device pika_sense
    ```

    It shows the version, the jaw angle, `Command` and the feedback rates.

4. Measure `tool_offset`, narrow `workspace` to the table and its surroundings, then try one arm first.

## What to check on hardware

- The trackers' serial numbers, and the pose rate and latency.
- Whether the one `lighthouse` node sees both trackers and both Senses follow their own.
- Recovery after unplugging the receiver or switching a Sense off. The fork carries upstream's unmerged fixes for the crash on unplug ([#383](https://github.com/collabora/libsurvive/pull/383), issue #372) and for timed-out or stalled USB transfers ([#378](https://github.com/collabora/libsurvive/pull/378)); they are tested against a fake libusb only.
- How `Command` changes (whether a double-click swaps 0 and 1).
- The jaw angle's direction and range, and how it maps to the Pika Gripper's angle (`gripper_map`).
- Whether the SDK's transform from the tracker to the Sense's centre (`inputs/pika_sense/spec.py`) is right for your units.
- `tool_offset` (how the Pika Gripper is mounted).
- The PiPER's firmware version. The URDF matches the DH of S-V1.6-3 and later.
