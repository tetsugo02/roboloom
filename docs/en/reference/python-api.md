# Python API and CLI

Every roboloom operation is available as a Python function. The CLI (`roboloom ...`) is only a thin layer that calls those functions and prints the result.

Add roboloom to your own uv project following [Installation](../quick-start/installation.md), and use `uv add git+https://github.com/tetsugo02/roboloom.git --extra record` for recording. Save the code below in your own Python script and run it with `uv run python <script.py>`. Configuration and `.roboloom/` paths are relative to your project root.

| Task | CLI | Python |
| --- | --- | --- |
| Create a project | `roboloom init rakuda2` | `roboloom.init_project("rakuda2")` |
| Align the EEPROM | `roboloom commission [robot] <node>` | `setup.plan_commission(...)`, `setup.apply_commission(plan, operator)` |
| Measure the range of motion | `roboloom measure-travel <cal> --out ...` | `setup.measure_travel(cal, out, operator)` |
| Identify the gravity model | `roboloom identify-gravity <cal> --out ... --collect` | `setup.identify_gravity(cal, out, operator, collect=True)` |
| Check gravity compensation | `roboloom gravity-check [robot] leader right_arm --with gravity` | `setup.gravity_check(...)` |
| Tune gravity compensation | `roboloom tune-gravity [robot] leader right_arm --with gravity` | `setup.open_tuning(...)` → `TuningSession` |
| Record an episode | `roboloom record [robot] --task ... --seconds 30` | `Session.launch(...)` → `record(...)` |
| Run with a policy | `roboloom infer [robot] --policy pkg:make --seconds 30` | `Session.launch(cfg, options=["policy"], policy="pkg:make")` → `record(...)` |
| Record continuously from the operation screen | `roboloom run [robot]` | The `Session.launch(...)` status screen and `start()` / `stop()` / `save()` |
| Install the skill for coding agents | `roboloom skills install` | `roboloom.agent_skills.install(root=".", targets=("agents", "claude"), force=False)`, `agent_skills.check(...)` |

A configuration can be specified either by file path or by its robot name under `.roboloom/` (`rakuda2` is `.roboloom/rakuda2/config.yaml`).

Launch options are chosen with `options=`: the listed options and the options they require are enabled. With `None` (the default), the options with `default: true` are enabled. Unlike the CLI's `--with` / `--without`, `options=` is the whole set to enable (it is not added to the default options). `mock=True` runs mock devices and `mock=False` real ones; `None` follows the YAML's `mode` (default `hardware`).

```python
from roboloom import load_config

cfg = load_config("rakuda2", options=["gravity", "digit"])
print(cfg.options, cfg.repo_id)  # ('digit', 'gravity') local/rakuda2-digit
```

## 1. Collection and inference: `Session`

### Structure

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

### Record an episode

```python
from roboloom import Session

with Session.launch("rakuda2", options=["gravity"]) as s:
    s.wait_ready()  # wait until the leader is aligned with the follower
    result = s.record("pick up the cup", seconds=30)
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
  - Stops the dataflow.
  - The leader goes limp. The follower's torque goes off only when you chose to release it; otherwise it keeps its torque and last target. A follower that does not hold when left alone (`unattended` other than `holds`) does not keep holding; see "Behaviour without torque and when left alone" in [Configuration](configuration.md).
  - To decide from a script, call `s.close(release=True)` (release) or `s.close(release=False)` (hold).
- Logs are kept in `logs/<dataset name>-<time>/` next to the configuration file (for example `logs/rakuda2-digit-20261102-101500/`).
  - `dora.log`
  - The leader trace
  - The location is available as `s.log_dir`.

### Status screen and exit confirmation

- `Session.launch(..., screen="auto")` is the default. When stdout is a terminal, a background thread updates the Rich node-status table and messages panel at 10 Hz. Interactive CLI commands instead use the [Textual operator screen](operator-screen.md).
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

### Automatic task naming

For `task`, you can pass either a string or a function that takes an `EpisodeInfo` and returns a string.

| `EpisodeInfo` field | Contents |
| --- | --- |
| `index` | Episode number in the dataset (number of saved episodes) |
| `number` | Number recorded in this Session |
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

### Choose which episodes to keep

- `record` calls `keep(result)` after stopping and before saving.
  - If it returns `False`, the episode is discarded.
- What `result` contains:
  - `metrics`: recorder metrics. Missing rate, valid action rate, control period distribution.
  - `warnings`: items that exceeded quality limits.
- Quality limits can be changed in `quality` of `nodes/recorder.yaml`.
  - `max_missing_rate` (default 0.05)
  - `min_action_valid_rate` (default 0.9)
  - `max_interval_ms` (default 100)

```python
ok = s.record("pick up the cup", 30, keep=lambda ep: ep.ok)
```

### Fine-grained control

- You can call `start(task)`, `stop()`, `save()`, `discard()`, `estop()`, and `release(confirm=True)` one at a time.
  - Example: when start and end are decided by an external signal.
- Inspecting state:
  - `status()`: latest status of each node.
  - `reports()`: unread reports, such as robot mode changes.
- When a command is rejected (e.g. the leader is not aligned), a `SessionError` is raised.
- `home(timeout=None)`: move the leader and follower slowly to the initial pose chosen in the controller and wait until both arrive. Raises `SessionError` if they do not arrive or a node refuses. `record(..., home=True)` does this before every episode. See "Move to an initial pose" in [Leader](../controllers/leader.md).

```python
s.start("wipe the table")
while not task_done():  # user's own check
    print(s.status()["robot"]["fields"]["mode"])
    time.sleep(0.5)
stopped = s.stop()  # not saved yet; metrics and warnings can be inspected
s.save() if stopped.ok else s.discard()
```

### Run with a policy

**Policy shape**
- An object with `reset()` and `infer(observation)` (`roboloom.Policy`).
- Observation keys are the same as the dataset features.
  - `observation.state`
  - `observation.images.camera`
  - `observation.images.digit_left`
  - Others
- `task` is also passed.
- Optionally, `bind(spec)`. Right after loading it receives the observation's shapes and the action's names, and refuses when they differ from training. LeRobot checkpoints load with `roboloom.policy.lerobot:load`. See [Driving with a policy](../controllers/policy.md).
- What `infer` returns: joint targets. Like the recorded `action`, they join every follower's joints in configuration order, each in its follower's unit. Either a single step `[n]` or an action chunk `[H, n]`. Each robot's order, size and units are on its page ([Rakuda2](../robots/rakuda2.md) and others).

**Node behavior**
- The policy is loaded from a `"module:callable"` reference and run by the policy node inside the dataflow.
  - Modules are looked up in the installed packages first, then in the robot's directory (`.roboloom/<robot>/`). A policy file kept next to the configuration is imported without `PYTHONPATH`. An installed module of the same name takes precedence.
- The following are set in `nodes/policy.yaml`:
  - Sensors to observe (`observe`)
  - Rate (`rate_hz`)
  - How many steps of an action chunk to execute before requesting the next one (`action_horizon`)
- Safety checks are the same as for teleoperation.
  - Targets sent are clipped by the velocity limit.
  - `FollowerSafety` checks the range of motion and deadlines.

```python
# my_lab/policies.py
class MyPolicy:
    def __init__(self, checkpoint: str): ...
    def reset(self): ...
    def infer(self, observation):
        return self.model(observation)  # [H, n]


def load(checkpoint: str) -> MyPolicy:
    return MyPolicy(checkpoint)
```

```python
with Session.launch(
    "rakuda2",
    options=["policy"],  # joint state + RealSense by default; add "digit" if needed
    policy="my_lab.policies:load",
    policy_kwargs={"checkpoint": "outputs/act/last"},
) as s:
    s.wait_ready()  # until the policy has finished loading
    for k in range(10):
        s.record(f"pick up the cup (eval {k})", seconds=30)  # saved as evaluation data
```

**Notes**
- No command is sent during `infer`.
  - If inference takes longer than `command_deadline_ms`, the robot enters HOLD. It stops and waits.
  - An asynchronous mode that keeps executing the previous action chunk during inference is future work.
- The template's default policy `roboloom.policy:hold` keeps the arms in place.
  - Use it when verifying the inference path on real hardware for the first time.

## 2. Setup and measurement: `roboloom.setup`

- The measurement functions return results as dataclasses and report failures as exceptions.
  - `ConfigError`: configuration error.
  - `SetupError`: measurement preconditions not met, or insufficient accuracy.
  - `HardwareError`: device state does not match, e.g. torque is enabled.
  - `Cancelled`: confirmation was declined. Nothing has been written.
- Steps that need human action query an `Operator`.
  - Supporting the arm, placing a pose, pressing Enter, etc.
  - The CLI passes a `TerminalOperator`.
  - In scripts and tests, you can pass a `ScriptedOperator` with a list of answers.
- Functions that take a configuration accept a path, a robot name, or a loaded `RobotConfig`. To choose options or the mode, load it with `load_config(..., options=..., mock=...)` and pass that.
- `plan_commission`, `watchdog_test`, and `gravity_check` refuse a mock configuration.

```python
from roboloom import setup
from roboloom.operator import TerminalOperator

op = TerminalOperator()
from roboloom import load_config

gravity = load_config("rakuda2", options=["gravity"])
plan = setup.plan_commission(gravity, "leader")
for line in plan.lines():
    print(line)
setup.apply_commission(plan, op)  # write after confirmation

fit = setup.identify_gravity(
    ".roboloom/rakuda2/calibration/leader_right.yaml",
    ".roboloom/rakuda2/calibration/gravity_right.yaml",
    op,
    collect=True,
)
for joint in fit.joints:
    print(joint.joint, f"{joint.explained:.0%}")
```

```python
# tune gravity compensation without the screen (e.g. automation that tries values in turn)
tuning = setup.open_tuning(gravity, "leader", "right_arm")
try:
    tuning.start()
    tuning.key("]")  # gain +0.1 for the selected joint
    for _ in range(120):
        tuning.step()
        time.sleep(tuning.period_s)
    print([(r.joint, r.gain, r.sent_mA) for r in tuning.rows()])
finally:
    tuning.close()
```

## 3. Run in a single process: `InProcessSession`

- `InProcessSession` performs robot bus access, sensor reads, and controller calls all on the caller's thread.
- Use cases:
  - Tests
  - Simulation
  - Simple robots with few sensors
- It drives one follower. Run configurations with several followers with `Session`.
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

For the data collection procedure on real hardware, see [Rakuda2 Quick start](../quick-start/rakuda2.md).
