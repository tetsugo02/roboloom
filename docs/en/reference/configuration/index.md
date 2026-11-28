# Configuration

A roboloom configuration is one file per robot, `config.yaml`, and the node YAML files it refers to. This page covers the file layout, the top-level keys, units, `extends`, launch options and experiment files. The status labels (Hardware-verified, Mock only, In development, Design only) are defined in [Status labels](../status-labels.md). The keys of each kind of node are on these pages:

| Page | Contents |
| --- | --- |
| [Followers](followers.md) | Keys of every follower and of each model, behaviour without torque, control rate |
| [Inputs](inputs.md) | `inputs:` (leader arm, Pika Sense) and `trackers:` |
| [Controllers](controllers.md) | `joint`, `parts`, `pose_ik` and `policy` under `controllers:`, force feedback and estimators |
| [The policy controller](policy.md) | Keys of `type: policy` |
| [Sensors](sensors.md) | Keys under `sensors:`, image storage, sensor selection |
| [recorder and session](recorder.md) | `recorder:`, quality warnings, video codec, `session:` |
| [Viewer](viewer.md) | Optional `viewer:` node keys, targets, logged entities, status fields <span class="status status--mock">Mock only</span> |
| [Control laws](control.md) | Keys of each law under `control:`, `limits`, `home` |

## File layout { #layout }

`roboloom init rakuda2` creates configuration, node, and calibration YAML in `.roboloom/rakuda2/`. It does not overwrite an existing directory. To bring a project up to a newer template, run `roboloom init rakuda2 --update`: it adds the files the project lacks, replaces files you have not touched and, for files you edited, lists the keys and options only the template has ([CLI](../cli.md#init)).

```text
.roboloom/
  .gitignore              # excludes raw data, logs and datasets (generated)
  rakuda2/
    config.yaml           # the configuration (one per robot)
    mock.yaml             # stand-ins for SET_ values (mock devices only)
    README.md             # the measurement steps
    nodes/                # node YAML (one file per feature)
    calibration/          # calibrations, gravity models, ranges, tuning
    poses/<follower>/     # saved poses (roboloom capture-pose)
    logs/                 # logs (not in Git)
    datasets/             # default dataset location (not in Git)
configs/roboloom/<name>.yaml   # experiment files (at the project root)
```

Each robot has one configuration (`config.yaml`); combinations of features are chosen with [launch options](#launch-options). The robot name `rakuda2` refers to `.roboloom/rakuda2/config.yaml`. When `.roboloom/` holds a single robot it can be omitted; you can also specify a file path.

## Configuration YAML { #config-yaml }

```yaml
repo_id: local/rakuda2
output: datasets/rakuda2
dataset_fps: 15
inputs:
  leader: nodes/leader.yaml
controllers:
  controller: nodes/controller.yaml
followers:
  follower: nodes/follower.yaml
sensors:
  audio: {file: nodes/audio.yaml, default: false}
  camera: nodes/camera.yaml
recorder: nodes/recorder.yaml
session: nodes/session.yaml
options:
  # see the next section
```

Node YAML paths and `output` are relative to the configuration file's directory. With no option enabled, the output location above is `.roboloom/rakuda2/datasets/rakuda2`. The robot's name is the configuration's directory name (`rakuda2` for `.roboloom/rakuda2/`) and is also the dataset's `robot_type`.

### Top-level keys { #top-level-keys }

Only the keys in this table are allowed at the top level; any other key is refused at load.

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `repo_id` | text | required | — | The dataset's `namespace/name`; the enabled options' `dataset` names are appended |
| `output` | path | required | — | Where the dataset is saved; the options' `dataset` names are appended |
| `dataset_fps` | number | required | Hz | Row rate of the dataset; at most each follower's `control_hz` |
| `mode` | text | `hardware` | — | `hardware` or `mock`; the CLI's `--mock` and the Python API's `mock=` take precedence |
| `trackers` | `{name: path}` | `{}` | — | Tracking systems ([Inputs](inputs.md#trackers)) |
| `inputs` | `{name: path}` | `{}` | — | Input devices ([Inputs](inputs.md)) |
| `controllers` | `{name: path}` | `{}` | — | Controllers ([Controllers](controllers.md)) |
| `followers` | `{name: path}` | `{}` | — | Followers ([Followers](followers.md)) |
| `sensors` | `{name: path or {file, default}}` | `{}` | — | Sensors; `{file, default: false}` does not run by default ([Sensor selection](sensors.md#sensor-selection)) |
| `estimators` | `{name: path}` | `{}` | — | Estimators ([Controllers](controllers.md#estimators)) <span class="status status--mock">Mock only</span> |
| `recorder` | path | required | — | Node YAML of the [recorder](recorder.md#recorder) |
| `session` | path | required | — | Node YAML of the [session](recorder.md#session) |
| `viewer` | path | — (off) | — | Optional node YAML of the [viewer](viewer.md) <span class="status status--mock">Mock only</span> |
| `options` | mapping | `{}` | — | [Launch options](#launch-options) |

`followers` lists the devices that move on command (arms, grippers, ...). One configuration may hold several followers. Each follower needs exactly one controller that drives it ([Followers and controllers](controllers.md#followers)). A configuration with `followers: {}` records its inputs and sensors only, with no `action`; it cannot have controllers, and its inputs and sensors need their own rate (`poll_hz`, `fps`) ([Hand-held collection with Pika Sense](../../tutorials/pika-handheld.md), in development).

### Node names { #node-names }

Node names are used as dora IDs and as dataset feature names, and are unique across roles. Use letters, digits, `-` and `_` only. `recorder`, `session`, `viewer`, `action` and `tick`, names starting with `action_` and names ending in `_status` are used by the dataflow and cannot be node names.

### type and unknown keys { #type }

Each node's `type` selects the implementation: a type name of roboloom (such as `rakuda2_follower`) or a reference `module:Class` to a class of your own ([From your own package](../../contribution/index.md#own-types)). A key the node does not read is refused on loading, so a misspelled key is not ignored in silence with the default used instead (for example `followers.follower: unknown keys torqe (did you mean torque?)`). A `control` group likewise takes only the keys its law reads.

### Unset values (SET_) and mock { #placeholders }

`SET_...` are robot-specific unset values; execution is refused if any remain in a referenced configuration. With `--mock` it validates and runs before any `SET_...` value is filled (with mock devices only, the stand-ins in the project's `mock.yaml` are used; the files keep their `SET_...` values, and the hardware refuses them as ever). `validate` checks the consistency of the configuration and dataflow without opening devices. It does not check that EEPROM matches the hardware, image capture, or stopping behavior.

## Units { #units }

Followers and leaders (`inputs`) each declare the unit of their joint positions; there is no default. Rakuda2 uses `dynamixel_count`. A controller's `unit`, if written, must equal its leader's and follower's (a `joint` controller with a `scale` on every joint may take an input in another unit; [Joint map](controllers.md#joint-map)). Commands carry the unit too, and a follower refuses a command in another unit.

The speed limit `max_speed` appears in these places, always in the follower's unit/s:

| Where | What it limits |
| --- | --- |
| `max_speed` in the follower's `limits` (per joint) | The follower's safety check: targets beyond it are clipped. It is the last line of defence, so keep it above the controller's value ([limits](control.md#limits)) |
| A `joint` controller's `max_speed` | How far a teleoperation target may move per period |
| The `max_speed` of a `policy` or `pose_ik` controller | How far a target may move per period, one value per follower as `{follower: value}` (followers differ in unit) |
| A controller's `home.max_speed` | The speed of the move to a saved pose; at most the controller's `max_speed` ([home](control.md#home)) |

`home.tolerance` (how close counts as arrived) is required, also in the follower's unit.

## Node files built on another (extends) { #extends }

Copying a node file for every combination of features means correcting a port or a measured value in all of them. Decide on one base file instead; the other files point at it with `extends` and say only what differs.

```yaml
# nodes/leader_gravity.yaml
extends: leader.yaml                  # the base: a node file in the same directory
without: [registers.operating_mode]   # keys of the base to drop (dotted); optional
registers:
  current_limit: {r_arm_sh_pitch1: 150}   # only what is added or changed
control:
- group: right_arm                    # laid over the base's group of the same name
  law: gravity_comp
  gravity_model: ../calibration/gravity_right.yaml
bus_watchdog_ms: 500
```

| Kind of value | How it is laid over the base |
| --- | --- |
| Mapping | Key by key (nested ones too) |
| List of mappings named by `group` or `name` (`control`, `limits`) | Entry by entry of the same name; entries with a new name are added last |
| Anything else (number, text, plain list) | Replaced |

- The base must be a file in the same directory, so that relative paths inside the files (`../calibration/...`) keep their meaning.
- A base may extend another file. A circle is refused.
- To remove or reorder entries of the base, drop the whole list with `without: [control]` and write it again. A key in `without` that the base does not have is refused.
- Unknown keys are checked on the result.
- `meta/roboloom.json` of a saved dataset keeps the resulting values and the names of the base files (`extends`).
- `check-hold` writes `unattended` into the file that has the key; when none has it, into the node's own file.

In the Rakuda2 template `leader_gravity.yaml` is built on `leader.yaml` and `policy_teleop.yaml` on `policy.yaml`.

## Launch options { #launch-options }

`options:` names the features chosen at launch (gravity compensation, extra sensors, and so on). Each option replaces, adds, or removes node files. The node files under `nodes/` stay split by feature; an option only chooses which of them are used. Option names use letters, digits, `-` and `_`.

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `help` | text | `""` | — | Description shown in the launcher |
| `default` | boolean | `false` | — | `true` enables it when nothing is specified |
| `requires` | list of text | `[]` | — | Options enabled together with it |
| `conflicts` | list of text | `[]` | — | Options that cannot be used at the same time |
| `set` | `{<role>.<node>: path or null}` | `{}` | — | Role is one of `trackers`, `inputs`, `controllers`, `followers`, `sensors`, `estimators`; `null` removes that node. The bare key `viewer: path or null` sets or disables the optional [viewer](viewer.md) |
| `dataset` | text | `""` | — | Short name appended to the dataset name while the option is enabled (letters, digits, `.`, `-`, `_`) |

The rules are:

- Enabling an option also enables the options in its `requires` and disables those in `conflicts`. Disabling one also disables the options that require it.
- Two enabled options setting the same node to different files is an error, unless one has the other in its `requires`; then the requiring (dependent) one wins. In the template, `bilateral`'s leader replaces `gravity`'s, and `policy_teleop`'s leader and policy replace those of `policy`.
- Unknown option names are an error.
- The `dataset` names of the enabled options are appended with `-`, in declaration order, to `repo_id` and `output`, so episodes of different shapes do not mix in one dataset.
- Loading is refused when an option without `dataset` changes the recorded features.
- `roboloom infer` enables the option named `policy` when there is one.

The options of the template (`src/roboloom/robots/rakuda2/template/config.yaml`). `bilateral` and `viewer` are <span class="status status--mock">Mock only</span> and `pika` <span class="status status--dev">In development</span>.

```yaml
options:
  digit:
    help: record the left/right DIGIT tactile sensors
    set:
      sensors.digit_left: nodes/digit_left.yaml
      sensors.digit_right: nodes/digit_right.yaml
    dataset: digit
  gravity:
    help: gravity-compensated leader arms (after the measurement steps of README.md)
    set:
      inputs.leader: nodes/leader_gravity.yaml
  bilateral:
    help: force feedback from the follower to the leader (NOT verified on hardware)
    requires: [gravity]
    set:
      inputs.leader: nodes/leader_bilateral.yaml
      controllers.controller: nodes/controller_bilateral.yaml
      followers.follower: nodes/follower_bilateral.yaml
      estimators.effort: nodes/effort.yaml
    dataset: bilateral
  policy:
    help: a learned policy drives the follower (`roboloom infer` turns this on)
    conflicts: [gravity]
    set:
      inputs.leader: null
      controllers.controller: null
      controllers.policy: nodes/policy.yaml
    dataset: eval
  pika:
    help: a Pika Sense per arm through inverse kinematics (in development, mock only)
    conflicts: [gravity, policy]
    set:
      trackers.lighthouse: nodes/lighthouse.yaml
      inputs.leader: null
      inputs.right_sense: nodes/right_sense.yaml
      inputs.left_sense: nodes/left_sense.yaml
      controllers.controller: nodes/controller_pika.yaml
    dataset: pika
  policy_teleop:
    help: with policy, the leader can drive before and during an episode (Teleop / Policy)
    requires: [policy]
    set:
      inputs.leader: nodes/leader.yaml
      controllers.policy: nodes/policy_teleop.yaml
    dataset: teleop
  viewer:
    help: show the observations live in Rerun (needs the viz extra)
    set:
      viewer: nodes/viewer.yaml
```

| Enabled options | `repo_id` |
| --- | --- |
| none | `local/rakuda2` |
| `digit` | `local/rakuda2-digit` |
| `policy` | `local/rakuda2-eval` |
| `digit`, `policy` | `local/rakuda2-digit-eval` |
| `policy`, `policy_teleop` | `local/rakuda2-eval-teleop` |
| `gravity`, `bilateral` | `local/rakuda2-bilateral` |
| `pika` | `local/rakuda2-pika` |

`output` gets the same name (for example `datasets/rakuda2-digit`). Check which options are enabled and what the dataset is called with, for example, `roboloom validate --with digit`. See [CLI](../cli.md) for choosing options and [Rakuda2](../../robots/rakuda2/index.md) for the combinations and limitations on Rakuda2.

## Experiment files { #experiments }

`.roboloom/<robot>/` holds the robot's own settings (ports, measured values, limits, poses). What changes with every experiment (the policy and its checkpoint, the options, where the episodes go, the task, the length) goes into `configs/roboloom/<name>.yaml` of the project. `roboloom infer --experiment <name>` and `roboloom record --experiment <name>` run as the file says.

```yaml
# configs/roboloom/drawer.yaml
help: evaluation of the drawer policy
robot: rakuda2                       # .roboloom/rakuda2 is used; a robot on the command line wins
options: [policy, digit]             # launch options to enable
dataset:                             # where the episodes go; left out: as the robot's configuration says
  root: data/roboloom/drawer
  repo_id: local/rakuda2-drawer
nodes:                               # what the nodes are given on top of their files
  controllers.policy:                # a mapping: laid over the node's settings
    factory: my_lab.policies:load
    kwargs: {checkpoint: /path/to/project/outputs/drawer/last.ckpt}
    rate_hz: 10
    action_horizon: 8
  inputs.leader: nodes/leader_fixed_head.yaml   # text: another node file of the robot's directory
task: open the drawer
steps: 200                           # or seconds: 40
episodes: 10
home: true
confirm: true
```

```bash
uv run roboloom infer --experiment drawer            # configs/roboloom/drawer.yaml
uv run roboloom infer --experiment path/to/file.yaml
```

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `help` | text | — | — | Description |
| `robot` | text | — | — | The robot's name (`.roboloom/<name>/`); a robot on the command line wins |
| `options` | list of text | — | — | Launch options to enable; `--with` and `--without` add to and remove from them |
| `dataset` | `{root, repo_id}` | as the robot's configuration says | — | `root` (the dataset's directory) and `repo_id`. The episodes go exactly there; the options' names (`-digit-eval`) are not appended |
| `nodes` | `{<role>.<node>: mapping or path}` | `{}` | — | Changes by node. A mapping is laid over the node's settings by the rules of [`extends`](#extends); text names another node file, seen from the robot's directory |
| `task` | text | — | — | The value of `--task` |
| `seconds` | number | — | s | The value of `--seconds` |
| `episodes` | integer | — | — | The value of `--episodes` |
| `home` | `true` / `false` / `<name>` | `false` | — | Move to the configured defaults (`true`), skip the move (`false`), or select a named pose (`<name>`) before every episode. See [home](control.md#home) |
| `confirm` | boolean | `false` | — | `true` enables [`--confirm`](../cli.md#record) for `record` and `infer`. An explicit `--confirm` takes precedence. <span class="status status--mock">Mock only</span> |
| `steps` | integer | — | actions | The value of `infer --steps`: the episode ends after this many actions of the policy. Not together with `seconds` |

- **Name or path**: `--experiment drawer` is `configs/roboloom/drawer.yaml` under the directory the command runs in. A word with `/` or ending in `.yaml` is read as a path.
- **Relative paths**: `dataset.root` is seen from the directory the command runs in (the project's root), text under `nodes` from the robot's directory.
- **Nodes that can be named**: those present after the options are applied. `followers.*` cannot be changed (a follower's range, speed and jump limits are the last check of every command).
- What the file does not say stays as the robot's node files say (the policy's `max_speed`, `command_deadline_ms`, ...).
- Values on the command line win (`--experiment drawer --seconds 10`). The command is refused when neither has `seconds` or `steps`.
- An episode given in `steps` ends as soon as the policy has executed that many actions. In case inference keeps it waiting, it also ends after a time limit (`steps / rate_hz × 1.5 + 5` seconds) and says at how many steps.
- Unknown keys are refused.
- `validate`, `check-dataset` and `label` take `--experiment` too (the experiment's configuration and dataset).
- `meta/roboloom.json` of a saved dataset keeps the experiment's name and the resulting settings.
- A policy with `backend: server` is served from the same file (`roboloom serve-policy --experiment <file>`).

In Python, `Session.launch(experiment=...)` takes the name, the path or a mapping with the same keys. A project that composes its experiments with Hydra passes the composed result; roboloom itself does not depend on Hydra.

```python
from omegaconf import OmegaConf
from roboloom import Session

experiment = OmegaConf.to_container(cfg.roboloom, resolve=True)   # composed by Hydra
with Session.launch(experiment=experiment) as session:
    session.wait_ready(60)
    session.record(experiment["task"], 155.0, steps=experiment["steps"])
```

## Managing logs and configuration { #logs }

Logs are placed in `logs/<dataset name>-<time>/` next to the configuration file (for example `logs/rakuda2-digit-20261102-101500/`); the dataset name tells which options were enabled. When the node ends, the leader's current control is written to `<leader name>_trace.npz`, and each follower's per-tick state (positions, velocities, currents, target, mode) to `<follower name>_trace.npz`. Manage YAML configuration, gravity models, ranges of motion, tuning values, and saved initial poses (`poses/<follower>/`) with Git; raw data `*.npz`, logs, datasets, and FIFOs (`config.fifo`) are excluded by the generated `.roboloom/.gitignore`.

API details are in [Python API](../python-api/index.md), and commands are in [CLI](../cli.md).
