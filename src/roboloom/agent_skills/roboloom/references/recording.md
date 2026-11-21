# Recording and datasets

With the `record` extra, episodes are saved as **LeRobotDataset 0.7.0** (format v3.0) at
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

## Background saving

**Mock only.** In the dora dataflow (`roboloom run`, `roboloom record`, `Session`),
these keys go in `nodes/recorder.yaml` and ship in the Rakuda2 and PiPER templates.

```yaml
background_save: true
max_pending_saves: 2
streaming_encoding: false
```

- `background_save` defaults to `true`. Set it to `false` for synchronous saves
  (`save` waits, `start` is refused during `saving`). `streaming_encoding: true`
  requires `background_save: false` because its encoder holds one episode.
  `InProcessSession` always saves synchronously.
- During recording the recorder stages images under `<dataset root>/roboloom_spool/<seq>/`
  as PNG (2D or 3-/4-channel `uint8`) or `.npy` (other arrays). `stop` writes the other
  features to `rows.npz`. `save` publishes `episode.json` with `ready: true` and returns
  once queued. One saver thread imports episodes in order using the save journal and
  removes their spool directories.
- `max_pending_saves` is an integer ≥ 1 (default `2`) and counts the active save too.
  Below the limit, `start` can follow a queued `save` as soon as ready. At the limit
  `start` reports `N episodes are waiting to be saved (max_pending_saves M); wait, then retry start`.
  The recorder status includes `pending_saves` and `max_pending_saves`. The screen
  shows `saving N queued` and logs acceptance and completion separately.
- On a write failure the dataset returns to the preceding saved state and the failed
  episode is dropped. The error arrives later and subsequent saves continue.
  `quit` and `Session.close()` wait for the queue. `roboloom record --plain` prints
  the final results after waiting. In the operator screen, read the results in Logs.
- If the recorder process dies, reopen the same dataset for recording. The recorder
  rolls back an interrupted write, removes unfinished spool episodes, and imports
  accepted episodes that had yet to commit. A warning gives the count for import.
  Startup recovery also runs with `background_save: false`.
- Before upload or training, finish the session and check `roboloom check-dataset`
  for the `episode spool:` note. If ready or unfinished episodes remain, reopen for
  recording, allow the recorder to finish, and recheck. `--recover` rolls back an
  interrupted dataset write; reopening for recording processes the spool.

## What a completed save guarantees

- A completed save closes the episode's files. Once reported as saved, the episode
  stays readable across process exit.
- In Python, use `save(wait=True)` to wait for one write, or `wait_saves()` to
  collect all outstanding results. See [python-api.md](python-api.md#fine-grained-control).
- `meta/roboloom.json` holds the roboloom version, the unit of each `action` /
  `observation.state` entry, and each recording run's options and configuration
  (`meta/roboloom_config/`).
- After a dataset commit the recorder attempts to append one JSON line to
  `meta/roboloom_episodes.jsonl`: `episode`,
  `saved`, `task`, `frames`, `metrics`, `controllers` (each controller's status when
  `save` was requested: a policy's `infer_max_ms`, `dropped`, `error`), `label` (`success` /
  `failure` / null) and `note`. Set the verdict when saving (`save(label=...)`,
  `record(..., label=...)`, typed `save success`) or afterwards with
  `roboloom label [robot] <episode> success|failure` (appends a line; later lines win).
  Read it with `roboloom.recording.episodes.read(root)`; LeRobot ignores the file.
- `roboloom check-dataset [robot|dataset dir]` reads a dataset only and lists what is
  broken (exit code 1), the share of rows whose `valid` is 0 and the count of verdicts. Run it before training
  and after a crash. **Do not repair a dataset by editing its files.**

## Training

```bash
uv add 'roboloom[policy,train]'
uv run lerobot-train \
  --dataset.repo_id=local/rakuda2-digit \
  --dataset.root=.roboloom/rakuda2/datasets/rakuda2-digit \
  --policy.type=act --policy.device=cuda --policy.push_to_hub=false \
  --trackio.enable=false --output_dir=outputs/train/act_rakuda2
```

`--dataset.repo_id` = the configuration's `repo_id` (with option suffixes);
`--dataset.root` = its `output` seen from the project root. See [policy.md](policy.md).

## Hook changes (mock only)

`action.filtered`: float32 [1], present only when a policy's YAML hooks list includes
an entry with nonempty writes (factory or from: policy). Schema selection uses YAML
alone; the recorder never imports the hook. All valid sent commands/followers in a row
are ORed, even when the first command was unchanged. The flag reflects hook changes
before interpolation/speed/safety limits; policy teleop carries it too. No writing
claims means no column. Preserve dataset schema compatibility; choose another output
and repo_id for a different feature layout rather than silently appending.
Controller status adds hook_ms, hook_max_ms, hook_errors, hook_over, filtered; per-hook
ms/max_ms/errors/over/changed/notes are logged at end. EpisodeEnded.filtered_steps counts
periods changed by the chain. See [policy](policy.md#local-hooks-mock-only).
