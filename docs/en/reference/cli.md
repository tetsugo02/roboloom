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
| `commission <experiment> <node> --hardware` | Write EEPROM after a diff and operator confirmation, then read it back |
| `tune-gravity <experiment> leader <group> --hardware` | Interactively tune gain and hold |
| `gravity-check <experiment> leader <group> --hardware` | Measure the change in pose with and without compensation |
| `run <experiment> --hardware` | Collect data with the operation screen |
| `record <experiment> --task <text> --seconds <n> --hardware` | Collect fixed-duration episodes (`--episodes` sets the count) |
| `session <experiment> <operation> [task]` | Send an operation to a running experiment |

`calibrate-joints` / `measure-travel` do not write to the bus, but they save local YAML. The arm torque must be off. `identify-gravity --collect`, `tune-gravity`, and `gravity-check` energize the motors. Do not open the same bus at the same time as the dataflow.

## run operations

| Input | Action |
| --- | --- |
| `start <task>` | Check readiness and start following and recording |
| `stop` | Stop following and recording (saving is a separate operation) |
| `save` | Save the episode |
| `discard` | Discard the episode |
| `release` | Turn off the torque of a follower in HOLD, after confirming the arms are supported |
| `estop` | Emergency stop |
| `quit` | Exit the dataflow after confirming the arms are supported. Enter also releases the follower; `hold` keeps it holding |

`stop` does not turn off torque. `FAULT` / `ESTOP` / `RELEASED` do not recover automatically. The start and shutdown procedure on hardware is in [Quick start](../quick-start/rakuda2.md). For details beyond the leader, such as the existing policy API, see [Python API](python-api.md).
