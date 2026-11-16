# Recording and resuming

How episodes are saved or discarded, and what a saved dataset keeps. The recorder's keys are in [Recorder configuration](../reference/configuration/recorder.md#recorder) and the command in the [CLI](../reference/cli.md#record).

## Saving and discarding { #save-and-discard }

- An episode begins with `start` and stops with `stop`. A stopped episode is then saved with `save` or dropped with `discard`. `roboloom record` and `Session.record` save it after stopping ([Choosing which episodes to keep](#choosing-episodes)).
- An episode whose `save()` returned stays readable even if the process stops afterwards ([What happens to a saved episode](#saved-episodes)).
- An episode in which a controller fails (a policy raising, for example) or a follower latches FAULT or ESTOP is discarded.
- The Python calls are in [Session](../reference/python-api/session.md).

## Resuming { #resuming }

You can append further episodes to the same dataset. On resume, FPS and feature compatibility are checked. Give an option that changes the recorded features a `dataset`, so it gets a dataset of its own ([Launch options](../reference/configuration/index.md#launch-options)).

## What happens to a saved episode { #saved-episodes }

- Every save closes the episode's files. An episode whose `save` succeeded stays readable even if the process is killed afterwards.
- So the rows, the episode metadata and each video are one file per episode (the layout LeRobot produces when `resume` is called for every episode). To merge the files before uploading to the Hub, use LeRobot's aggregation tools.
- When a save fails (for example the disk is full), that episode is dropped and the dataset is put back as it was before the save. The earlier episodes stay, and the next episode can be recorded.
- When the process stops in the middle of a save, the half-written episode is removed the next time the dataset is opened (`run`, `record`, or `check-dataset --recover`).
- A video that is not as long as the episode's rows (for example a frame could not be written) counts as a failed save.
- This covers a process that dies. It does not cover a power loss (LeRobot does not sync its files to the disk).

## Dataset metadata { #metadata }

`meta/roboloom.json` keeps the roboloom version that created the dataset, the unit of every entry of `action` and `observation.state`, and, for every run that saved an episode, its options and configuration (`meta/roboloom_config/<name>.json`, the nodes' values as loaded). Files a node file points to (gravity models, tuning, calibration) are not copied.

## Episode records { #episode-records }

Every save appends one line (JSON) to the dataset's `meta/roboloom_episodes.jsonl`.

| Key | Content |
| --- | --- |
| `episode` | The episode's index in the dataset |
| `saved` | When it was saved |
| `task`, `frames` | The task and the number of rows |
| `metrics` | The recorder's metrics (missing rates, the share of valid actions, the control interval) |
| `controllers` | What each controller reported when the episode was saved. For a policy: `infer_ms` and `infer_max_ms` (inference time), `dropped` (the steps asynchronous inference dropped as late), `error`, and so on |
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
