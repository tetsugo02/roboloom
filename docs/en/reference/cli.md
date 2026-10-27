# CLI

Below, commands are abbreviated as `roboloom`. In a uv environment, prefix them with `uv run`. You can also check each command's arguments with `roboloom <command> --help`.

| Command | Purpose |
| --- | --- |
| `init rakuda2` | Generate the robot configuration |
| `probe <port>` | Read Dynamixel IDs, models, registers, and read times (a rough rate limit) |
| `validate <experiment>` | Validate the configuration and dataflow without opening devices |
| `calibrate-joints <calibration>` | Save measured counts at the URDF zero pose to the calibration |
| `measure-travel <calibration> --out <path>` | Save the range of motion moved by hand |
| `identify-gravity <calibration> --out <path> --collect --hardware` | Measure holding current and identify the gravity model |
| `capture-pose <experiment> <name> --hardware` | Save the follower's current pose as `poses/<name>.yaml` (moves nothing; `--force` replaces) |
| `commission <experiment> <node> --hardware` | Write EEPROM after a diff and operator confirmation, then read it back |
| `tune-gravity <experiment> leader <group> --hardware` | Interactively tune gain and hold |
| `gravity-check <experiment> leader <group> --hardware` | Measure the change in pose with and without compensation |
| `run <experiment> --hardware` | Collect data with the operation screen |
| `record <experiment> --task <text> --seconds <n> --hardware` | Collect fixed-duration episodes (`--episodes` sets the count; `--home` moves to the initial pose before each) |
| `infer <experiment> --seconds <n> --hardware` | Fixed-duration policy episodes; save only with `--task` |
| `session <experiment> <operation> [task]` | Send an operation to a running experiment |

`calibrate-joints` / `measure-travel` do not write to the bus, but they save local YAML. The arm torque must be off. `identify-gravity --collect`, `tune-gravity`, and `gravity-check` energize the motors. Do not open the same bus at the same time as the dataflow.

## run operations

| Input | Action |
| --- | --- |
| `start <task>` | Check readiness and start following and recording |
| `stop` | Stop following and recording (saving is a separate operation) |
| `save` | Save the episode |
| `discard` | Discard the episode |
| `release` | Stop following and release actuated inputs and followers after confirming support |
| `home` | Move the leader and follower slowly to the initial pose chosen in the controller; after arriving the leader returns to its normal laws |
| `estop` | Emergency stop |
| `quit` | Open the exit confirmation: Cancel, follower hold, or supported release |

The Textual operations menu shows unavailable actions with reasons, including `home` without a configured pose. Ctrl-L opens the editable command input; Ctrl-G requests emergency stop. Ctrl-C and Ctrl-Q open the same exit dialog, initially selecting Cancel. See [Operator screen](operator-screen.md) for keys, panes, confirmations, fixed-duration modes, and extension contracts.

`run --plain` retains line input; `record --plain` and `infer --plain` collect without key input. Non-TTY invocation selects these paths automatically. `tune-gravity` requires a TTY before device open. Python API Rich displays and prompts retain their existing behavior.
`stop` does not turn off torque. `FAULT` / `ESTOP` / `RELEASED` do not recover automatically. The start and shutdown procedure on hardware is in [Quick start](../quick-start/rakuda2.md). For details beyond the leader, such as the existing policy API, see [Python API](python-api.md).
