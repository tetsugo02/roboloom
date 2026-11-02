# CLI

Below, commands are abbreviated as `roboloom`. In a uv environment, prefix them with `uv run`. You can also check each command's arguments with `roboloom <command> --help`.

## Choosing the configuration and devices

Each robot has one configuration (`.roboloom/<robot>/config.yaml`). `[robot]` in the table is optional: when `.roboloom/` holds a single robot, that one is used. A robot name (`rakuda2`) or a YAML file path also works. For commands that take other positional words, the first word is the configuration only when it names one (`roboloom commission follower` and `roboloom commission rakuda2 follower`, `roboloom session home` and `roboloom session rakuda2 home` are all valid).

Real hardware is the default. Commands that open devices accept:

| Flag | Meaning |
| --- | --- |
| `--with a,b` | Enable launch options (what they `requires` is enabled too; what `conflicts` is disabled) |
| `--without a,b` | Disable launch options (also ones with `default: true`; options requiring them are disabled too) |
| `--mock` | Use mock devices instead of the hardware |

`--hardware` has been removed; passing it is an error that suggests `--mock`. For how launch options are defined and the rules they follow, see "Launch options" in [Configuration](configuration.md).

## Commands

| Command | Purpose |
| --- | --- |
| `roboloom [robot]` | Open the launcher (same as `roboloom launch [robot]`) |
| `init rakuda2` | Generate the robot configuration |
| `probe <port>` | Read Dynamixel IDs, models, registers, and read times (a rough rate limit) |
| `validate [robot]` | Validate the configuration and dataflow without opening devices (prints the enabled options and the dataset name) |
| `calibrate-joints <calibration>` | Save measured counts at the URDF zero pose to the calibration |
| `measure-travel <calibration> --out <path>` | Save the range of motion moved by hand |
| `identify-gravity <calibration> --out <path> --collect` | Measure holding current and identify the gravity model (leader gravity compensation, the follower `model_residual` estimator); asks the operator before energizing |
| `capture-pose [robot] [follower] <name>` | Save a follower's current pose as `poses/<follower>/<name>.yaml` (moves nothing; `--force` replaces; `follower` may be omitted when there is one) |
| `commission [robot] <node>` | Write EEPROM after a diff and operator confirmation, then read it back |
| `watchdog-test [robot] <node> <joint>` | Bench test: check that the Bus Watchdog stops a current-mode motor (energizes it) |
| `tune-gravity [robot] leader <group> --with gravity` | Interactively tune gain and hold |
| `gravity-check [robot] leader <group> --with gravity` | Measure the change in pose with and without compensation |
| `run [robot]` | Collect data with the operation screen |
| `record [robot] --task <text> --seconds <n>` | Collect fixed-duration episodes (`--episodes` sets the count; `--home` moves to the initial pose before each) |
| `infer [robot] --seconds <n>` | Fixed-duration policy episodes; enables the option `policy` automatically; save only with `--task` |
| `session [robot] <operation> [task]` | Send an operation to a running `run` |

`probe`, `calibrate-joints`, `measure-travel`, `identify-gravity`, `commission`, `watchdog-test`, `tune-gravity` and `gravity-check` are for Dynamixel robots only; given a node that is not Dynamixel, they refuse and say why.

Examples:

```bash
uv run roboloom                                   # launcher
uv run roboloom run --with gravity                # start without the launcher
uv run roboloom run --mock                        # mock devices
uv run roboloom record --task "pick up the cup" --seconds 30 --home
uv run roboloom infer --seconds 20 --policy my_lab.policies:load
uv run roboloom validate --with digit
uv run roboloom session home
```

`calibrate-joints` / `measure-travel` do not write to the bus, but they save local YAML. The arm torque must be off. `identify-gravity --collect`, `tune-gravity`, and `gravity-check` energize the motors. Do not open the same bus at the same time as the dataflow. `commission`, `watchdog-test`, and `gravity-check` refuse a mock configuration.

## Launcher

Running `roboloom` in a terminal (or `roboloom launch`) first opens the robot list: the robots with a `.roboloom/<robot>/config.yaml`, each with its dataset name and default options. The cursor starts on the robot chosen last time; Enter selects, Esc exits without starting anything. The choice is kept in `.roboloom/logs/last_robot`. Naming the robot, as in `roboloom rakuda2`, skips the list and opens the next screen. In a terminal, `run`, `record`, and `infer` also open the launcher first unless `--with`, `--without`, or `--plain` is given; the command's arguments become its initial values.

- Choose the operation (`run` / `record` / `infer`). For `record` and `infer`, enter the task, seconds, and episodes; for `record`, also whether to move to the initial pose before every episode.
- Tick the options. Required options are enabled with them and conflicting options are disabled. Choosing `infer` turns on the option named `policy` when the configuration declares one.
- Choose whether to use mock devices.
- The summary shows the operation, mock or hardware, the enabled options, the dataset name, and the node files that are replaced.

Launch (Ctrl-S) starts; Cancel exits without starting anything. When opened from the robot list, Back (Esc) returns to the list; otherwise Esc is the same as Cancel. The previous choice is kept in `.roboloom/<robot>/logs/last_launch.yaml` and becomes the next initial value.

Options are never switched while the dataflow runs (they change control modes). To switch them, choose "Quit and choose options again (followers hold)" in the operator screen's exit dialog: it quits with the followers holding and returns to the launcher.

Before a hardware launch from a terminal, the CLI compares each Dynamixel node's EEPROM (Operating Mode, Current Limit) with the chosen options. If they differ, it prints the differences and writes them after the operator confirms (the same procedure as `roboloom commission`). For example, turning `gravity` on or off changes the leader's Operating Mode.

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
| `quit` | Open the exit confirmation: Cancel, follower hold, choose options again, or supported release |

The Textual operations menu shows unavailable actions with reasons, including `home` without a configured pose. Ctrl-L opens the editable command input; Ctrl-G requests emergency stop. Ctrl-C and Ctrl-Q open the same exit dialog, initially selecting Cancel. See [Operator screen](operator-screen.md) for keys, panes, confirmations, fixed-duration modes, and extension contracts.

`run --plain` retains line input; `record --plain` and `infer --plain` collect without key input. Non-TTY invocation selects these paths automatically (no launcher). `tune-gravity` requires a TTY before device open. Python API Rich displays and prompts retain their existing behavior.
`stop` does not turn off torque. `FAULT` / `ESTOP` / `RELEASED` do not recover automatically. The start and shutdown procedure on hardware is in [Quick start](../quick-start/rakuda2.md). For details beyond the leader, such as the existing policy API, see [Python API](python-api.md).
