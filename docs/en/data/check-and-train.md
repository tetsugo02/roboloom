# Checking and training

How to check a recorded dataset before training, leave out episodes you do not want, and train with LeRobot.

## Checking a dataset { #check-dataset }

`roboloom check-dataset [robot]` checks a dataset by reading it only ([CLI](../reference/cli.md#check-dataset)). Name a robot (with `--with` / `--without` as recorded) or a dataset directory.

```bash
uv run roboloom check-dataset --with policy
```

| Output | Content |
| --- | --- |
| Summary | Episodes, rows, fps, robot, the roboloom version that recorded it, file counts; with episode records, the verdict counts (`labels: 7 success, 3 failure, ...`) |
| `problems` | What is broken: unreadable files, counts that disagree between `info.json` and the episode metadata, episode indices with gaps, missing videos and videos that do not match their rows, a half-written episode |
| `notes` | What to know before training: the share of rows that are 0, per `*.valid` column; the share of rows whose `action` is all zeros (recorded before rows without a command kept the held target) |
| `episode spool:` (in `notes`) | Counts ready and unfinished episodes still in the [spool](recording.md#background-saving) <span class="status status--mock">Mock only</span> |

- With `problems`, the command exits with code 1.
- If a dataset write was interrupted, `--recover` rolls it back before checking. Reopening the dataset for recording also rolls it back and processes any remaining spool episodes ([What happens to a saved episode](recording.md#saved-episodes)).
- <span class="status status--mock">Mock only</span> Before upload or training, finish the recording session and check for an `episode spool:` note even when `problems: none` appears. If there are spool episodes, reopen the dataset for recording, let the recorder finish, then check again.
- What `valid` means is in [Validity flags](format.md#valid); the values of rows that are 0 are in [Missing data](format.md#missing-data).

## Leaving out bad episodes { #excluding-episodes }

The per-episode metrics ([Episode records](recording.md#episode-records)) tell which episodes to train on.

```python
from roboloom.recording import episodes

records = episodes.read(".roboloom/rakuda2/datasets/rakuda2")
keep = [
    index
    for index, record in sorted(records.items())
    if record.get("metrics", {}).get("action_valid_rate", 0) >= 0.9
]
print(keep)
```

Pass the indices to `lerobot-train` as `--dataset.episodes`, and it trains on those episodes only.

```bash
uv run lerobot-train \
  --dataset.repo_id=local/rakuda2 \
  --dataset.root=.roboloom/rakuda2/datasets/rakuda2 \
  --dataset.episodes='[0, 1, 3, 4]' \
  --policy.type=act --policy.device=cuda --policy.push_to_hub=false \
  --trackio.enable=false \
  --output_dir=outputs/train/act_rakuda2
```

- `--dataset.episodes` selects rows only. The normalization statistics stay those of the whole dataset (`meta/stats.json`). When the left-out episodes hold outlying values, make a dataset without them instead, as below.
- LeRobot's `lerobot-edit-dataset --operation.type delete_episodes --operation.episode_indices "[2, 5]"` writes a new dataset without those episodes and aggregates the statistics of the kept ones again (`--root`, `--new_root` and `--new_repo_id` give the places). The episodes are renumbered from 0. roboloom's files (`meta/roboloom.json`, `meta/roboloom_episodes.jsonl`) are not copied to the new dataset.
- To recompute the statistics of a whole dataset, use `lerobot-edit-dataset --operation.type recompute_stats`.
- Both need `lerobot[dataset]`, which `--extra train` (`lerobot[training]`) installs. roboloom has not checked these tools; see LeRobot's documentation for their use.
- The `--dataset.*` options of `lerobot-train` have no setting that selects rows by `action.valid` or the like. To select rows, read `LeRobotDataset(...).hf_dataset` and drop them yourself ([Missing data](format.md#missing-data)).

## Training with LeRobot { #training }

A dataset roboloom recorded (LeRobotDataset v3.0) trains with `lerobot-train` as it is. The extras, the command and how to run the trained checkpoint are in [Training with LeRobot](../policy/lerobot.md#training).

- `--dataset.repo_id` is the configuration's `repo_id`; `--dataset.root` is its `output`, from the robot's directory.
- `lerobot-train` does not look at the `*.valid` columns. In rows whose `action.valid` is 0, `action` holds the target each follower keeps.
- Before training on a GPU, check with `labstatus` that a GPU is free.
- An example of training your own model is in [From a recording to your own model](../policy/custom.md#from-recording-to-model).
