# Recording and datasets

With the `record` extra, episodes are saved as **LeRobotDataset 0.6.1** (format v3.0) at
`output` (relative to `config.yaml`) under `repo_id`, both suffixed by enabled options'
`dataset` names. `task` is stored in every frame and works as the language instruction.

## Features

| Feature | Content |
| --- | --- |
| `observation.state` | every follower's joint positions, joined in configuration order; `names` are `<follower>.<joint>` |
| `observation.effort` | followers with `record_effort: true`; units must not mix (N·m vs mA is refused) |
| `observation.images.<sensor>` | camera/tactile images, HWC uint8 RGB (stored as video) |
| `observation.<input>` | input samples, e.g. a Pika Sense pose (10 values) |
| `action` | first command each follower sent in the row's interval, same order as state |
| `action.valid` | 1 when every follower sent a command in that row |
| `action.clamped` | 1 when any follower clipped its command to `max_speed` |
| `action.meta.<follower>.valid/clamped/seq/sent_ns` | per-follower details |

- Rows without a command hold the follower's kept target (not zeros). LeRobot training
  ignores `action.valid`; filter by it yourself if you only want valid rows.
- Missing observations are zeros plus validity flags. Timestamps distinguish capture,
  availability, reception and sending (monotonic clock).
- A row is final once every follower's commands passed its interval or after `grace_ms`
  (500 ms).

## Quality warnings

`recorder.quality` in `nodes/recorder.yaml`:

| Key | Default |
| --- | --- |
| `max_missing_rate` | 0.05 |
| `min_action_valid_rate` | 0.9 |
| `max_interval_ms` | 100 |

Results (`EpisodeResult.metrics`, `.warnings`) report missing rate, valid action rate and
per-follower control intervals. Use `keep=lambda ep: ep.ok` to drop warned episodes.

## Appending and resuming

New episodes append to the same dataset across runs. On resume, FPS and features are
checked; a mismatch is refused. **Do not delete data to get around it** – change `output`,
or give the option that changed the features a `dataset` name.

## Training

```bash
uv add 'roboloom[policy,train]'
uv run lerobot-train \
  --dataset.repo_id=local/rakuda2-digit \
  --dataset.root=.roboloom/rakuda2/datasets/rakuda2-digit \
  --policy.type=act --policy.device=cuda --policy.push_to_hub=false \
  --wandb.enable=false --output_dir=outputs/train/act_rakuda2
```

`--dataset.repo_id` = the configuration's `repo_id` (with option suffixes);
`--dataset.root` = its `output` seen from the project root. See [policy.md](policy.md).
