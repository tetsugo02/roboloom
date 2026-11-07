# Pika Gripper follower (in development, not tested on hardware)

!!! warning "In development"
    Notes on the driver that runs an AgileX Pika Gripper as a follower. It has been checked only with the mock bus and with tests against a fake serial port, never on hardware. The protocol was read from the source of AgileX's pika_sdk and pika_ros.

## Requirements

- No extra package. roboloom talks to the serial port directly through pyserial (a roboloom dependency). AgileX's SDK (`agx-pypika`) is not used, because it also requires camera and GUI packages.
- One USB serial cable and a 24 V supply per gripper. It is a separate device from the PiPER's CAN, so it is configured as a follower of its own, apart from the PiPER.
- Name the port with `/dev/serial/by-path/...`, which is fixed by the USB socket. Numbers such as `/dev/ttyUSB0` can swap left and right after replugging or a reboot. by-path needs no sudo (the path changes if you move the cable to another socket).
- The gripper's cameras (fisheye and D405) are configured as sensors of their own ([Pika wrist cameras](pika-cameras.md)).

## Configuration

```yaml
type: pika_gripper_follower
port: /dev/serial/by-path/pci-0000:00:14.0-usb-0:2:1.0-port0
control_hz: 100
current_limit_A: 1.0     # required: the motor current limit sent before enabling (0 < x <= 2)
stale_ms: 100            # optional: older feedback latches FAULT
torque: true
record_effort: true      # record the motor phase current (mA) in observation.effort
health:                  # required: over-current, overheating and driver faults show only here
  every_ticks: 10        # optional, default 10
  max_temperature_c: 70
limits:                  # rad (motor angle), inside 0 to 1.67
  - {name: gripper, min: 0.0, max: 1.6, max_speed: 3.0, max_jump: 0.5}
```

| Key | Meaning |
| --- | --- |
| `port` | The serial port. A value left as `SET_` is refused |
| `current_limit_A` | Required. The motor current limit (A). Values beyond the range pika_sdk documents (0 to 2 A) are refused |
| `stale_ms` | Default 100. Feedback older than this latches FAULT as a bus failure. The frames carry no time, so the time they were received is used |
| `health` | Required (`health: {}` is enough). The status is read every `every_ticks` control ticks (default 10) |
| `limits` | rad. Values beyond the gripper's range (0 to 1.67 rad) are refused |
| `unattended` | Optional. The measured value when left alone (see "Safety traits" below) |

`record_effort` cannot be combined with the PiPER's `record_effort` in one configuration: `observation.effort` is a single vector, so N·m (PiPER) and mA (gripper) cannot be mixed, and loading the configuration refuses it. Record it for one of them only.

There is one joint, `gripper`. Its value is the motor angle (rad); 0 is closed. The opening width (mm) is not used: it is converted by pika_sdk's linkage model and has not been checked on hardware (by that model 1.67 rad is about 97 mm). `control:` (control-law groups) is not available: the gripper's driver does the position control.

## Behaviour

- On opening, it waits up to 2 s for `motor` and `motorstatus` feedback to arrive after the port opened.
- Commands are sent as the motor angle (rad). FollowerSafety checks the range and speed.
- Enabling first sends the current limit, then repeats enable until the status reports enabled (up to 2 s).
- Any of the following latches FAULT.
  - Feedback older than `stale_ms` (power or USB lost)
  - A fault bit in the status (supply voltage low, motor over-temperature, over-current, driver over-temperature, sensor abnormal, driver error)
  - The motor became disabled after enabling
- `release` disables the motor: the gripper lets go of what it holds.
- Ending the dataflow (closing the port) does not disable the motor.

## Safety traits

| Trait | Value |
| --- | --- |
| `torque_off` | `lets_go` (assumed to let go of objects when the motor is disabled, since it has no brake) |
| `unattended` | `unknown` (whether it holds once commands stop has not been checked) |

Because it is `unknown`, the quit dialog does not offer "Quit with followers holding". The `release` confirmation says to take objects out. The values are explained in "Behaviour without torque and when left alone" in [Configuration](../reference/configuration.md).

## Checking the screen with mock devices

`.roboloom/piper-mock/` configures two mock PiPER arms (`left`, `right`), two Pika Grippers (`left_gripper`, `right_gripper`) and a camera, so the operator screen can be checked without hardware. The arms and grippers are teleoperated by mock Pika Senses ([Teleoperation with Pika Sense and IK](pika-sense.md)). After Launch, "Move home" brings the arms to their starting pose; the mock Senses then engage and the arms move. With `--with policy`, the demo policy in the same directory (`demo_policy.py`) moves them instead.

`.roboloom/piper-mock/` is part of the roboloom repository, not of the installed package (`roboloom init` has only the `rakuda2` template), so run the commands below from the root of a checkout of the repository. In your own project, you can copy the directory from [the repository](https://github.com/tetsugo02/roboloom) into your `.roboloom/`; it needs the `ik` extra ([Teleoperation with Pika Sense and IK](pika-sense.md)). Its values are for mock mode only; do not reuse them on hardware.

```bash
uv run roboloom run piper-mock
uv run roboloom run piper-mock --with policy
```

## First steps on hardware

1. Connect the gripper's USB and power, and find the port's path.

    ```bash
    ls -l /dev/serial/by-path/
    ```

2. Check its state by reading only. It is neither enabled nor moved (only `GET_INFO`, which asks for the version, is sent).

    ```bash
    uv run roboloom probe /dev/serial/by-path/... --device pika
    ```

    It shows the version, the angle, speed and current, the status bits (enabled, homed), the voltage, temperatures, feedback rates and faults.

3. Measure whether it holds when left alone. Keep your hands away and nothing between the fingers. The procedure is the same as for the PiPER ("First steps on hardware" in [PiPER follower](piper.md)).

    ```bash
    uv run roboloom check-hold left_gripper --tolerance 0.02
    ```

## What to check on hardware

- Whether angle 0 is closed. If not, a step that sets the zero with pika_sdk's `set_zero()` (command 12) is needed (roboloom has none yet).
- The feedback rate, to choose `stale_ms` and `control_hz`.
- Whether command 15 is the current limit. pika_sdk sends it as `set_motor_torque` (a current), pika_ros as the current limit at startup.
- Whether it lets go of objects when disabled (`torque_off`).
- Whether it keeps its last target when commands stop while enabled (`check-hold`).
- The sign and size of the phase current (`currents_mA`): look at the values while gripping an object.
