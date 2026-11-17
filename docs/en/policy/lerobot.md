# LeRobot policies <span class="status status--mock">Mock only</span>

`roboloom.policy.lerobot:load` is a ready-made policy that loads a checkpoint trained with LeRobot. A dataset roboloom recorded trains with `lerobot-train` as it is.

!!! warning "What has been checked"
    LeRobot policies have been checked only with the mock PiPER + Pika configuration: an ACT trained briefly on CPU with `lerobot-train` on mock recordings ran the whole path from recording to inference. They have not been checked on hardware or with a well-trained policy.

## Loading a checkpoint { #loading }

```yaml
factory: roboloom.policy.lerobot:load
kwargs:
  path: /path/to/project/outputs/train/act_piper/checkpoints/last/pretrained_model  # or a Hub ID
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

- Loading follows LeRobot 0.7.0's rollout. The config, the weights and the saved pre- and post-processors (with the normalization statistics) all come from the checkpoint.
- On loading, the checkpoint's inputs and outputs are checked against this configuration's observation and followers. A missing observation or a different size is refused, naming it.
  - The inputs checked are the ones LeRobot policies read (`observation.state`, `observation.images.*`, `observation.environment_state`).
  - LeRobot's training lists every `observation.*` of the dataset as an input (`observation.meta.*`, `observation.effort`, a Pika Sense's `observation.left_sense` and so on). LeRobot policies do not read them, so the inference configuration need not have them.
  - The output checked is the size of `action`.
- Requirements: `uv add 'roboloom[policy]'` (in this repository, `uv sync --extra policy`). torch comes with it. ACT needs nothing more. Diffusion needs `lerobot[diffusion]`, SmolVLA `lerobot[smolvla]` and pi0 `lerobot[pi]` as well.
- Before running inference or training on a GPU, check with `labstatus` that a GPU is free.
- ACT's temporal ensembling (`temporal_ensemble_coeff`) works only with `mode: step` ([Limitations](index.md#limitations)).

## Training with LeRobot { #training }

A dataset roboloom recorded (LeRobotDataset v3.0) trains with `lerobot-train` as it is.

```bash
# training needs lerobot[training] (accelerate, trackio)
uv add git+https://github.com/tetsugo02/roboloom.git --tag v0.2.0 --extra policy --extra train   # in your own project
uv sync --extra policy --extra train                                                # in a checkout of the roboloom repository
uv run lerobot-train \
  --dataset.repo_id=local/piper-mock \
  --dataset.root=.roboloom/piper-mock/datasets/piper-mock \
  --policy.type=act --policy.device=cuda --policy.push_to_hub=false \
  --trackio.enable=false \
  --output_dir=outputs/train/act_piper_mock
```

- `--dataset.repo_id` is the configuration's `repo_id`; `--dataset.root` is its `output`, from the robot's directory.
- The trained checkpoint is `<output_dir>/checkpoints/last/pretrained_model`. Pass it as `path`. The names are those recorded, so no `rename` is needed.
- `lerobot-train` counts every `observation.*` of the dataset as an input and every `action*` as an output (`observation.meta.*`, `observation.effort`, `action.valid`, `action.meta.*` and so on). ACT reads only `observation.state`, the images and `action`; the rest is used neither in training nor in inference.
- In rows where `action.valid` is 0 (for example while the input is not engaged), `action` holds the target each follower keeps. The policy learns to stay still there. LeRobot does not select rows by the `valid` columns ([Missing data](../data/format.md#missing-data)).
- To check only the path, `--policy.device=cpu --steps=200 --batch_size=8` takes a few minutes. Without a network, `--policy.pretrained_backbone_weights=null` skips downloading the backbone weights (training gets worse).
- Before training on a GPU, check with `labstatus` that a GPU is free.
- Checking a dataset and leaving out bad episodes before training is described in [Checking and training](../data/check-and-train.md).
