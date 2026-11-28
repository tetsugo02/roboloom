# CLI

The `roboloom` commands. In a uv environment, prefix them with `uv run`. `roboloom --version` (`-V`) prints the version, and `roboloom <command> --help` lists each command's arguments. The CLI is a thin layer that calls the [Python API](python-api/index.md) and prints the result.

## Choosing the configuration and devices { #choosing-the-configuration }

Each robot has one configuration (`.roboloom/<robot>/config.yaml`). `[robot]` in a synopsis is optional: when `.roboloom/` holds a single robot, that one is used. A robot name (`rakuda2`) or a YAML file path also works. For commands that take other positional words, the first word is the configuration only when it names one (`roboloom commission follower` and `roboloom commission rakuda2 follower`, `roboloom session home` and `roboloom session rakuda2 home` are all valid).

### Common options { #common-options }

Real hardware is the default. Most commands that read the configuration accept these (the commands whose table lists "Common options"):

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `--with A,B` | list of names | — | Enable launch options (what they `requires` is enabled too; what `conflicts` is disabled) |
| `--without A,B` | list of names | — | Disable launch options (also ones with `default: true`; options requiring them are disabled too) |
| `--mock` | flag | off | Use mock devices instead of the hardware |
| `--video-codec CODEC` | `av1`, `libsvtav1`, `h264` | the recorder YAML | Codec of `storage: video` images (omitted: the recorder YAML; when appending, the saved videos' codec; H.264 when neither says; [Video codec](configuration/recorder.md#video-codec)) |
| `--experiment NAME` | name or path | — | An experiment file (`configs/roboloom/<NAME>.yaml` of the project, or a file path). It gives the robot, the options, what the nodes are given (the policy) and the dataset, and for `record` and `infer` the task, length, episodes, home, and save confirmation. Values on the command line win ([experiment files](configuration/index.md#experiments)) |
| `--sensors A,B` | list of names | the configuration's defaults | Sensors to start and record (`""` selects none; [sensor selection](#sensor-selection)) |
| `--observe A,B` | list of names | the policy YAML's `observe` | Sensors the policy observes (`""` selects none) |

`--hardware` has been removed; passing it is an error that suggests `--mock`. For how launch options are defined and the rules they follow, see [Launch options](configuration/index.md#launch-options).

## Launcher { #launcher }

Running `roboloom` in a terminal (or `roboloom launch`) first opens the robot list: the robots with a `.roboloom/<robot>/config.yaml`, each with its dataset name and default options. In a terminal, `run`, `record`, and `infer` also open the launcher first unless `--with`, `--without`, `--experiment`, or `--plain` is given; the command's arguments become its initial values. For the screens and keys, see [the launcher](operator-screen.md#launcher) on the operator screen page.

Before a hardware launch from a terminal, the CLI compares each Dynamixel node's EEPROM (Operating Mode, Current Limit) with the chosen options. If they differ, it prints the differences and writes them after the operator confirms (the same procedure as [`roboloom commission`](#commission)). For example, turning `gravity` on or off changes the leader's Operating Mode.

## run operations { #run-operations }

A running `run` takes these operations from the operator screen or from [`roboloom session`](#session).

| Input | Action |
| --- | --- |
| `start <task>` | Check readiness and start following and recording |
| `stop` | Stop following and recording (saving is a separate operation) |
| `save` | Save the stopped episode. By default, acknowledge when queued. [Background saving](../data/recording.md#background-saving) <span class="status status--mock">Mock only</span> |
| `discard` | Discard the episode |
| `teleop` | Drive the followers with operator input. See [teleop outside an episode](../controllers/index.md#teleop) (<span class="status status--mock">Mock only</span>) and [teleoperation and interventions](../policy/intervention.md#teleop) for availability. |
| `stop_teleop` | End teleop and hold the followers outside an episode. See [teleop outside an episode](../controllers/index.md#teleop) (<span class="status status--mock">Mock only</span>) and [teleoperation and interventions](../policy/intervention.md#teleop). |
| `release` | Stop following and release actuated inputs and followers after confirming support |
| `home [NAME]` | Move slowly to the configured default poses or the named pose. An actuated leader moves with its follower and returns to its normal laws after arrival |
| `estop` | Emergency stop |
| `quit` | Open the exit confirmation: Cancel, follower hold, choose options again, or supported release |

Textual shows state-specific action buttons and explains refusals. Ctrl-L opens the editable command input; Ctrl-G requests emergency stop. Ctrl-C and Ctrl-Q open the same exit dialog, initially selecting Cancel. See [Operator screen](operator-screen.md) for keys, panes, confirmations, fixed-duration modes, and extension contracts.

`run --plain` retains line input; `record --plain` and `infer --plain` start episodes automatically. Non-TTY invocation follows the same path. The `--confirm` prompt requires a TTY on stdin. `tune-gravity` requires a TTY before device open. Python API Rich displays and prompts retain their existing behavior.
`stop` does not turn off torque. `FAULT` / `ESTOP` / `RELEASED` do not recover automatically. The start and shutdown procedure on hardware is in [Rakuda2: teleoperated collection](../tutorials/rakuda2/collect.md).

## Sensor selection { #sensor-selection }

`--sensors camera,audio --observe camera` selects the sensors to start and record independently from the sensors the policy observes; `--sensors "" --observe ""` selects none. The launcher provides separate sensor and observation checkboxes and remembers selections. The rules are in [Sensor selection](configuration/sensors.md#sensor-selection); selecting from Python is shown in [Session](python-api/session.md#sensor-selection).

## Commands { #commands }

| Command | Purpose |
| --- | --- |
| [`launch`](#launch) | Open the launcher (same as `roboloom [robot]`) |
| [`init`](#init) | Generate the robot configuration |
| [`skills`](#skills) | Install or check the Agent Skill for coding agents |
| [`validate`](#validate) | Validate the configuration and dataflow without opening devices |
| [`run`](#run) | Collect with the operator screen |
| [`record`](#record) | Collect episodes of a fixed length |
| [`infer`](#infer) | Run episodes with a policy |
| [`session`](#session) | Send an operation to a running `run` |
| [`serve-policy`](#serve-policy) | Serve a policy from another process |
| [`check-dataset`](#check-dataset) | Check a recorded dataset |
| [`label`](#label) | Give a saved episode its evaluation verdict |
| [`convert-handheld`](#convert-handheld) | Turn a hand-held recording into a training dataset |
| [`setup`](#setup) | Find which device is which node and write it to the configuration (PiPER, Pika) |
| [`probe`](#probe) | Inspect a bus or device read-only |
| [`calibrate-joints`](#calibrate-joints) | Save the measured counts at the URDF zero pose |
| [`measure-travel`](#measure-travel) | Save the range of motion moved by hand |
| [`identify-gravity`](#identify-gravity) | Identify the gravity model |
| [`capture-pose`](#capture-pose) | Save a follower's current pose |
| [`commission`](#commission) | Bring the EEPROM in line with the configuration |
| [`watchdog-test`](#watchdog-test) | Bench test: the Bus Watchdog |
| [`check-hold`](#check-hold) | Bench test: does a follower keep its pose once commands stop |
| [`tune-gravity`](#tune-gravity) | Tune gravity compensation interactively |
| [`gravity-check`](#gravity-check) | Measure the change in pose with and without compensation |

`calibrate-joints`, `measure-travel`, `identify-gravity`, `commission`, `watchdog-test`, `tune-gravity` and `gravity-check` are for Dynamixel robots only (`probe` reads Dynamixel, PiPER, Pika Gripper and Pika Sense); given a node that is not Dynamixel, they refuse and say why. `commission`, `watchdog-test`, `check-hold`, and `gravity-check` refuse a mock configuration.

A bus is opened by one process at a time: opening the bus a dataflow uses with `probe` or `tune-gravity` (or the other way round) stops the second one with `... is in use by another process`.

## roboloom launch { #launch }

Open the launcher, choose the operation (`run`, `record`, `infer`) and the options, then start ([Launcher](#launcher)).

```text
roboloom [robot] [COMMON_OPTIONS]
roboloom launch [robot] [COMMON_OPTIONS]
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `robot` | robot name or path | the only robot | Given, the robot list is skipped and the next screen opens |
| Common options | — | — | [Common options](#common-options); they become the launcher's initial values |

```bash
uv run roboloom                                   # launcher
```

## roboloom init { #init }

Generate the robot configuration (`.roboloom/<robot>/`) from a template (the shipped templates are `rakuda2` and `piper-pika`).

```text
roboloom init <robot> [--root DIR] [--template PACKAGE_OR_DIR] [--update]
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `robot` | str | required | Robot name; the project is named after it |
| `--root DIR` | path | `.roboloom` | Parent directory of the project |
| `--template PACKAGE_OR_DIR` | package or path | the shipped template | Make it from a template roboloom does not ship: a package holding `template/` (`my_lab.robots.arm`) or a directory ([From your own package](../contribution/index.md#own-types)) |
| `--update` | flag | off | Bring an existing project up to the installed template: add missing files, replace files still as they were copied, and leave edited and measured files alone, listing the keys and options only the template has |

```bash
uv run roboloom init rakuda2
```

## roboloom skills { #skills }

Copy the Agent Skill for coding agents into your project's `.agents/skills/` and `.claude/skills/` (`install`), check that the copies match this version (`check`; exit status 1 otherwise), or print where the packaged skill is (`path`). Opens no device ("Use with coding agents" in [Installation](../get-started/installation.md)).

```text
roboloom skills install|check|path [--agent all|agents|claude] [--root DIR] [--force]
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `action` | `install`, `check`, `path` | required | What to do |
| `--agent` | `all`, `agents`, `claude` | `all` | Which agents' skills directory (`agents`: `.agents/skills`, `claude`: `.claude/skills`) |
| `--root DIR` | path | `.` | The project root |
| `--force` | flag | off | Replace a copy that differs |

```bash
uv run roboloom skills install
```

## roboloom validate { #validate }

Validate the configuration and dataflow without opening devices. Prints the enabled options, the dataset name and the video codec.

```text
roboloom validate [robot] [COMMON_OPTIONS]
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `robot` | robot name or path | the only robot | The configuration to validate |
| Common options | — | — | [Common options](#common-options) (including `--experiment`) |

```bash
uv run roboloom validate --with digit
```

## roboloom run { #run }

Start the dataflow and keep collecting with the operator screen ([run operations](#run-operations)).

```text
roboloom run [robot] [--plain] [COMMON_OPTIONS]
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `robot` | robot name or path | the only robot | The configuration to start |
| `--plain` | flag | off | A line-by-line prompt instead of the fixed screen (no launcher either) |
| Common options | — | — | [Common options](#common-options) |

```bash
uv run roboloom run --with gravity                # start without the launcher
uv run roboloom run --mock                        # mock devices
```

## roboloom record { #record }

Collect episodes of a fixed length, then exit. Select Start for each episode once ready ([Operator screen](operator-screen.md#operations)).

<span class="status status--mock">Mock only</span> With [background saving](../data/recording.md#background-saving), `--plain` waits for queued saves after the last episode and prints the saved results. The operator screen logs results as they arrive and waits for the queue on confirmed exit.

```text
roboloom record [robot] --task TEXT --seconds N [--episodes N] [--home [NAME]] [--confirm] [--plain] [COMMON_OPTIONS]
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `robot` | robot name or path | the only robot | The configuration to start |
| `--task TEXT` | str | required (or `task:` in the experiment file) | Task text stored with every frame |
| `--seconds N` | float | required (or `seconds:` in the experiment file) | Length of an episode, in seconds |
| `--episodes N` | int | 1 | Number of episodes |
| `--home [NAME]` | flag or pose name | off | Move to the controllers' default poses or the named pose before every episode |
| `--confirm` | flag | off | Ask whether to save or discard after each episode. In plain mode, stdin must be a TTY. Answer `save`, `save success`, `save failure`, or `discard` (`s` and `d` also work). Discard repeats the episode number. EOF or Ctrl-C discards it and ends the run. <span class="status status--mock">Mock only</span> |
| `--plain` | flag | off | Start episodes automatically without the operator screen |
| Common options | — | — | [Common options](#common-options) |

When the experiment file gives `steps:`, pass `--seconds` (steps count a policy's actions and do not apply to `record`).

```bash
uv run roboloom record --task "pick up the cup" --seconds 30 --home
```

## roboloom infer { #infer }

Run episodes with a policy. Enables the option `policy` automatically. Saving requires a task from `--task` or the experiment file ([Running a policy](../policy/run.md)).

```text
roboloom infer [robot] (--seconds N | --steps N) [--episodes N] [--home [NAME]] [--confirm] [--policy MODULE:CALLABLE] [--policy-kwargs JSON] [--task TEXT] [--plain] [COMMON_OPTIONS]
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `robot` | robot name or path | the only robot | The configuration to start |
| `--seconds N` | float | this or `--steps` is required (or the experiment file) | Length of an episode, in seconds |
| `--steps N` | int | — | End each episode after this many actions of the policy (at least 1; not together with `--seconds`) |
| `--episodes N` | int | 1 | Number of episodes |
| `--home [NAME]` | flag or pose name | off | Move to the policy's default poses or the named pose before every episode ([policy home](../policy/run.md#home)) |
| `--policy MODULE:CALLABLE` | str | the YAML's `factory` | The callable returning the policy |
| `--policy-kwargs JSON` | JSON | the YAML's `kwargs` | Its arguments |
| `--task TEXT` | str | — | Task given to the policy; with it, runs are saved |
| `--confirm` | flag | off | Same prompt as [`record --confirm`](#record). Requires a task from `--task` or the experiment file. <span class="status status--mock">Mock only</span> |
| `--plain` | flag | off | Start episodes automatically without the operator screen |
| Common options | — | — | [Common options](#common-options) |

```bash
uv run roboloom infer --seconds 20 --policy my_lab.policies:load
uv run roboloom infer --experiment drawer         # configs/roboloom/drawer.yaml
```

## roboloom session { #session }

Send one operation to a running `run`.

```text
roboloom session [robot] <operation> [argument]
roboloom session [robot] home [NAME]
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `robot` | robot name or path | the only robot | The configuration of the running `run` (whatever its options) |
| `operation` | one of below | required | `start`, `stop`, `save`, `discard`, `home`, `estop`, `release`, `quit`; with `teleop:` in the policy also `teleop`, `policy`, `stop_teleop` ([teleoperation and interventions](../policy/intervention.md#teleop)). When every controller follows operator input, `teleop` and `stop_teleop` are available for [teleop outside an episode](../controllers/index.md#teleop) without recording. <span class="status status--mock">Mock only</span> |
| `argument` | str | — | Task for `start`, verdict (`success` or `failure`) for `save`, pose name for `home`. Omit `NAME` to use each controller's configured default |

```bash
uv run roboloom session home
uv run roboloom session home ready
uv run roboloom session save success
```

## roboloom serve-policy { #serve-policy }

<span class="status status--mock">Mock only</span>

Serve a policy from this environment to a policy node with `backend: server` ([another process](../policy/remote.md#running-the-policy-in-another-process)). Reads no robot configuration.

```text
roboloom serve-policy (<module:callable> | --from POLICY_YAML | --experiment EXPERIMENT_YAML) [--kwargs JSON] [--address HOST:PORT] [--authkey-env NAME]
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `policy` | `module:callable` | — | The callable returning the policy (exactly one of this, `--from`, `--experiment`) |
| `--from POLICY_YAML` | path | — | Use the `factory`, `kwargs` and `server.address` of this policy node file (e.g. `.roboloom/<robot>/nodes/policy.yaml`) |
| `--experiment EXPERIMENT_YAML` | path | — | Use the `factory`, `kwargs` and `server.address` this experiment file (e.g. `configs/roboloom/<name>.yaml`) gives the policy |
| `--kwargs JSON` | JSON | the file's `kwargs` | Arguments of the callable (replace the file's) |
| `--address HOST:PORT` | str | the file's `server.address`, else `127.0.0.1:18765` | Where to listen |
| `--authkey-env NAME` | str | the file's `server.authkey_env`, else `ROBOLOOM_POLICY_AUTHKEY` | Environment variable holding the shared secret |

```bash
uv run roboloom serve-policy --from .roboloom/rakuda2/nodes/policy.yaml
```

## roboloom check-dataset { #check-dataset }

Check a recorded dataset by reading it only: episode counts against the files, video length against the rows, the share of rows whose `valid` is 0, the count of verdicts. Exit code 1 when something is wrong ([Checking the data](../data/check-and-train.md)).

<span class="status status--mock">Mock only</span> The `episode spool:` note reports ready and unfinished [spool episodes](../data/recording.md#background-saving).

```text
roboloom check-dataset [robot | DATASET_DIR] [--recover] [COMMON_OPTIONS]
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `robot` | robot name or path, or a dataset directory | the only robot's dataset | The dataset to check; select a dataset whose name an option changes with `--with` |
| `--recover` | flag | off | Roll back an interrupted dataset write before checking ([Saved episodes](../data/recording.md#saved-episodes)) |
| Common options | — | — | [Common options](#common-options) (`--with`, `--without` and `--experiment` decide the dataset name) |

```bash
uv run roboloom check-dataset --with digit
```

## roboloom label { #label }

Give a saved episode its evaluation verdict, or change it. Appends to the dataset's `meta/roboloom_episodes.jsonl` and prints the count of verdicts ([Episode records](../data/recording.md#episode-records)).

```text
roboloom label [robot | DATASET_DIR] <episode> success|failure [--note TEXT] [COMMON_OPTIONS]
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `robot` | robot name or path, or a dataset directory | the only robot's dataset | The dataset; select a dataset whose name an option changes with `--with` |
| `episode` | int | required | The episode's index in the dataset |
| `verdict` | `success`, `failure` | required | The verdict |
| `--note TEXT` | str | — | Free text kept with the verdict |
| Common options | — | — | [Common options](#common-options) (`--with`, `--without` and `--experiment` decide the dataset name) |

```bash
uv run roboloom label --with policy 3 failure     # episode 3 of the evaluation dataset
```

## roboloom convert-handheld { #convert-handheld }

<span class="status status--dev">In development</span>

Turn a hand-held recording (a configuration without followers) into a training dataset whose actions are relative poses ([Hand-held collection](../tutorials/pika-handheld.md)).

```text
roboloom convert-handheld [robot] [--action delta|relative-chunk] [--horizon N] [--hands A,B] [--max-gap N] [--output DIR] [--repo-id ID]
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `robot` | robot name or path | the only robot | The configuration that recorded (its dataset is read) |
| `--action` | `delta`, `relative-chunk` | `delta` | `delta`: one step `inv(P[t]) P[t+1]`; `relative-chunk`: `inv(P[t]) P[t+k]`, k=1..horizon, in one row (train with chunk_size 1) |
| `--horizon N` | int | 16 | Steps of `relative-chunk` |
| `--hands A,B` | list of names | every pose | The pose inputs to convert |
| `--max-gap N` | int | 3 | Untracked rows filled per gap |
| `--output DIR` | path | `<output>-<action>` of the recording | Where to write |
| `--repo-id ID` | str | `<repo_id>-<action>` | Repo id of the result |

```bash
uv run roboloom convert-handheld --action relative-chunk --horizon 16
```

## roboloom setup { #setup }

<span class="status status--dev">In development</span> Find which CAN interface, serial port and tracker is which PiPER, Pika Gripper and Pika Sense in the configuration, and write them to the node files. Devices are only read: nothing is enabled, moved, or zeroed. The steps are in [PiPER + Pika: robot setup](../tutorials/piper-pika/setup.md).

```text
roboloom setup [robot] [--step check,can,arms,senses,trackers,grippers,validate]
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `robot` | str | the only one in `.roboloom/` | Robot configuration |
| `--step A,B` | list of steps | all (in this order) | Steps to run |

- Arms are found by turning the named arm's joint1 by hand, Senses by opening and closing them, trackers by moving the Sense, and Grippers by unplugging and replugging their USB. A device is assigned only when exactly one thing changed.
- Values already set are shown first; Enter keeps them and `r` finds the device again.
- When a CAN interface is not up, the `sudo ip link ...` commands to run are shown (not run).
- It stops if any PiPER has its motors enabled (disabling makes the arm drop, so setup does not disable it).

```bash
uv run roboloom setup piper-pika
uv run roboloom setup piper-pika --step grippers
```

## roboloom probe { #probe }

Inspect a Dynamixel bus read-only: IDs, models, registers, and read times (a rough rate limit). Given a CAN interface such as `can0` (a name without `/`), read the PiPER ([in development](../robots/piper/index.md)) there: firmware, joint angles, state, enabling, temperatures and faults (enables and moves nothing). With `--device pika`, read the Pika Gripper ([in development](../robots/pika/index.md)) on a serial port: version, angle, status bits, temperatures and feedback rates. With `--device pika_sense`, read a Pika Sense's ([in development](../controllers/pose-ik.md)) serial link: version, jaw angle, `Command` and feedback rates.

```text
roboloom probe <port> [--device dynamixel|pika|pika_sense] [--ids 1,2,3] [--baudrate N]
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `port` | str | required | Serial port (Dynamixel, Pika) or CAN interface (PiPER) |
| `--device` | `dynamixel`, `pika`, `pika_sense` | `dynamixel` | What is on a serial port (a CAN interface is a PiPER) |
| `--ids 1,2,3` | list of integers | the IDs a broadcast ping finds | Dynamixel IDs to read |
| `--baudrate N` | int | 1000000 | Baud rate |

```bash
uv run roboloom probe /dev/ttyUSB0
```

## roboloom calibrate-joints { #calibrate-joints }

Save measured counts at the URDF zero pose to the calibration. It does not write to the bus, but it saves local YAML. The arm torque must be off.

```text
roboloom calibrate-joints <calibration> [--joints A,B]
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `calibration` | path | required | The calibration YAML |
| `--joints A,B` | list of names | every joint | Joints to record |

```bash
uv run roboloom calibrate-joints .roboloom/rakuda2/calibration/leader_right.yaml
```

## roboloom measure-travel { #measure-travel }

Save the range of motion moved by hand. It does not write to the bus, but it saves local YAML. The arm torque must be off.

```text
roboloom measure-travel <calibration> --out PATH
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `calibration` | path | required | The calibration YAML |
| `--out PATH` | path | required | Where to save the travel |

```bash
uv run roboloom measure-travel .roboloom/rakuda2/calibration/leader_right.yaml --out .roboloom/rakuda2/calibration/travel_right.yaml
```

## roboloom identify-gravity { #identify-gravity }

Measure holding current and identify the gravity model (leader gravity compensation, the follower `model_residual` estimator). `--collect` energizes the motors, so it asks the operator first.

```text
roboloom identify-gravity <calibration> --out PATH [--collect] [--data NPZ] [--delta N] [--max-rms-mA X]
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `calibration` | path | required | The calibration YAML |
| `--out PATH` | path | required | Where to save the gravity model |
| `--collect` | flag | off | Collect new poses first (energizes the arm) |
| `--data NPZ` | path | next to `--out` | npz of holding currents |
| `--delta N` | int | 30 | Approach offset, in counts |
| `--max-rms-mA X` | float | 15.0 | Largest RMS residual of the fit, in mA; above it the model is not saved |

```bash
uv run roboloom identify-gravity .roboloom/rakuda2/calibration/leader_right.yaml --out .roboloom/rakuda2/calibration/gravity_right.yaml --collect
```

## roboloom capture-pose { #capture-pose }

Save a follower's current pose as `poses/<follower>/<name>.yaml` (moves nothing), for `home`.

```text
roboloom capture-pose [robot] [follower] <name> [--force] [COMMON_OPTIONS]
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `robot` | robot name or path | the only robot | The configuration |
| `follower` | str | the only follower | The follower to read (may be omitted when there is one) |
| `name` | str | required | The pose name |
| `--force` | flag | off | Replace an existing pose |
| Common options | — | — | [Common options](#common-options) |

```bash
uv run roboloom capture-pose ready
```

## roboloom commission { #commission }

Read a node's EEPROM (Operating Mode, Current Limit), compare it with the configuration, write after a diff and operator confirmation, then read it back.

```text
roboloom commission [robot] <node> [COMMON_OPTIONS]
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `robot` | robot name or path | the only robot | The configuration |
| `node` | str | required | The Dynamixel node |
| Common options | — | — | [Common options](#common-options) (options change the expected values) |

```bash
uv run roboloom commission leader --with gravity
```

## roboloom watchdog-test { #watchdog-test }

Bench test: check that the Bus Watchdog stops a current-mode motor (energizes it). The node needs `bus_watchdog_ms`.

```text
roboloom watchdog-test [robot] <node> <joint> [--current-mA X] [COMMON_OPTIONS]
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `robot` | robot name or path | the only robot | The configuration |
| `node` | str | required | The Dynamixel node |
| `joint` | str | required | The joint to push |
| `--current-mA X` | float | 30.0 | Current to push with, in mA |
| Common options | — | — | [Common options](#common-options) |

```bash
uv run roboloom watchdog-test leader r_arm_sh_pitch1 --with gravity
```

## roboloom check-hold { #check-hold }

Bench test: measure whether a follower keeps its pose once commands stop, and after confirmation write `unattended:` to its YAML (energizes it). Only for models that declare `unattended` unknown ([Behaviour without torque and when left alone](configuration/followers.md#torque-off-and-unattended)).

```text
roboloom check-hold [robot] <follower> --tolerance X [--seconds N] [COMMON_OPTIONS]
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `robot` | robot name or path | the only robot | The configuration |
| `follower` | str | required | The follower to test |
| `--tolerance X` | float | required | Largest change still counted as holding, in the follower's unit |
| `--seconds N` | float | 10.0 | How long to watch after the commands stop, in seconds |
| Common options | — | — | [Common options](#common-options) |

```bash
uv run roboloom check-hold left --tolerance 0.02                 # PiPER's left
```

## roboloom tune-gravity { #tune-gravity }

Tune the leader's gravity compensation gain and hold joint by joint (energizes the arm). Requires a TTY before opening any device. Stop the dataflow that opens the same bus first. For the keys, see [Gravity tuning](operator-screen.md#gravity-tuning).

```text
roboloom tune-gravity [robot] <node> <group> [COMMON_OPTIONS]
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `robot` | robot name or path | the only robot | The configuration |
| `node` | str | required | The Dynamixel leader node |
| `group` | str | required | The `gravity_comp` group (e.g. `right_arm`) |
| Common options | — | — | [Common options](#common-options) (`--with gravity` selects the gravity-compensated configuration) |

```bash
uv run roboloom tune-gravity leader right_arm --with gravity
```

## roboloom gravity-check { #gravity-check }

At the same pose, release the arm once per multiple of the configured gains and measure the change in pose with and without compensation (energizes the arm).

```text
roboloom gravity-check [robot] <node> <group> [--poses N] [--scales 1,0] [COMMON_OPTIONS]
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `robot` | robot name or path | the only robot | The configuration |
| `node` | str | required | The Dynamixel leader node |
| `group` | str | required | The control group (e.g. `right_arm`) |
| `--poses N` | int | 3 | Number of poses to try |
| `--scales 1,0` | list of numbers | `1,0` | Multiples of the configured gains to try at each pose (e.g. `1,0,2,-2`) |
| Common options | — | — | [Common options](#common-options) (`--with gravity`) |

```bash
uv run roboloom gravity-check leader right_arm --with gravity
```
