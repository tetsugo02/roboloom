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
| `observation.<input>` | each input's reading: a leader's joint positions (`observation.leader`, joint names without prefix) or a pose input's 10 fields (`x`…`qw`, `gripper`, `tracking`, `engaged`) |
| `observation.meta.<node>.valid/capture_age_ms/ready_age_ms` (float32), `seq/capture_ns/ready_ns/receive_ns` (int64) | per recorded node (inputs, followers, sensors): sample used in this row, its ages, sequence number, timestamps |
| `action` | first command each follower sent in the row's interval, same order as state |
| `action.valid` | 1 when every follower sent a command in that row |
| `action.clamped` | 1 when any follower clipped its command to `max_speed` |
| `action.meta.<follower>.valid/clamped/seq/sent_ns` | per-follower details |

- Rows without a command hold the follower's kept target (not zeros). LeRobot training
  ignores `action.valid`; filter by it yourself if you only want valid rows.
- A sample older than `recorder.max_age_ms.<node>` is missing: `observation.meta.<node>.valid` 0, `seq` -1,
  and the value repeats that node's last valid sample (zeros only before its first one).
  Every input, follower and sensor needs an entry; entries for nodes not in the configuration
  (and misspelled names) are ignored.
- Missing observations are the last valid value plus validity flags. Timestamps distinguish capture,
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
or give the option that changed the features a `dataset` name. The same holds for the
video codec: without `video_codec` the saved videos' codec is reused, and a different
explicit one is refused ([configuration](configuration.md#video-codec)).

## What a save guarantees

- Every save closes the episode's files (one data file, one metadata file and one video
  per camera for each episode). An episode whose `save` succeeded stays readable even if
  the process is killed afterwards.
- A save that fails (disk full, a video that does not match the rows) drops that episode
  and puts the dataset back as it was: `save()` raises `SessionError`, the earlier
  episodes stay, the next episode can be recorded.
- A save interrupted by a kill is undone the next time the dataset is opened (`run`,
  `record`, or `roboloom check-dataset --recover`).
- `meta/roboloom.json` holds the roboloom version, the unit of each `action` /
  `observation.state` entry, and each recording run's options and configuration
  (`meta/roboloom_config/`).
- `roboloom check-dataset [robot|dataset dir]` reads a dataset only and lists what is
  broken (exit code 1) and the share of rows whose `valid` is 0. Run it before training
  and after a crash. **Do not repair a dataset by editing its files.**

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
