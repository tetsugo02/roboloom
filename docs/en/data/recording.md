# Recording and resuming

How episodes are saved or discarded, and what a saved dataset keeps. The recorder's keys are in [Recorder configuration](../reference/configuration/recorder.md#recorder) and the command in the [CLI](../reference/cli.md#record).

## Saving and discarding { #save-and-discard }

- An episode begins with `start` and stops with `stop`. A stopped episode is then saved with `save` or dropped with `discard`. `roboloom record` and `Session.record` save it after stopping ([Choosing which episodes to keep](#choosing-episodes)).
- `save` queues the stopped episode by default in a dora dataflow. With `background_save: false`, it waits for the dataset write to finish. `InProcessSession` always saves synchronously.
- An episode in which a controller fails (a policy raising, for example) or a follower latches FAULT or ESTOP is discarded.
- The Python calls are in [Session](../reference/python-api/session.md).

## Background saving { #background-saving }

<span class="status status--mock">Mock only</span> Checked with mock dataflows and synthetic frames. The default applies to `roboloom run`, `roboloom record` and Python `Session`.

```mermaid
sequenceDiagram
  participant O as Operator / Session
  participant R as Recorder
  participant S as Saver thread
  participant D as LeRobot dataset
  O->>R: start → record → stop
  O->>R: save
  R->>S: enqueue ready spool
  R-->>O: queued, recorder idle
  par Next episode
    O->>R: start (if below limit)
  and Background save
    S->>D: import and commit
    S-->>O: saved or error
  end
```

| Step | What happens |
| --- | --- |
| `start` → `stop` | The recorder stages the episode under `<dataset root>/roboloom_spool/<seq>/`. During recording it writes PNGs for 2D `uint8` images and `uint8` images with 3 or 4 channels, and `.npy` for other image arrays. `stop` finishes the image writes and writes the buffered non-image features to `rows.npz`. |
| `save` | Publishes `episode.json` with `ready: true` and returns once queued. One saver thread imports episodes in order using the save journal and removes each episode's spool directory after processing it. |
| Next `start` | Can follow immediately if the recorder and controllers are ready and `pending_saves < max_pending_saves`. The count includes the active save. At the limit the message is `N episodes are waiting to be saved (max_pending_saves M); wait, then retry start`. |
| Save failure | The dataset returns to its pre-save state and only that episode is dropped. The error arrives later in the log or as a `Session` error note, possibly during the next recording. Later queued episodes continue saving. |
| `quit` / `Session.close()` | Discards the unfinished episode and waits for queued saves to finish. `Session.close()` reports `saving N queued episodes ...` when it finds saves still pending. |

After a recorder process dies, reopen the same dataset for recording. The recorder rolls back any interrupted dataset write, removes unfinished spool episodes (including stopped episodes that were never queued), and queues the accepted episodes for import. The warning `N episodes left from an interrupted run are being saved` gives the number queued for recovery. An episode that committed before the process died is kept once, even if spool cleanup was interrupted. This recovery also runs with `background_save: false`.

Before uploading or training, finish the session and check `roboloom check-dataset` for an `episode spool:` note. If there are ready or unfinished episodes, reopen the dataset for recording and quit to finish recovery, then check again. `--recover` repairs an interrupted dataset write only. See [Checking a dataset](check-and-train.md#check-dataset).

To save synchronously, set `background_save: false` in [nodes/recorder.yaml](../reference/configuration/recorder.md#recorder). This setting is also required with `streaming_encoding: true`.

## Resuming { #resuming }

You can append further episodes to the same dataset. On resume, FPS and feature compatibility are checked. Give an option that changes the recorded features a `dataset`, so it gets a dataset of its own ([Launch options](../reference/configuration/index.md#launch-options)).

## What happens to a saved episode { #saved-episodes }

- A completed save closes the episode's files. Once reported as saved, the episode stays readable even if the process is killed afterwards.
- So the rows, the episode metadata and each video are one file per episode (the layout LeRobot produces when `resume` is called for every episode). To merge the files before uploading to the Hub, use LeRobot's aggregation tools.
- When a save fails (for example the disk is full), that episode is dropped and the dataset is put back as it was before the save. The earlier episodes stay, and the next episode can be recorded.
- When a process stops during a dataset write, the save journal rolls back the partial write when recording resumes or with `check-dataset --recover`. [Background saving](#background-saving) reimports accepted spool episodes when recording resumes.
- A video that is not as long as the episode's rows (for example a frame could not be written) counts as a failed save.
- This covers a process that dies. It does not cover a power loss (LeRobot does not sync its files to the disk).

## Dataset metadata { #metadata }

`meta/roboloom.json` keeps the roboloom version that created the dataset, the unit of every entry of `action` and `observation.state`, and, for every run that saved an episode, its options and configuration (`meta/roboloom_config/<name>.json`, the nodes' values as loaded). Files a node file points to (gravity models, tuning, calibration) are not copied.

## Episode records { #episode-records }

After the dataset write succeeds, the recorder attempts to append one line (JSON) to `meta/roboloom_episodes.jsonl`. The dataset commit can survive an interrupted or failed append to this file.

| Key | Content |
| --- | --- |
| `episode` | The episode's index in the dataset |
| `saved` | When it was saved |
| `task`, `frames` | The task and the number of rows |
| `metrics` | The recorder's metrics (missing rates, the share of valid actions, the control interval) |
| `controllers` | What each controller reported when `save` was requested. For a policy: `infer_ms` and `infer_max_ms` (inference time), `dropped` (the steps asynchronous inference dropped as late), `error`, and so on |
| `label`, `note` | The evaluation verdict (`success` or `failure`; `null` when none was given) and a note |

- A verdict is given when saving: `save(label=...)` and `record(..., label=...)` in Python ([Recording an evaluation's verdicts](../policy/evaluation.md#labels)), `save success` or `save failure` in the operator screen's command box or the `--plain` line input, `roboloom session save success` from another terminal.
- To set or change it afterwards, use `roboloom label [robot] <episode> success|failure` ([CLI](../reference/cli.md#label)). It appends a `{"episode", "label", "labelled", "note"}` line; reading merges the lines of an episode, later ones winning. No line is ever rewritten.
- `roboloom check-dataset` counts the verdicts.
- LeRobot does not read this file; training is unaffected. An episode whose save failed, or that was discarded, has no line.
- From Python, `roboloom.recording.episodes.read(...)` reads it ([Python API: recording](../reference/python-api/recording.md)). An example that picks the episodes to train on is in [Leaving out bad episodes](check-and-train.md#excluding-episodes).

## Choosing which episodes to keep { #choosing-episodes }

- `record` calls `keep(result)` after stopping and before saving.
  - If it returns `False`, the episode is discarded.
- What `result` contains:
  - `metrics`: recorder metrics. Missing rate, valid action rate, control period distribution.
  - `warnings`: items that exceeded quality limits. `result.ok` is true when there are none.
- Quality limits can be changed in `quality` of `nodes/recorder.yaml` ([Quality limits](../reference/configuration/recorder.md#quality)).
  - `max_missing_rate` (default 0.05)
  - `min_action_valid_rate` (default 0.9)
  - `max_interval_ms` (default 100)
- `control_interval_ms` and `action_missing_rate` (the share of rows without a command) are per follower, and warnings name the follower.

```python
ok = s.record("pick up the cup", 30, keep=lambda ep: ep.ok)
```
