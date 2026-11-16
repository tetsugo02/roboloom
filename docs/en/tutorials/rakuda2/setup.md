# Rakuda2: configuration and read check

<span class="status status--verified">Hardware-verified</span>

- **Goal**: create `.roboloom/rakuda2/`, read the leader and the follower, and go once through the collection path with the follower's torque off.
- **Prerequisites**: [Installation](../../get-started/installation.md) is done; Rakuda2, the Rakuda-mini leader and the RealSense are connected.
- **Time**: 1–2 hours (including checking ports and values).
- **Result**: `validate` passes, every node runs in the `run` screen, and you can save or discard an episode.

This assumes you have added roboloom and the robot/hardware-collection extras (`rakuda2` / `record` / `hardware` / `digit`) to your own uv project following [Installation](../../get-started/installation.md). Commands and configuration paths are relative to your project root. For supported devices and configurations, see [Rakuda2](../../robots/rakuda2/index.md).

## 1. Robot configuration and read check

```bash
uv run roboloom init rakuda2
ls /dev/serial/by-id/
```

If `.roboloom/rakuda2/` already exists, `init` does not overwrite it. Review the existing robot configuration and use it. To bring a project up to a newer template, run `roboloom init rakuda2 --update`: it adds the files the project lacks and replaces files that are still as they were copied. Files you edited and files holding measured values are left alone; for those it lists the keys and options only the template has, to copy by hand.

Identify the leader / follower U2D2 ports and read them while no other process is using them. Replace the `<...>` below with the actual ports.

```bash
uv run roboloom probe /dev/serial/by-id/<follower-U2D2>
uv run roboloom probe /dev/serial/by-id/<leader-U2D2>
```

| File (in `.roboloom/rakuda2/`) | What to set and check |
| --- | --- |
| `nodes/follower.yaml` | Follower `port`, IDs and models, `registers`, measured safe `limits`, velocity, current, and temperature limits |
| `nodes/leader.yaml`, `nodes/leader_gravity.yaml` | Leader `port`, IDs and models, `registers`, control law |
| `nodes/camera.yaml` | RealSense `serial` |
| `nodes/digit_left.yaml`, `nodes/digit_right.yaml` | Left and right DIGIT `serial` |
| `calibration/leader_right.yaml`, `calibration/leader_left.yaml` | Leader `port`, joint-to-URDF mapping, zero points, directions |

`config.yaml` is the robot's configuration; gravity compensation, DIGIT, force feedback, policy execution and other features are launch options in it (see [Configuration](../../reference/configuration/index.md)). The node files for each option are kept separately under `nodes/`.

Apply values such as each joint's `homing_offset` from the `probe` results to the configuration. Gravity compensation deliberately changes the operating mode and Current Limit, so do not copy the current EEPROM as-is; check the difference from the configuration with `commission`, described below.

Template values are not a safety guarantee for your robot. In particular, the follower's `limits.min/max` are wide initial values. Narrow them to the measured safe range, and verify the stop and torque-off methods on each robot unit. Even with the standard leader, the trigger is powered.

For the first path check, **change `torque: true` to `torque: false` in `nodes/follower.yaml`**. Support the arms while the follower torque is off. This setting does not cut power on the leader side.

## 2. Check the collection path with the standard leader

With no option enabled, the configuration uses only the standard leader and the RealSense. It does not reference DIGIT unless the option `digit` is enabled, even if DIGIT is not connected yet.

```bash
uv run roboloom validate
```

If `SET_...` remains in a referenced configuration, its location is shown. Fill it in and validate again. To try the flow before connecting the hardware, `uv run roboloom validate rakuda2 --mock` and `uv run roboloom run rakuda2 --mock` work without filling anything. `validate` does not open devices, so the hardware EEPROM and stop behavior must be checked separately.

If the EEPROM differs from the intended configuration, stop the dataflow and run `commission` while supporting both arms. Review the displayed changes before approving. This operation writes the EEPROM and reads it back.

```bash
uv run roboloom commission follower
uv run roboloom commission leader
uv run roboloom run
```

In a terminal, `run` first opens the [launcher](../../reference/cli.md). Choose the operation `run`, leave every option unticked, and press Launch (Ctrl-S). To start without the launcher, use `uv run roboloom run --plain` (a line-input screen).

IDs, models, and EEPROM are also checked at startup, and startup is refused on a mismatch. Check the status of all nodes and the sensor acquisition rates on the screen. Align the leader to the follower's pose, and once the controller is `following`, enter the following in order.

```text
start pipeline check
stop
save
release
quit
```

At the `release` confirmation, support the follower arms. `quit` also releases the leader's torque, so support the leader arms as well before exiting. At the `quit` confirmation, select follower Hold or supported Release; Cancel is initially selected. At this stage, keep the follower at `torque: false` and check the observation and recording path.

## Next

- To use gravity compensation: [Rakuda2: gravity compensation](gravity.md)
- To collect right away: [Rakuda2: teleoperated collection](collect.md)
