# Python API and CLI

Every roboloom operation is available as a Python function. The CLI (`roboloom ...`) is only a thin layer that calls those functions and prints the result.

Add roboloom to your own uv project following [Installation](../quick-start/installation.md), and use `uv add git+https://github.com/tetsugo02/roboloom.git --extra record` for recording. Save the code below in your own Python script and run it with `uv run python <script.py>`. Experiment and `.roboloom/` paths are relative to your project root.

| Task | CLI | Python |
| --- | --- | --- |
| Create a project | `roboloom init rakuda2` | `roboloom.init_project("rakuda2")` |
| Align the EEPROM | `roboloom commission <exp> <node> --hardware` | `setup.plan_commission(...)`, `setup.apply_commission(plan, operator)` |
| Measure the range of motion | `roboloom measure-travel <cal> --out ...` | `setup.measure_travel(cal, out, operator)` |
| Identify the gravity model | `roboloom identify-gravity <cal> --out ... --collect --hardware` | `setup.identify_gravity(cal, out, operator, collect=True, hardware=True)` |
| Check gravity compensation | `roboloom gravity-check <exp> leader right_arm --hardware` | `setup.gravity_check(...)` |
| Tune gravity compensation | `roboloom tune-gravity <exp> leader right_arm --hardware` | `setup.open_tuning(...)` → `TuningSession` |
| Record an episode | `roboloom record <exp> --task ... --seconds 30 --hardware` | `Session.launch(...)` → `record(...)` |
| Run with a policy | `roboloom infer <exp> --policy pkg:make --seconds 30 --hardware` | `Session.launch(exp, policy="pkg:make")` → `record(...)` |
| Record continuously from the operation screen | `roboloom run <exp> --hardware` | The `Session.launch(...)` status screen and `start()` / `stop()` / `save()` |

An experiment can be specified either by file path or by its name under `.roboloom/` (`rakuda2`, `rakuda2/experiment_gravity`).

## 1. Collection and inference: `Session`

### Structure

The robot learning systems we examined (franka_ros2, DROID, deoxys, diffusion_policy, OpenPI, etc.) all separated the following three parts:

- A fast loop that drives the motors
- Teleoperation and recording
- The policy

roboloom takes the same structure.

- **dora dataflow**: each of the following runs in its own process.
  - The robot node and the leader node (control loops)
  - Sensors
  - The recorder
  - The policy node
- **`Session`**: launches the dataflow and sends events. Events are start, stop, save, task name, and so on. It does not run the control loop.
  - Therefore, even if the user's script does heavy processing or stalls, the control period is not disturbed.

### Record an episode

```python
from roboloom import Session

with Session.launch("rakuda2/experiment_gravity", hardware=True) as s:
    s.wait_ready()  # wait until the leader is aligned with the follower
    result = s.record("pick up the cup", seconds=30)
    print(result.index, result.frames, result.warnings)
```

- `launch` waits until every node has started reporting its status.
- Experiments that open real hardware require `hardware=True`.
- Leaving the `with` block does the following:
  - Discards any in-progress episode.
  - If an `operator` is configured, asks you to support the arms. Enter releases the follower too; typing `hold` keeps the follower holding.
  - Stops the dataflow.
  - The leader goes limp. The follower's torque goes off only when you chose to release it; otherwise it keeps its torque and last target.
  - To decide from a script, call `s.close(release=True)` (release) or `s.close(release=False)` (hold).
- Logs are kept in `logs/<experiment name>-<time>/` next to the experiment file.
  - `dora.log`
  - The leader trace
  - The location is available as `s.log_dir`.

### Status screen and exit confirmation

- `Session.launch(..., screen="auto")` is the default. When stdout is a terminal, a background thread updates the same node-status table and messages panel as the CLI at 10 Hz.
  - Set `screen=False` to disable the display. It is hidden by default when stdout is not a terminal, such as in a pipe.
  - Your script's `print()` output appears above the screen. The screen reads no keys, so you can use `input()` and API calls to operate the session. It does not add the keyboard controls of CLI `record`.
  - Save results and quality warnings also appear in the messages panel.
- `operator="auto"` is the default. When stdin is a terminal, the session asks you to support the leader and follower arms before exiting.
  - Support the arms and press Enter to end with the follower torque off as well.
  - Type `hold` to end with the follower still holding.
  - When the follower has `torque: false`, only the leader confirmation is shown.
  - With `operator=None`, or when stdin is not a terminal, this confirmation is skipped and the follower keeps holding. Setting only `screen=False` does not disable it.
  - If the follower is left holding, support its arms or lower them to a safe pose before switching off its power.

### Automatic task naming

For `task`, you can pass either a string or a function that takes an `EpisodeInfo` and returns a string.

| `EpisodeInfo` field | Contents |
| --- | --- |
| `index` | Episode number in the dataset (number of saved episodes) |
| `number` | Number recorded in this Session |
| `experiment` | Name of the experiment file |
| `previous` | List of tasks saved in this Session |

```python
import itertools

objects = itertools.cycle(["cup", "bottle", "sponge"])

with Session.launch("rakuda2", hardware=True) as s:
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
- Quality limits can be changed in the experiment's `recorder.quality`.
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
- What `infer` returns: joint targets (counts). Either a single step `[17]` or an action chunk `[H, 17]`.

**Node behavior**
- The policy is loaded from a `"module:callable"` reference and run by the policy node inside the dataflow.
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
        return self.model(observation)  # [H, 17]


def load(checkpoint: str) -> MyPolicy:
    return MyPolicy(checkpoint)
```

```python
with Session.launch(
    "rakuda2/experiment_policy",
    hardware=True,
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
- Steps that move motors and steps that write the EEPROM require `hardware=True`.

```python
from roboloom import setup
from roboloom.operator import TerminalOperator

op = TerminalOperator()
plan = setup.plan_commission("rakuda2/experiment_gravity", "leader", hardware=True)
for line in plan.lines():
    print(line)
setup.apply_commission(plan, op)  # write after confirmation

fit = setup.identify_gravity(
    ".roboloom/rakuda2/calibration/leader_right.yaml",
    ".roboloom/rakuda2/calibration/gravity_right.yaml",
    op,
    collect=True,
    hardware=True,
)
for joint in fit.joints:
    print(joint.joint, f"{joint.explained:.0%}")
```

```python
# tune gravity compensation without the screen (e.g. automation that tries values in turn)
tuning = setup.open_tuning(
    "rakuda2/experiment_gravity", "leader", "right_arm", hardware=True
)
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

## 3. Run in a single process: `Experiment`

- `Experiment` performs robot bus access, sensor reads, and controller calls all on the caller's thread.
- Use cases:
  - Tests
  - Simulation
  - Simple robots with few sensors
- A policy can be passed directly to `step(policy=...)`.
  - However, if the policy or sensors are slow, the control period is delayed too.
- Run the real Rakuda-2 with `Session`.
  - `from_yaml` rejects experiments that use a motor-controlling leader (trigger spring, gravity compensation).
  - `from_yaml` also rejects experiments that use a policy controller.

This mock example uses no devices or sample files from the repository. The `record` extra is required. Do not reuse its joint ranges or speeds on hardware.

```python
from roboloom import Experiment
from roboloom.drivers.mock import MockBus

with Experiment.from_components(
    robot_id="my-mock",
    robot=MockBus(dimension=2),
    joint_names=["j1", "j2"],
    limits=[
        {"name": "j1", "min": 0, "max": 4095, "max_speed": 3000, "max_jump": 400},
        {"name": "j2", "min": 0, "max": 4095, "max_speed": 3000, "max_jump": 400},
    ],
    controller=lambda obs: [2048, 2048],
    output="datasets/my-mock",
    repo_id="local/my-mock",
) as experiment:
    experiment.start_episode("handover")
    experiment.run(3.0)
    experiment.stop_episode()
    experiment.save_episode()
```

For the data collection procedure on real hardware, see [Rakuda2 Quick start](../quick-start/rakuda2.md).
