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

Because of `unknown`, the exit confirmation offers no "quit with followers holding" and names the arms as ones that may fall at the end. The values are explained in "Behaviour without torque and when left alone" in [Configuration](../reference/configuration.md).

## First steps on hardware

1. Ask an administrator to create the CAN interfaces (1 Mbps, one name per arm).
2. With the arm powered, check its state read-only. Nothing is enabled or moved.

    ```bash
    uv run roboloom probe can_left
    ```

    It shows the firmware, joint angles (rad and degrees), control mode, enabling, temperatures, faults and feedback rates.

3. Measure whether it holds when left alone. Be ready to support the arm and clear the space around it. It holds the current pose for 2 s, closes the bus with the motors enabled, and reads the joints for up to `--seconds`. A change beyond `--tolerance` (rad) or a disabled motor means `torque_off`; otherwise `holds`. Typing `record` writes `unattended:` to the follower YAML. Finally, choose `release` to turn the torque off, or leave it as it is.

    ```bash
    uv run roboloom check-hold left --tolerance 0.02
    ```

## To check on hardware

- Whether the joint signs and zeros match the SDK's description.
- Whether the arm holds when the bus is closed with the motors enabled (`check-hold`).
- How fast the loop runs on 1 Mbps CAN when every command is preceded by the control mode, to choose `control_hz`.
- The sign and size of the joint torque (`efforts_Nm`).
