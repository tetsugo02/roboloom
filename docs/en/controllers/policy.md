# Driving with a policy

A `type: policy` controller drives the followers with a learned policy. Policies you write yourself and LeRobot checkpoints are loaded the same way.

!!! warning "What has been checked"
    The path for your own policies is used with the Rakuda2 configuration and with mock devices. LeRobot policies (`roboloom.policy.lerobot`) have been checked only with the mock PiPER + Pika configuration: an ACT trained briefly on CPU with `lerobot-train` on mock recordings ran the whole path from recording to inference. They have not been checked on hardware or with a well-trained policy.

## Configuration

```yaml
# nodes/policy.yaml
type: policy
followers: [left, right, left_gripper, right_gripper]  # every follower, in configuration order
factory: demo_policy:wave           # "module:callable" returning the policy
kwargs: {}                          # arguments for the factory
observe: [camera, left_wrist, right_wrist]  # inputs and sensors the policy sees; follower states are always seen
rate_hz: 10
action_horizon: 2                   # steps of a chunk to run before asking for the next
max_speed: {left: 1.0, right: 1.0, left_gripper: 3.0, right_gripper: 3.0}  # per follower, in unit/s
command_deadline_ms: 300
```

- The `factory` module is looked up in the installed packages first, then in the robot's directory (`.roboloom/<robot>/`).
- `roboloom infer` turns on the option named `policy`. `--policy` and `--policy-kwargs` replace the policy without editing the YAML.

```bash
uv run roboloom infer piper-mock --seconds 20 \
  --policy roboloom.policy.lerobot:load --policy-kwargs '{"path": "outputs/act/pretrained_model"}'
```

## Selecting observations

The Rakuda2 template passes joint state and RealSense to the policy without DIGIT. Set `observe` in `nodes/policy.yaml` to match the training inputs. Follower joint state is always included.

| Observations passed to the policy | `observe` | Enabled options |
| --- | --- | --- |
| Joint state + RealSense (default) | `[camera]` | `policy` |
| Joint state + RealSense + left/right DIGIT | `[camera, digit_left, digit_right]` | `digit`, `policy` |
| Joint state only | `[]` | `policy` |

Enabling `digit` alone does not change the policy inputs. Sensors added to `observe` must also exist in `sensors`. Removing a sensor from `observe` still opens and records it if it remains in `sensors`. For a configuration without a camera, also remove `camera` from `sensors` in `config.yaml`.

A policy trained with DIGIT inputs cannot simply run unchanged without them. Use a policy trained without DIGIT inputs. The LeRobot loader refuses missing required inputs before starting. Custom policies can implement the same check with `bind(spec)`.

Package updates do not overwrite existing project configurations. To migrate an older template, remove `requires: [digit]` from `options.policy` in `config.yaml` and set `observe: [camera]` in `nodes/policy.yaml`. Evaluation runs save to `datasets/rakuda2-eval` without DIGIT, or `datasets/rakuda2-digit-eval` with `digit` enabled.

## Your own policy

Write a function that returns an object with `reset()` and `infer(observation)` (`roboloom.Policy`).

```python
# .roboloom/<robot>/my_policy.py, or an installed package
import numpy as np


class MyPolicy:
    def __init__(self, checkpoint: str): ...

    def bind(self, spec):  # optional; called once, right after loading
        if "observation.images.left_wrist" not in spec.observation:
            raise ValueError("add left_wrist to observe")

    def reset(self): ...  # called when an episode starts

    def infer(self, observation) -> np.ndarray:
        state = observation["observation.state"]  # float32 [n]
        image = observation["observation.images.left_wrist"]  # uint8 [h, w, 3], RGB
        task = observation["task"]
        return self.model(state, image, task)  # [n] or [H, n]


def load(checkpoint: str) -> MyPolicy:
    return MyPolicy(checkpoint)
```

- **Observation**: the keys are the recorded dataset's features (`observation.state`, `observation.images.<name>`, `observation.<input name>` and so on). The values are numpy arrays; images are uint8 `[h, w, 3]` (RGB). `task` is passed too.
- **Output**: joint targets in the order and units of the recorded `action` (the followers joined in configuration order). One step `[n]` or a chunk `[H, n]`.
- Each robot's observation names and sizes, and the action's order, size and units, are on its page ([Rakuda2](../robots/rakuda2.md), [PiPER](../contribution/piper.md) in development).
- **`bind(spec)` (optional)**: called once after loading, before any episode. `spec` (`roboloom.policy.PolicySpec`) holds:
  - `observation`: `dtype`, `shape` and `names` per observation name
  - `action`: the names of the action's entries (`left.joint1`, …, `right_gripper.gripper`)
  - `rate_hz`, `dataset_fps`

  Raise when the configuration differs from what the policy was trained on. The controller turns `failed`, shows the reason on the screen and starts no episode. `roboloom infer` and `Session.wait_ready` stop at once with the reason instead of waiting. Policies without `bind` work as before.

## LeRobot policies

`roboloom.policy.lerobot:load` is a ready-made policy that loads a checkpoint trained with LeRobot.

```yaml
factory: roboloom.policy.lerobot:load
kwargs:
  path: outputs/train/act_piper/checkpoints/last/pretrained_model  # or a Hub ID
  device: auto        # cuda when available, else cpu
  mode: step          # step or chunk
  rename: {}          # {checkpoint name: roboloom name}
action_horizon: 1     # with mode: step
```

| Key | Meaning |
| --- | --- |
| `path` | The checkpoint directory (with `config.json`, `model.safetensors`, `policy_preprocessor.json` and so on) or a Hugging Face Hub ID |
| `device` | `auto` (the default), `cpu`, `cuda` and so on |
| `mode` | `step` (the default): returns one step at a time from LeRobot's `select_action`. The policy keeps its own chunk queue and observation history, so ACT, Diffusion and SmolVLA all run as in LeRobot's rollout. Use it with `action_horizon: 1`. `chunk`: returns a chunk `[H, n]` from `predict_action_chunk` and runs `action_horizon` steps before asking for the next. Only for policies without an observation history (such as ACT) |
| `rename` | Maps the checkpoint's feature names to this configuration's. Example: `{observation.images.wrist: observation.images.left_wrist}` |
| `revision` | The Hub revision (optional) |

- Loading follows LeRobot 0.6.1's rollout. The config, the weights and the saved pre- and post-processors (with the normalization statistics) all come from the checkpoint.
- On loading, the checkpoint's inputs and outputs are checked against this configuration's observation and followers. A missing observation or a different size is refused, naming it.
  - The inputs checked are the ones LeRobot policies read (`observation.state`, `observation.images.*`, `observation.environment_state`).
  - LeRobot's training lists every `observation.*` of the dataset as an input (`observation.meta.*`, `observation.effort`, a Pika Sense's `observation.left_sense` and so on). LeRobot policies do not read them, so the inference configuration need not have them.
  - The output checked is the size of `action`.
- Requirements: `uv add 'roboloom[policy]'` (in this repository, `uv sync --extra policy`). torch comes with it. ACT needs nothing more. Diffusion needs `lerobot[diffusion]`, SmolVLA `lerobot[smolvla]` and pi0 `lerobot[pi]` as well.
- Before running inference or training on a GPU, check with `labstatus` that a GPU is free.

## Training with LeRobot

A dataset roboloom recorded (LeRobotDataset v3.0) trains with `lerobot-train` as it is.

```bash
# training needs lerobot[training] (accelerate, wandb)
uv add git+https://github.com/tetsugo02/roboloom.git --extra policy --extra train   # in your own project
uv sync --extra policy --extra train                                                # in a checkout of the roboloom repository
uv run lerobot-train \
  --dataset.repo_id=local/piper-mock \
  --dataset.root=.roboloom/piper-mock/datasets/piper-mock \
  --policy.type=act --policy.device=cuda --policy.push_to_hub=false \
  --wandb.enable=false \
  --output_dir=outputs/train/act_piper_mock
```

- `--dataset.repo_id` is the configuration's `repo_id`; `--dataset.root` is its `output`, from the robot's directory.
- The trained checkpoint is `<output_dir>/checkpoints/last/pretrained_model`. Pass it as `path`. The names are those recorded, so no `rename` is needed.
- `lerobot-train` counts every `observation.*` of the dataset as an input and every `action*` as an output (`observation.meta.*`, `observation.effort`, `action.valid`, `action.meta.*` and so on). ACT reads only `observation.state`, the images and `action`; the rest is used neither in training nor in inference.
- In rows where `action.valid` is 0 (for example while the input is not engaged), `action` holds the target each follower keeps. The policy learns to stay still there.
- To check only the path, `--policy.device=cpu --steps=200 --batch_size=8` takes a few minutes. Without a network, `--policy.pretrained_backbone_weights=null` skips downloading the backbone weights (training gets worse).
- Before training on a GPU, check with `labstatus` that a GPU is free.

## Rate and steps

- The policy node sends one command every `1/rate_hz`. When no action is queued, it calls `infer`.
- No command is sent during `infer` (synchronous). When inference takes longer than `command_deadline_ms`, the followers go to HOLD and wait. The controller's row on the screen shows the inference time (`infer_ms`, `infer_max_ms`).
- Set `rate_hz` to the `dataset_fps` of the dataset the policy was trained on.
- Targets are cut to `max_speed` from what each follower holds, and `FollowerSafety` checks the joint limits and the deadline, as in teleoperation.

## Limitations

- Asynchronous inference (running the previous chunk while inferring) and LeRobot's RTC are not supported.
- ACT's temporal ensembling (`temporal_ensemble_coeff`) works only with `mode: step`.

## Steps for PiPER + Pika (mock)

1. Record with the mock Senses ([Teleoperation with Pika Sense and IK](../contribution/pika-sense.md)).

    ```bash
    uv run roboloom record piper-mock --task "pick" --seconds 15 --episodes 5 --home --plain
    ```

2. Train with LeRobot (`lerobot-train`) on the recorded dataset ("Training with LeRobot" above). Check with `labstatus` that a GPU is free before training.
3. Run the trained checkpoint.

    ```bash
    uv run roboloom infer piper-mock --seconds 20 --task "pick" \
      --policy roboloom.policy.lerobot:load \
      --policy-kwargs '{"path": "outputs/train/act_piper_mock/checkpoints/last/pretrained_model"}'
    ```

    With `--task`, the runs are saved as evaluation data.

## Sensor selection

`load_config(..., sensors=[...], observe=[...])` and
`Session.launch(..., sensors=[...], observe=[...])` select sensors independently
from policy observations. None keeps configuration defaults; [] selects none.
Follower state is always observed. When passing RobotConfig, select in load_config;
Session.launch rejects additional selection arguments.

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

`--sensors camera,audio --observe camera` makes the same CLI selection;
`--sensors "" --observe ""` selects none. The launcher provides separate
sensor and observation checkboxes and remembers selections.
Unselected sensor YAML files are not loaded. Observing an inactive sensor fails.
Sensors introduced by options can also be selected individually, including either DIGIT.
An optional sensor uses `{file: nodes/audio.yaml, default: false}`; string paths
remain enabled by default. Options apply first. Recording includes every active sensor,
even those omitted from observe. See [Audio](../sensors/audio.md).
