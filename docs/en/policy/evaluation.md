# Evaluation and replay

How to keep whether each policy run succeeded, and how to replay recorded actions through the policy path.

## Recording an evaluation's verdicts { #labels }

Runs saved with `roboloom infer --task <text>` (`record` in Python) go into the evaluation dataset. Whether each run succeeded can be kept in the episode records (`meta/roboloom_episodes.jsonl` in the dataset).

```bash
uv run roboloom infer --seconds 30 --episodes 10 --confirm --task "pick up the cup"
uv run roboloom label --with policy 3 failure --note "missed the grasp"   # afterwards, for episode 3
uv run roboloom check-dataset --with policy                                # labels: 7 success, 3 failure, ...
```

- With `--confirm`, type `save success` or `save failure` in the operator screen's input or at the `--plain` prompt. Use `save` to keep an episode without a verdict or `discard` to repeat its episode number. <span class="status status--mock">Mock only</span>
- For episodes collected with `roboloom run`, type the same save commands in the operator screen or send `roboloom session save success` from another terminal. In Python, use `record(..., label=...)` or `save(label=...)`.
- To set or change a verdict afterwards, use `roboloom label [robot] <episode> success|failure` ([CLI](../reference/cli.md#label)). `roboloom check-dataset` counts the verdicts ([CLI](../reference/cli.md#check-dataset)).
- The record also holds what the policy reported for the run (inference time `infer_max_ms`, the steps asynchronous inference dropped as late `dropped`, its error) and the recorder's metrics. The keys are listed in [Episode records](../data/recording.md#episode-records).
- A run in which the policy failed is not saved, so it has no record.
- LeRobot does not read this file; training is unaffected.

### From Python { #labels-python }

- `record(..., label="success")` and `save(label="failure", note="...")` save the episode with a verdict (`success` or `failure`) and a note.
  - `record` also takes a function as `label`: it receives the stopped episode (`result`) and returns the verdict. Returning `None` saves without one.
  - Any other string raises `ValueError` before anything is saved.
- The recorder writes the [episode record](../data/recording.md#episode-records) with or without a verdict after the dataset write. With [background saving](../data/recording.md#background-saving) <span class="status status--mock">Mock only</span>, call `wait_saves()` before reading the records, or use `save(wait=True)` for one episode.
- To set or change a verdict afterwards, `roboloom.recording.episodes.label(...)` works too ([Python API: recording](../reference/python-api/recording.md)).

```python
from roboloom.recording import episodes

for k in range(10):
    s.record(
        "pick up the cup",
        seconds=30,
        label=lambda ep: "success" if cup_lifted() else "failure",
    )
s.wait_saves()
records = episodes.read(s.cfg.output)
print(episodes.summary(s.cfg.output, s.episodes))
# labels: 7 success, 3 failure, 0 not labelled (70% of the labelled)
```

## Replaying a recording <span class="status status--mock">Mock only</span> { #replaying-a-recording }

`roboloom.policy.replay:load` sends the recorded `action` rows of one episode to the followers, whatever is observed. It runs the same path as a learned policy (controller, speed limit, interpolation, safety checks), so it checks that path without a model, and the replay's recorded `observation.state` can be compared with the original episode.

```bash
uv run roboloom infer rakuda2 --seconds 20 --home --task replay \
    --policy roboloom.policy.replay:load \
    --policy-kwargs '{"path": ".roboloom/rakuda2/datasets/rakuda2", "episode": 0}'
```

- `path` is a recorded dataset or a `.npy` file `[T, n]` of actions (to check the joint order and units of data from another tool). `stride: k` takes every k-th row (`rate_hz` must be `dataset_fps / k`); `horizon` is the chunk length.
- The dataset's action names and rate are checked against the configuration at load.
- It cannot be combined with `inference: async` (refused at load): a replay returns its rows in order whatever is observed, so replacing the queued actions would skip recorded rows.
- Move the robot to the episode's first pose before starting ([home](run.md#home)), and keep `max_speed` low on the first try. After the last action the followers stay there.
