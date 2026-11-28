# Running a policy

How to configure the policy node and run a policy with `roboloom infer`. The keys are listed in [Policy configuration](../reference/configuration/policy.md) and the command's options in the [CLI](../reference/cli.md#infer).

## Configuration { #configuration }

```yaml
# nodes/policy.yaml
type: policy
followers: [left, right, left_gripper, right_gripper]  # every follower, in configuration order
factory: demo_policy:wave           # "module:callable" returning the policy
kwargs: {}                          # arguments for the factory
observe: [camera, left_wrist, right_wrist]  # inputs and sensors the policy sees; follower states are always seen
rate_hz: 10                         # one action per 1/rate_hz: the training dataset's dataset_fps
interpolation_multiplier: auto      # commands at rate_hz × this; left out or auto: from the followers' control_hz
action_horizon: 2                   # steps of a chunk to run before asking for the next
max_speed: {left: 1.0, right: 1.0, left_gripper: 3.0, right_gripper: 3.0}  # per follower, in unit/s
command_deadline_ms: 300
```

- The `factory` module is looked up in the installed packages first, then in the robot's directory (`.roboloom/<robot>/`). A policy file kept next to the configuration is imported without `PYTHONPATH`; an installed module of the same name takes precedence.
- The policy and its checkpoint, the options, the dataset, the task and the length go into an [experiment file](../reference/configuration/index.md#experiments) of the project (`configs/roboloom/<name>.yaml`). `roboloom infer --experiment <name>` is then all it takes, and `nodes/policy.yaml` stays as it is.
- `roboloom infer` turns on the option named `policy`. `--policy` and `--policy-kwargs` replace the policy without editing the YAML.
- The template's default policy `roboloom.policy:hold` keeps the arms in place. Use it to check the inference path on hardware for the first time.
- Choosing what the policy observes is described in [Selecting observations](custom.md#observations).

```bash
uv run roboloom infer piper-mock --seconds 20 \
  --policy roboloom.policy.lerobot:load --policy-kwargs "{\"path\": \"$PWD/outputs/act/pretrained_model\"}"
```

!!! note "Use absolute paths"
    The dataflow starts from a temporary directory. Give checkpoint paths in `--policy-kwargs` or in the policy YAML's `kwargs`, and `PYTHONPATH`, as absolute paths (`$PWD/...` in the shell). A relative path is resolved from the temporary directory, not the project, and is not found.

## Rate and steps { #rate-and-steps }

- The policy node takes one action every `1/rate_hz`. When no action is queued, it calls `infer`.
- Set `rate_hz` to the `dataset_fps` of the dataset the policy was trained on. Raising `rate_hz` to command faster would use up the actions faster than in training.
- By default no command is sent during `infer` (synchronous; see [Asynchronous inference](async.md#asynchronous-inference)). When inference takes longer than `command_deadline_ms`, the followers go to HOLD and wait. The controller's row on the screen shows the inference time (`infer_ms`, `infer_max_ms`).
- Between two actions, interpolated targets are sent ([Action interpolation](async.md#interpolation)).

## Starting from a saved pose (home) { #home }

A policy can also move the followers to a saved pose before each episode. Save the pose with `roboloom capture-pose <name>` and add `home:` to `nodes/policy.yaml`.

```yaml
home:
  pose: ../poses/follower/ready.yaml  # roboloom capture-pose ready
  max_speed: 200                      # at most this controller's max_speed (follower unit/s)
  tolerance: 30                       # arrived when every measured joint is this close
  timeout_s: 30                       # optional
```

- With several followers, write one per follower: `home: {left: {...}, right: {...}}`. Followers left out do not move.
- `roboloom infer --home [NAME]` moves before each episode. Omit `NAME` for the configured default. In the launcher, enable `Move home before every episode` and choose a pose. In the operator screen, use [Move home](../reference/operator-screen.md#move-home). In Python, use `Session.home(pose=...)` or `Session.record(..., home=...)`. <span class="status status--mock">Mock only</span>
- Arrival is checked with the measured joints, not the sent target. After the move, `reached` means every joint is within `tolerance`. If one is still out after 2 s, the screen shows `short` with the joint and its difference; `home` fails and `start` is refused.
- As with teleoperation, `home` is refused while recording or following, and `start` is refused while moving home.
- With `teleop:`, `home` moves the leader too ([Teleoperation and interventions](intervention.md#behavior)).

## Running from Python { #python }

The policy node inside the dataflow loads the policy from a `"module:callable"` reference and runs it. From Python, pass the configuration and the policy to `Session.launch` ([Session](../reference/python-api/session.md)). How to write a policy is in [Your own policy](custom.md).

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
from pathlib import Path

from roboloom import Session

with Session.launch(
    "rakuda2",
    options=["policy"],  # joint state + RealSense by default; add "digit" if needed
    policy="my_lab.policies:load",
    policy_kwargs={"checkpoint": str(Path("outputs/act/last").resolve())},
) as s:
    s.wait_ready()  # until the policy has finished loading
    for k in range(10):
        s.record(f"pick up the cup (eval {k})", seconds=30)  # saved as evaluation data
```

- The sensors to observe (`observe`), the rate (`rate_hz`) and how many steps of a chunk run before the next is requested (`action_horizon`) are set in `nodes/policy.yaml`.
- `wait_ready` stops at once with the reason when the policy did not load (including a `bind` that raised).

## Sensor selection <span class="status status--mock">Mock only</span> { #sensor-selection }

The sensors that are opened and recorded and the sensors the policy observes are selected independently, with `load_config(..., sensors=[...], observe=[...])` and `Session.launch(..., sensors=[...], observe=[...])`. `None` keeps the configuration's defaults; `[]` selects none. Follower state is always observed. When passing a `RobotConfig`, select in `load_config`; `Session.launch` rejects additional selection arguments.

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

- On the command line, `--sensors camera,audio --observe camera` makes the same selection; `--sensors "" --observe ""` selects none. The launcher has separate checkboxes for the sensors and the observations and remembers the selection.
- The YAML of an unselected sensor is not loaded. Observing a sensor that is not started fails.
- Sensors that options add can be selected individually too, either DIGIT included. The selection is resolved after the options are applied.
- An optional sensor is declared as `{file: nodes/audio.yaml, default: false}`; plain string paths stay enabled by default.
- A started sensor is recorded even when it is not in `observe`.

The configuration is described in [Sensor selection](../reference/configuration/sensors.md#sensor-selection). See also [Audio](../sensors/audio.md).

## Steps for PiPER + Pika (mock) <span class="status status--dev">In development</span> { #piper-pika }

1. Record with the mock Senses ([Teleoperation with Pika Sense and IK](../controllers/pose-ik.md)).

    ```bash
    uv run roboloom record piper-mock --task "pick" --seconds 15 --episodes 5 --home --plain
    ```

2. Train with LeRobot (`lerobot-train`) on the recorded dataset ([Training with LeRobot](lerobot.md#training)). Check with `labstatus` that a GPU is free before training.
3. Run the trained checkpoint.

    ```bash
    uv run roboloom infer piper-mock --seconds 20 --task "pick" \
      --policy roboloom.policy.lerobot:load \
      --policy-kwargs "{\"path\": \"$PWD/outputs/train/act_piper_mock/checkpoints/last/pretrained_model\"}"
    ```

    With `--task`, the runs are saved as evaluation data.
