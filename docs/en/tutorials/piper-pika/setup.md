# PiPER + Pika: robot setup

!!! warning "Status: in development"
    <span class="status status--dev">In development</span> `roboloom setup` is checked only by tests with fake hardware. It has not run on hardware. If a step fails, report it with that step's output.

- **Goal**: create `.roboloom/piper-pika/`, find with `roboloom setup` which CAN interface, serial port and tracker is which device, write them in, and check by reading.
- **Prerequisites**: [Installation](../../get-started/installation.md) is done. Two PiPER arms, two Pika Grippers, two Pika Senses and the base stations (Lighthouse) are wired and powered. The arms are in the folded rest pose with the motors disabled (as right after power-on).
- **Time**: 30 minutes (not counting the administrator's work).
- **Result**: `roboloom validate piper-pika` passes. No device is enabled or moved.

## 0. What to ask an administrator

This work needs root. roboloom does not call sudo.

- Permission to open serial ports (the `dialout` group).
- The udev rules for Vive trackers (libsurvive's `81-vive.rules`).
- Bringing the CAN interfaces up at 1 Mbps. The names do not need to be chosen (`can0` and `can1` are fine). roboloom tells the arms apart by the serial number of the USB-CAN adapter.

## 1. Create the configuration

```bash
uv add git+https://github.com/tetsugo02/roboloom.git --tag v0.2.1 --extra piper --extra pika --extra record
uv run roboloom init piper-pika
uv run roboloom validate piper-pika --mock   # check that the configuration loads without hardware
```

`.roboloom/piper-pika/` gets a node file for each arm, Gripper and Sense. The device identifiers (CAN adapter serials, serial ports, tracker serials) are left as `SET_`.

## 2. Identify the devices

```bash
uv run roboloom setup piper-pika
```

Following the prompts, move each device by hand in turn. When exactly one thing changed, it is written as that device. When none or more than one changed, you are asked again.

| Step | What it checks | What you are asked to do |
| --- | --- | --- |
| `check` | extras, serial port permissions, the Vive udev rules | Nothing |
| `can` | CAN interface state, bitrate, adapter serial | If an interface is not up, have an administrator run the displayed commands, then press Enter |
| `arms` | Which CAN is which arm | Turn joint1 (the base) of the named arm about 20° by hand and back, then press Enter |
| `senses` | Which port is which Sense | Open and close the named Sense a few times, then press Enter |
| `trackers` | Which tracker (`LHR-…`) is in which Sense | Move the named Sense about 30 cm (keep the others still), then press Enter |
| `grippers` | Which port is which Gripper | Unplug the named Gripper's USB and press Enter, plug it back into the same port and press Enter |
| `validate` | Whether the configuration loads for hardware | Nothing |

- **An arm with its motors enabled is refused.** A PiPER drops when disabled, so setup does not disable it. Support the arm and release it at the end of `check-hold`, or power-cycle it in the rest pose, then run setup again.
- **When a tracker is not seen**, setup offers a base-station calibration (libsurvive's `--force-calibrate`). Place both Senses still where both base stations can see them, then answer `yes`. The result is kept in libsurvive's configuration (`~/.config/libsurvive/`), so this is needed only once.
- **Grippers cannot be turned by hand**, so they are identified by unplugging and replugging their USB (the same approach as LeRobot's `lerobot-find-port`). The port name depends on the USB socket, so plug it back into the same socket.
- The last device is assigned without asking when only one candidate is left.

Written lines get `# roboloom setup <date>`. Other lines and comments in the file are not changed.

```yaml
# nodes/left.yaml (excerpt)
can: {serial: "0029002F5746570A20383839"}  # roboloom setup 2026-11-17
# nodes/left_sense.yaml (excerpt)
port: /dev/serial/by-path/pci-0000:00:14.0-usb-0:3.4:1.0-port0  # roboloom setup 2026-11-17
tracker: {system: lighthouse, serial: "LHR-F7BA2042"}  # roboloom setup 2026-11-17
```

### Redoing only part of it

```bash
uv run roboloom setup piper-pika --step grippers        # Grippers only
uv run roboloom setup piper-pika --step can,arms        # CAN and arms
```

Values already set are shown first. Enter keeps them, and `r` identifies the device again. Use this to check after replacing a cable or a device.

## 3. Check by reading

```bash
uv run roboloom validate piper-pika
uv run roboloom probe can0          # arm (the CAN name is shown in setup's can step)
uv run roboloom probe /dev/serial/by-path/<Gripper-port> --device pika
uv run roboloom probe /dev/serial/by-path/<Sense-port> --device pika_sense
```

- `validate` prints a `note:` for IK nodes without a `workspace`. That is fine the first time (it is added in [Tightening the configuration](tighten.md)).
- In the rest pose, joint2 is slightly negative and joint3 slightly positive, and they can be outside `limits` (joint2 ≥ 0, joint3 ≤ 0). They come back inside the range when the arm moves home, so leave them as they are.
- When a closed Gripper's angle is below 0 (for example, −0.015 rad), setup reports it with a `note:`. roboloom does not yet write the zero point (pika_sdk's `set_zero`). A small offset is fine to proceed with.

## Next

[First teleoperation](first-teleop.md): check holding, move home, and teleoperate with a loose configuration.
