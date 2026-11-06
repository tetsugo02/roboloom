# Hand-held collection with Pika Sense

!!! warning "In development"
    Notes on collecting with Pika Senses held in the hands, without a robot (after UMI). Checked only with mock Senses and mock cameras; not run on hardware. Inference that drives PiPER with the collected data does not exist yet.

## How it works

1. **Recording**: a configuration without followers records each Sense's absolute pose, jaw angle, tracking and engaged, and the Sense's fisheye camera. The dataset has no `action`.
2. **Conversion**: `roboloom convert-handheld` turns the recording into a new training dataset. Actions and state are poses relative to the Sense itself, so the tracker's frame need not be registered to a robot base.
3. **Training**: the converted dataset trains with `lerobot-train` as it is.

The recording keeps the raw values, so the same recording can be converted again another way.

## Configuration

`.roboloom/pika-handheld-mock/` has two mock Senses (`left_sense`, `right_sense`) and their fisheye cameras (`left_wrist`, `right_wrist`).

```yaml
inputs:
  left_sense: nodes/left_sense.yaml
  right_sense: nodes/right_sense.yaml
followers: {}  # none: nothing is driven, and the dataset has no action
sensors:
  left_wrist: nodes/left_wrist.yaml
  right_wrist: nodes/right_wrist.yaml
```

- A configuration without followers cannot have controllers.
- Inputs and sensors need their own rate: `poll_hz` for a Sense (e.g. 100), `fps` for a camera. Without followers there is no rate to borrow.
- A Sense is written as in [Teleoperation with Pika Sense and IK](pika-sense.md); the cameras are `v4l2_rgb` as in [Pika wrist cameras](pika-cameras.md).

## Recording

```bash
uv run roboloom record pika-handheld-mock --task "pick" --seconds 15 --episodes 5 --plain
uv run roboloom run pika-handheld-mock     # with the operator screen
```

`observation.<Sense>` has 10 entries.

| Name | Unit | Meaning |
| --- | --- | --- |
| `x`, `y`, `z` | m | position in the tracker's world frame |
| `qx`, `qy`, `qz`, `qw` | quaternion | orientation |
| `gripper` | rad | jaw angle |
| `tracking` | 0/1 | whether the pose is tracked now; in rows with 0 the pose is the last tracked one |
| `engaged` | 0/1 | the state the Sense's button toggles |

## Conversion

```bash
uv run roboloom convert-handheld pika-handheld-mock --action delta
uv run roboloom convert-handheld pika-handheld-mock --action relative-chunk --horizon 16
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--action` | `delta` | how actions are expressed (table below) |
| `--horizon` | 16 | the steps H of `relative-chunk` |
| `--hands` | every recorded pose | the Senses to use (e.g. `left_sense,right_sense`) |
| `--max-gap` | 3 | the longest untracked gap filled (rows); episodes with longer gaps are left out, with the reason |
| `--output` | `<recording's output>-<action>` | where to write (refused if it exists) |
| `--repo-id` | `<repo_id>-<action>` | the new dataset's name |

Let P[t] be the Sense's pose in row t. A relative pose is 9 numbers: the position (3) and the rotation's 6D form (the first two columns of the rotation matrix, 6).

| Form | `action` (per Sense) | When |
| --- | --- | --- |
| `delta` | inv(P[t])·P[t+1] and the jaw at t+1: 10 entries | LeRobot's ACT and Diffusion work unchanged. A chunk becomes targets by chaining the steps from the observed pose; errors tend to add up along the chunk |
| `relative-chunk` | inv(P[t])·P[t+k] and the jaw at t+k for k=1..H: H×10 entries in one row | UMI's form; errors do not add up. Train with `chunk_size=1` in LeRobot. ACT works; Diffusion is awkward |

`observation.state` is, per Sense, inv(P[t])·P[t-1] (a cue for velocity) and the jaw at t (10 entries), plus, with two or more Senses, each further Sense's pose seen from the first (9). With two Senses it has 29 entries.

- Untracked rows are filled up to `--max-gap` rows: inside a gap, the position linearly and the rotation by slerp; at an episode's ends, the nearest tracked pose.
- The images, the raw `observation.<Sense>` and `observation.meta.*` stay. Videos are copied, not re-encoded.
- How the dataset was made (form, H, Senses, fps, episodes left out) is kept in `meta/roboloom_handheld.json`.

## Training

```bash
uv sync --extra policy --extra train
# delta
uv run lerobot-train --dataset.repo_id=local/pika-handheld-mock-delta \
  --dataset.root=.roboloom/pika-handheld-mock/datasets/pika-handheld-mock-delta \
  --policy.type=act --policy.push_to_hub=false --wandb.enable=false \
  --output_dir=outputs/train/act_handheld_delta
# relative-chunk
uv run lerobot-train --dataset.repo_id=local/pika-handheld-mock-relative-chunk \
  --dataset.root=.roboloom/pika-handheld-mock/datasets/pika-handheld-mock-relative-chunk \
  --policy.type=act --policy.chunk_size=1 --policy.n_action_steps=1 \
  --policy.push_to_hub=false --wandb.enable=false \
  --output_dir=outputs/train/act_handheld_chunk
```

Before training on a GPU, check with `labstatus` that a GPU is free. "Training with LeRobot" in [Driving with a policy](../controllers/policy.md) shows how to check the path on CPU.

## Limitations

- Not checked on hardware (Sense, libsurvive, base stations, fisheye cameras).
- Whether the fisheye camera sits in the same place relative to the jaws on the Sense and on the Pika Gripper has not been measured. If it does not, a trained policy will not match the Gripper's images.
- Inference that drives PiPER with a trained policy (turning relative poses into targets, then joints by IK) does not exist yet.
- Motions PiPER cannot perform (joint limits, singular poses) are not filtered out.
- Actions are not advanced to cover inference delay (UMI's latency matching).
- The mock Senses move the same way, left and right.
