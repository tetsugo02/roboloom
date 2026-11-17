# Your own policy

roboloom fixes no model form. A policy is an object with `reset()` and `infer(observation)`: it gets the same observation as the recording and returns absolute joint targets. For LeRobot checkpoints, see [LeRobot policies](lerobot.md).

## The policy's shape { #interface }

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

- **Observation**: the keys are the recorded dataset's features (`observation.state`, `observation.images.<name>`, `observation.<input name>` and so on). The values are numpy arrays; images are uint8 `[h, w, 3]` (RGB). `task` is passed too. The features are listed in [Dataset features](../reference/dataset-features.md#observation).
- **Output**: joint targets in the order and units of the recorded `action` (the followers joined in configuration order). One step `[n]` or a chunk `[H, n]`.
- Each robot's observation names and sizes, and the action's order, size and units, are on its page ([Rakuda2](../robots/rakuda2/index.md), [PiPER](../robots/piper/index.md) in development).
- **`bind(spec)` (optional)**: called once after loading, before any episode. `spec` (`roboloom.policy.PolicySpec`) holds:
  - `observation`: `dtype`, `shape` and `names` per observation name
  - `action`: the names of the action's entries (`left.joint1`, …, `right_gripper.gripper`)
  - `rate_hz`, `dataset_fps`

  Raise when the configuration differs from what the policy was trained on. The controller turns `failed`, shows the reason on the screen and starts no episode. `roboloom infer` and `Session.wait_ready` stop at once with the reason instead of waiting. Policies without `bind` work as before.

The Python types and functions are in [Python API: policy](../reference/python-api/policy.md).

## Selecting observations { #observations }

The Rakuda2 template passes joint state and RealSense to the policy without DIGIT. Set `observe` in `nodes/policy.yaml` to match the training inputs. Follower joint state is always included.

| Observations passed to the policy | `observe` | Enabled options |
| --- | --- | --- |
| Joint state + RealSense (default) | `[camera]` | `policy` |
| Joint state + RealSense + left/right DIGIT | `[camera, digit_left, digit_right]` | `digit`, `policy` |
| Joint state only | `[]` | `policy` |

Enabling `digit` alone does not change the policy inputs. Sensors added to `observe` must also exist in `sensors`. Removing a sensor from `observe` still opens and records it if it remains in `sensors`. For a configuration without a camera, also remove `camera` from `sensors` in `config.yaml`. To select per launch, see [Sensor selection](run.md#sensor-selection).

A policy trained with DIGIT inputs cannot simply run unchanged without them. Use a policy trained without DIGIT inputs. The LeRobot loader refuses missing required inputs before starting. Custom policies can implement the same check with `bind(spec)`.

Package updates do not overwrite existing project configurations. `roboloom init rakuda2 --update` adds the files a project lacks (`nodes/policy.yaml` and the like) and lists the options its `config.yaml` lacks. To migrate an older template, remove `requires: [digit]` from `options.policy` in `config.yaml` and set `observe: [camera]` in `nodes/policy.yaml`. Evaluation runs save to `datasets/rakuda2-eval` without DIGIT, or `datasets/rakuda2-digit-eval` with `digit` enabled.

## When the policy fails during an episode { #failures }

- When `infer` or `reset` raises, the controller stops sending commands and turns `failed`; the followers hold. The reason shows on the controller's row of the screen.
- `roboloom infer`, `Session.record` and the timed runs of the operator screen discard that episode (it is not saved). `Session.record` raises `EpisodeFailed`.
- Once `stop` or `discard` has ended the episode, the policy is `ready` again. No restart is needed: the next `start` begins with `policy.reset()`. The reason stays on the screen until that `start`.
- A policy that did not load (including a `bind` that raised) stays `failed`. Fix it and launch again.
- An episode in which a follower latched FAULT or ESTOP is discarded in the same way.

## History, joints left alone, and fresh samples { #hold }

What a model needs beyond the latest frame is asked from the controller, so a new model does not rebuild it. Normalization, resizing and turning the model's own action form (deltas, a subset of joints) into joint targets stay in the policy.

```yaml
observation_history: 4                       # default 1: only the latest frame
hold: [follower.torso_yaw, follower.head_yaw, follower.head_pitch]  # default []
```

- **`observation_history: N`**: the observation is sampled once per action (every `1/rate_hz`), also for the actions of a chunk that need no inference. `infer` then also gets `observation["history"]`: every array of the observation stacked `[N, ...]`, oldest first, the current frame last. At the start of an episode the first frame fills the history. `history["action"]` (float32 `[N, n]`) is the action executed before each frame (the targets the followers held at the start): the command sent to the followers, as the recorder writes it to `action`, so a policy output cut by `max_speed` appears as the cut value. It is for models that read their past actions. With `N = 1` the observation is unchanged.
- **`hold`**: entries of the action (`<follower>.<joint>`) the policy does not drive. Whatever the policy returns there, NaN included, is replaced by the target the follower holds, so a model trained on some of the joints still returns `[n]` or `[H, n]`. Every other entry must be finite, or the episode stops. The recorded `action` keeps those entries; a hook with an explicit write claim may change them after hold substitution ([Dataset format](../data/format.md#by-configuration)).
- **`options()` (optional)**: a policy states these itself, and its values win over the YAML. Swapping the model then needs no edited configuration.

    ```python
    def options(self) -> dict:
        return {
            "observation_history": 4,
            "hold": ["follower.torso_yaw"],
            "action_horizon": 8,
        }
    ```

- `bind(spec)` also receives `spec.history`, `spec.hold`, `spec.units` (the unit of each action entry) and `spec.inference` (`sync` or `async`).
- **Fresh samples only**: an observed input or sensor whose latest sample is older than the recorder's `max_age_ms.<node>` stops the policy (`stale_observation` on the controller's line): nothing is sent and the followers hold, also between two actions of an interpolation. Once the sample is fresh again, the policy starts over with `reset()`. `max_age_ms` is described in [Recorder configuration](../reference/configuration/recorder.md#recorder).

## From a recording to your own model { #from-recording-to-model }

roboloom fixes no model form. It hands the policy the recorded observation, its history and the executed actions, and takes absolute joint targets back; everything specific to a model belongs to the policy:

| Step | Where |
| --- | --- |
| Which joints the model drives | the policy returns anything (NaN) for the others and names them in `hold` |
| Normalization (statistics from the training data) | the policy; keep the statistics with the checkpoint |
| Resizing or cropping images, other preprocessing | the policy |
| Action form: offsets from the state, a subset of joints | the policy turns it back into absolute targets in `infer` |
| Observation history, past actions | roboloom (`observation_history`) |
| A lower action rate than the recording | train on every k-th row and set `rate_hz` to `dataset_fps / k` |
| Interpolation to the control rate, speed limit, safety checks | roboloom |

`examples/policies/chunk_mlp.py` in the repository is a small model that does each of these steps (joint state only, trains on a CPU in seconds): it reads the recorded dataset's `observation.state` and `action` columns, trains, keeps the statistics, the kept joints and the history length in the checkpoint, and states them to roboloom with `options()`.

```bash
uv run python examples/policies/chunk_mlp.py train \
    --dataset .roboloom/rakuda2/datasets/rakuda2 --out outputs/chunk_mlp.pt \
    --history 4 --horizon 8 --stride 3 --exclude torso_yaw head_yaw head_pitch
PYTHONPATH=$PWD/examples/policies uv run roboloom infer rakuda2 --seconds 20 \
    --policy chunk_mlp:load --policy-kwargs "{\"checkpoint\": \"$PWD/outputs/chunk_mlp.pt\"}"
```

With `--stride 3` on a 15 fps recording the policy's rate is 5 Hz: set `rate_hz: 5` in `nodes/policy.yaml`. Reading the dataset for training: the table columns (`observation.state`, `action`, `action.valid`, `episode_index`, `index`) are in `LeRobotDataset(...).hf_dataset`; images are decoded per row with `dataset[i]`. Rows whose `action.valid` is 0 are described in [Missing data](../data/format.md#missing-data).

## Hooks { #hooks }

<span class="status status--mock">Mock only</span>

A policy may provide `hooks() -> Sequence[Hook]` after bind. Implement `Hook.step(action, ctx)` for local action-period processing and `on_episode_ended(event)` for finalization. Writing hooks require a `hooks:` YAML entry with `from: policy` and the write limit. Holds are substituted before hooks; explicitly claimed held joints can be changed. See [Hooks](hooks.md) for the release gate and [threading](../explanation/hooks.md#threading) before sharing state with async inference.
