# Rakuda2: teleoperated collection

<span class="status status--verified">Hardware-verified</span>

- **Goal**: drive the follower with the leader and save episodes with the RealSense (and DIGIT) to a LeRobotDataset.
- **Prerequisites**: [Rakuda2: configuration and read check](setup.md) is done; for gravity compensation, [Rakuda2: gravity compensation](gravity.md) too.
- **Time**: 30 minutes or more.
- **Result**: episodes are saved in `.roboloom/rakuda2/datasets/rakuda2` (`rakuda2-digit` with `digit`).

## 1. Prepare

Before collecting, optionally configure [leader joint locking and torso-yaw compensation](../../controllers/leader.md). Edit `control` in the active `leader*.yaml` and `couplings` in `controller.yaml`. Align the leader joints to be locked with the follower before launch. These settings work with both standard and gravity-compensated configurations, but the combination has not been tested on hardware.

With only `gravity` enabled, the configuration records **RealSense only**. To also record DIGIT, enable the option `digit` as well (`--with gravity,digit`); the save location is separated automatically as `rakuda2-digit`. For the supported combinations and limitations, see [Rakuda2](../../robots/rakuda2/index.md).

Before moving the follower, verify the robot's safe range, low-speed following, stop, and torque off, then change `nodes/follower.yaml` to `torque: true`. Support both arms, and start after completing the EEPROM check with the dataflow stopped.

## 2. Start and collect

```bash
uv run roboloom validate --with gravity
uv run roboloom run --with gravity
```

With `--with`, the launcher is not opened. To start from the launcher, run `uv run roboloom`, choose `rakuda2` in the robot list, and tick `gravity`.

1. Check the robot status, sensor acquisition rates, and recorder. If an initial pose ([home](../../controllers/leader.md)) is configured, `home` moves both arms there before you start.
2. Align the leader to the follower and confirm the controller is `following`. While an `aligning` warning is shown, match the pose and retry starting.
3. Start following and recording with `start pick up the cup`, and operate with the leader.
4. Stop with `stop`. `stop` holds the follower and does not turn off torque.
5. Accept the episode with `save`, or drop it with `discard`. Check the completed result's warnings for missing-data rate, valid-command rate, and control period in Logs.
6. Collect another episode with the next `start <task>`.
7. To finish, do `stop` → save or discard → support the leader and follower arms and `quit`, then explicitly select supported Release or follower Hold in the confirmation. Cancel is selected initially; Enter alone cancels.

`estop` on a fault is latched and does not recover automatically. Operate with physical support and stop means available.

## 3. Collect episodes of a fixed length

Fixed-duration collection can also be done with the following. After the controller is ready, follow the on-screen instructions and press Enter to start.

```bash
uv run roboloom record --task "pick up the cup" --seconds 30 --episodes 3 --with gravity
```

The same dataflow can be used from Python.

<span class="status status--mock">Mock only</span> With [background saving](../../data/recording.md#background-saving), the episode is queued by default. To read its saved index, wait for the final result.

```python
from roboloom import Session

with Session.launch("rakuda2", options=["gravity"]) as session:
    session.wait_ready()
    result = session.record("pick up the cup", seconds=30)
    if result.pending:
        (result,) = session.wait_saves()
    print(result.index, result.frames, result.warnings)
```

The arms must be supported when the script ends as well. To build in manual stop and release, see [Python API](../../reference/python-api/session.md).

## 4. Where it is saved

With only `gravity` enabled, the save location is `.roboloom/rakuda2/datasets/rakuda2` (`output` is relative to the configuration YAML); with `digit` it becomes `datasets/rakuda2-digit`. Logs are kept in `.roboloom/rakuda2/logs/<dataset name>-<time>/`. Keep the configuration, calibration, and tuning YAMLs under management, and you can resume collection into a dataset with the same configuration, FPS, and features.

Interactive CLI commands use the [Textual operator screen](../../reference/operator-screen.md): Ctrl-L for command input, Ctrl-N for panes, Ctrl-G for emergency stop, Ctrl-C/Ctrl-Q for exit confirmation. `record --plain` and non-TTY runs start without an Enter prompt. Python API displays remain input-free Rich views.

## Next

- Check the recording, train a policy and run it: [Rakuda2: from collection to inference](train-infer.md)
- Dataset columns and missing data: [Dataset format](../../data/format.md)
