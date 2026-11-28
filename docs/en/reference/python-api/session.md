# Session

The collection and inference API at the top of the `roboloom` package. Usage examples come first, followed by the descriptions generated from the docstrings.

## Structure { #architecture }

The robot learning systems we examined (franka_ros2, DROID, deoxys, diffusion_policy, OpenPI, etc.) all separated the following three parts:

- A fast loop that drives the motors
- Teleoperation and recording
- The policy

roboloom takes the same structure.

- **dora dataflow**: each of the following runs in its own process.
  - The follower nodes and the leader node (control loops)
  - Sensors
  - The recorder
  - The policy node
- **`Session`**: launches the dataflow and sends events. Events are start, stop, save, task name, and so on. It does not run the control loop.
  - Therefore, even if the user's script does heavy processing or stalls, the control period is not disturbed.

The settings of one experiment (the policy, the options, the dataset) are passed with `Session.launch(experiment=...)`: a name (`configs/roboloom/<name>.yaml`), a file path or a mapping with the same keys ([experiment files](../configuration/index.md#experiments)).

## Loading a configuration { #loading-a-configuration }

A configuration can be specified either by file path or by its robot name under `.roboloom/` (`rakuda2` is `.roboloom/rakuda2/config.yaml`).

Launch options are chosen with `options=`: the listed options and the options they require are enabled. With `None` (the default), the options with `default: true` are enabled. Unlike the CLI's `--with` / `--without`, `options=` is the whole set to enable (it is not added to the default options). `mock=True` runs mock devices and `mock=False` real ones; `None` follows the YAML's `mode` (default `hardware`).

```python
from roboloom import load_config

cfg = load_config("rakuda2", options=["gravity", "digit"])
print(cfg.options, cfg.repo_id)  # ('digit', 'gravity') local/rakuda2-digit
```

`load_config(..., video_codec="av1")` and `Session.launch(..., video_codec="av1")` record `storage: video` images as AV1 (`"h264"` for H.264, `None` for the recorder YAML's choice, else H.264). With a loaded `RobotConfig`, choose it in `load_config`. For appending with a codec that differs from the existing dataset, see [Video codec](../configuration/recorder.md#video-codec).

## Recording episodes { #recording-episodes }

```python
from roboloom import Session

with Session.launch("rakuda2", options=["gravity"]) as s:
    s.wait_ready()
    result = s.record("pick up the cup", seconds=30)
    if result.pending:
        (result,) = s.wait_saves()
    print(result.index, result.frames, result.warnings)
```

- `launch` waits until every node has started reporting its status.
- Every `start` is checked: the follower must be within `alignment_tolerance` of the leader, not only at the first alignment. `record` waits for this (`ready_timeout`, default 60 s) before each episode; `start` raises `SessionError` when the arms differ.
- Real hardware is the default. Pass `mock=True` to run mock devices.
- `launch` uses `options` and `mock` only when the configuration is given as a path or robot name. When passing a loaded `RobotConfig`, choose them with `load_config(..., options=..., mock=...)` first.
- Each node process receives the enabled options in `ROBOLOOM_OPTIONS` and the mode in `ROBOLOOM_MODE`.
- Leaving the `with` block does the following:
  - Discards any in-progress episode.
  - If an `operator` is configured, asks you to support the arms. Enter releases the follower too; typing `hold` keeps the follower holding.
  - Waits for queued saves, then stops the dataflow.
  - The leader goes limp. The follower's torque goes off only when you chose to release it; otherwise it keeps its torque and last target. A follower that does not hold when left alone (`unattended` other than `holds`) does not keep holding; see [Behaviour without torque and when left alone](../configuration/followers.md#torque-off-and-unattended).
  - To decide from a script, call `s.close(release=True)` (release) or `s.close(release=False)` (hold).
- Logs are kept in `logs/<dataset name>-<time>/` next to the configuration file (for example `logs/rakuda2-digit-20261102-101500/`).
  - `dora.log`
  - The leader trace
  - The location is available as `s.log_dir`.

## Status screen and exit confirmation { #status-screen }

- `Session.launch(..., screen="auto")` is the default. When stdout is a terminal, a background thread updates the Rich node-status table and messages panel at 10 Hz. Interactive CLI commands instead use the [Textual operator screen](../operator-screen.md).
  - Set `screen=False` to disable the display. It is hidden by default when stdout is not a terminal, such as in a pipe.
  - Your script's `print()` output appears above the screen. The screen reads no keys, so you can use `input()` and API calls to operate the session. It does not add the keyboard controls of CLI `record`.
  - Save results and quality warnings also appear in the messages panel.
- `operator="auto"` is the default. When stdin is a terminal, the session asks you to support the leader and follower arms before exiting.
  - Support the arms and press Enter to end with the follower torque off as well.
  - Type `hold` to end with the follower still holding.
  - When the follower has `torque: false`, only the leader confirmation is shown.
  - The confirmation is built from the devices' traits: it names what to support (`falls`) and what to empty (`lets_go`), and when no follower holds, `hold` means quitting without releasing (those followers may not hold). `s.release_note()` returns what to do before `release` as a string; `release(confirm=False)` raises `HardwareError` with it.
  - With `operator=None`, or when stdin is not a terminal, this confirmation is skipped and the follower keeps holding. Setting only `screen=False` does not disable it.
  - If the follower is left holding, support its arms or lower them to a safe pose before switching off its power.

## Automatic task naming { #task-names }

For `task`, you can pass either a string or a function that takes an `EpisodeInfo` and returns a string.

| `EpisodeInfo` field | Contents |
| --- | --- |
| `index` | Next dataset index if all pending saves succeed (`next_info()` adds saved and pending counts) |
| `number` | Number saved by this Session plus its accepted saves still awaiting a result |
| `dataset` | The dataset's name (the part of `repo_id` after `/`, with the enabled options' names; e.g. `rakuda2-digit`) |
| `previous` | List of tasks saved in this Session |

```python
import itertools

objects = itertools.cycle(["cup", "bottle", "sponge"])

with Session.launch("rakuda2") as s:
    s.wait_ready()
    for _ in range(9):
        s.record(lambda info: f"pick up the {next(objects)}", seconds=20)
```

```python
# numbered, ask the operator each time, etc.
s.record(lambda info: f"trial {info.index:03d}", seconds=20)
s.record(lambda info: input(f"task for episode {info.index}: "), seconds=20)
```

- The resolved task string is saved in `task` of each frame of the LeRobotDataset.
- It can be used directly as the language instruction during training.

## Fine-grained control { #step-by-step }

- You can call `start(task)`, `stop()`, `save()`, `discard()`, `estop()`, and `release(confirm=True)` one at a time.
- <span class="status status--mock">Mock only</span> [Background saving](../../data/recording.md#background-saving) adds the following save results and controls.

| Call or field | Behavior |
| --- | --- |
| `save(timeout=300, *, label=None, note=None, wait=None)` | `wait=None` follows `background_save`. Use `wait=True` for this episode's final result. With `background_save: false`, `save` always waits for the write. |
| `EpisodeResult.pending` | In background mode, `save()` by default and `record()` for kept episodes return `pending=True`, `saved=False`, and `index=None`. Use a final result for the saved index. |
| `wait_saves(timeout=None) -> list[EpisodeResult]` | Collects this Session's queued results in submission order, including completed results that have yet to be collected. After those saves finish, raises `SessionError` if any failed, with successes in `report["results"]` and failures in `report["failures"]`. A timeout raises `SessionError` and the results can be collected later. |
| `pending_saves` | Latest recorder count of queued and in-progress saves. |

- Inspecting state:
  - `status()`: latest status of each node.
  - `reports()`: unread reports, such as robot mode changes.
- When a command is rejected (e.g. the leader is not aligned), a `SessionError` is raised.
  - `start` is rejected while recording, while an episode awaits `save` or `discard`, during a synchronous save, or when the background queue is full. If the followers and policy received a `start` the recorder could not take, they are stopped too.
- `record` discards the episode and raises `EpisodeFailed` (a `SessionError`) when a controller fails during it (for example the policy raised) or a follower latches FAULT or ESTOP. The policy can be used for the next episode as it is.
- `estop()` goes out even after a node has failed (other commands raise `SessionError` once they see a failed node).
- When the process that called `Session.launch` ends, however it ends (killed, an exception, its terminal closed), the dataflow discards the episode in progress, lets the followers hold and ends. A robot never keeps following a policy after its script is gone, with or without `close()`. Child processes made with `multiprocessing` and the like count as the process still being there.
- `home(timeout=None)`: move the leader and follower slowly to the initial pose chosen in the controller and wait until both arrive. Raises `SessionError` if they do not arrive or a node refuses. `record(..., home=True)` does this before every episode. See "Move to an initial pose" in [Leader](../../controllers/leader.md).
- `teleop()`, `policy()`, `stop_teleop()`: with `teleop:` in the policy, hand the followers to the leader (before an episode, or during one as an intervention), hand back to the policy, and end teleoperation outside an episode. See [teleoperation and interventions](../../policy/intervention.md#teleop).
- When every controller follows operator input, `teleop()` uses the readiness and alignment checks of `start` and arms the followers without recording. `stop_teleop()` returns once every follower holds. Call it before `home()` if teleop is active. See [teleop outside an episode](../../controllers/index.md#teleop). <span class="status status--mock">Mock only</span>

```python
s.start("wipe the table")
while not task_done():
    print(s.status()["follower"]["fields"]["mode"])
    time.sleep(0.5)
stopped = s.stop()
s.save(wait=True) if stopped.ok else s.discard()
```

## Policies, evaluation and choosing episodes { #guides }

- Running a policy: [Running a policy](../../policy/run.md)
- Recording an evaluation's verdicts: [Evaluation verdicts](../../policy/evaluation.md#labels)
- Choosing which episodes to keep (`keep`): [Choosing episodes](../../data/recording.md#choosing-episodes)

## Sensor selection { #sensor-selection }

`load_config(..., sensors=[...], observe=[...])` and `Session.launch(..., sensors=[...], observe=[...])` select the sensors to start and record independently from the policy's observations. `None` keeps the configuration's defaults; `[]` selects none. Follower state is always observed. When passing a `RobotConfig`, select in `load_config` (`Session.launch` rejects additional selection arguments).

```python
with Session.launch(
    "rakuda2",
    options=["policy"],
    sensors=["camera", "audio"],
    observe=["camera"],
    policy="my_lab.policies:load",
) as session:
    session.wait_ready()
    session.record("pick", seconds=20)
```

- Unselected sensor YAML files are not loaded. Observing a sensor that is not started fails.
- Sensors introduced by options can also be selected individually, including either DIGIT. Options apply first.
- An optional sensor uses `{file: nodes/audio.yaml, default: false}`; string paths remain enabled by default.
- Recording includes every started sensor, even those omitted from `observe`.

The CLI selection is in [Sensor selection in the CLI](../cli.md#sensor-selection) and the rules in [Sensor selection](../configuration/sensors.md#sensor-selection). See also [Audio](../../sensors/audio.md).

## Running in one process: InProcessSession { #inprocesssession }

- `InProcessSession` performs robot bus access, sensor reads, and controller calls all on the caller's thread.
- Use cases:
  - Tests
  - Simulation
  - Simple robots with few sensors
- It drives one follower. Run configurations with several followers with `Session`.
- `save_episode()` always saves synchronously, including when the recorder YAML enables background saving for the dataflow.
- A policy can be passed directly to `step(policy=...)`.
  - However, if the policy or sensors are slow, the control period is delayed too.
- Run the real Rakuda-2 with `Session`.
  - `from_yaml` rejects configurations that use a motor-controlling leader (trigger spring, gravity compensation).
  - `from_yaml` also rejects configurations that use a policy controller.
- In `InProcessSession.from_yaml(path, *, options=None, mock=None, sensors=None, dataset=None)`, `options` and `mock` mean the same as in `load_config`.

This mock example uses no devices or sample files from the repository. The `record` extra is required. Do not reuse its joint ranges or speeds on hardware.

```python
from roboloom import InProcessSession
from roboloom.drivers.mock import MockBus

with InProcessSession.from_components(
    robot="my-mock",
    bus=MockBus(dimension=2),
    joint_names=["j1", "j2"],
    unit="count",
    limits=[
        {"name": "j1", "min": 0, "max": 4095, "max_speed": 3000, "max_jump": 400},
        {"name": "j2", "min": 0, "max": 4095, "max_speed": 3000, "max_jump": 400},
    ],
    controller=lambda obs: [2048, 2048],
    output="datasets/my-mock",
    repo_id="local/my-mock",
) as session:
    session.start_episode("handover")
    session.run(3.0)
    session.stop_episode()
    session.save_episode()
```

For the data collection procedure on real hardware, see [Rakuda2: teleoperated collection](../../tutorials/rakuda2/collect.md).

## API { #api }

::: roboloom.Session
    options:
      heading_level: 3

::: roboloom.EpisodeInfo
    options:
      heading_level: 3

::: roboloom.EpisodeResult
    options:
      heading_level: 3

::: roboloom.EpisodeFailed
    options:
      heading_level: 3

::: roboloom.SessionError
    options:
      heading_level: 3

::: roboloom.InProcessSession
    options:
      heading_level: 3

::: roboloom.load_config
    options:
      heading_level: 3

::: roboloom.resolve_config
    options:
      heading_level: 3

::: roboloom.init_project
    options:
      heading_level: 3

::: roboloom.Sample
    options:
      heading_level: 3

## Exceptions { #errors }

::: roboloom.RoboloomError
    options:
      heading_level: 3

::: roboloom.ConfigError
    options:
      heading_level: 3

::: roboloom.HardwareError
    options:
      heading_level: 3

::: roboloom.SetupError
    options:
      heading_level: 3

::: roboloom.errors.Cancelled
    options:
      heading_level: 3
