# Hand-held collection with Pika Sense and `convert-handheld`

> **Status: in development, mock only, not verified on hardware.** Hand-held recording
> and the conversion to relative pose actions have run only with mock Senses and mock
> cameras. There is **no inference path** that drives a robot from a policy trained on
> this data. **Tell the user this** whenever you set it up or use it.

UMI-style: record Pika Senses held in the hands (no robot), then convert the recording into
a new LeRobotDataset whose `action` and `observation.state` are poses relative to the
Sense itself, so the tracker frame never needs registering to a robot base. The recording
keeps raw values; it can be converted again in another form.

## Configuration (no followers)

No template (`roboloom init` only knows `rakuda2`). The mock configuration
`.roboloom/pika-handheld-mock/` is in the roboloom repository, not in the package; copy it
from <https://github.com/tetsugo02/roboloom> if needed. Its ports, tracker names and camera
sizes are mock values (`mode: mock`): never reuse them for hardware.

```yaml
repo_id: local/pika-handheld-mock
output: datasets/pika-handheld-mock
mode: mock
dataset_fps: 10
inputs:
  left_sense: nodes/left_sense.yaml     # type: pika_sense, needs poll_hz
  right_sense: nodes/right_sense.yaml
followers: {}                           # nothing driven; dataset has no action
sensors:
  left_wrist: nodes/left_wrist.yaml     # type: v4l2_rgb (Sense fisheye), needs fps
  right_wrist: nodes/right_wrist.yaml
recorder: nodes/recorder.yaml
session: nodes/session.yaml
```

- `followers: {}` forbids controllers; every input needs `poll_hz` and every sensor `fps`
  (no follower rate to borrow). Loading refuses otherwise.
- `pika_sense` keys (`port`, `tracker: {system, serial}`, `stale_ms`, `poll_hz`) and the
  `trackers:` node (`type: libsurvive`): see
  [piper-pika.md](piper-pika.md); cameras: [../sensors.md](../sensors.md).

## Recording

```bash
uv run roboloom record pika-handheld-mock --task "pick" --seconds 15 --episodes 5 --plain
uv run roboloom run pika-handheld-mock        # with the operator screen
```

Each Sense gives `observation.<sense>` (10, `float32`): `x y z` (m, tracker world frame),
`qx qy qz qw`, `gripper` (jaw, rad), `tracking` (0/1; when 0 the pose is the last tracked
one), `engaged` (0/1). A row with no fresh sample is recorded as all zeros. Images are
`observation.images.<camera>`. Needs the `record` extra.

## Conversion

```bash
uv run roboloom convert-handheld pika-handheld-mock --action delta
uv run roboloom convert-handheld pika-handheld-mock --action relative-chunk --horizon 16
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--action` | `delta` | `delta` or `relative-chunk` |
| `--horizon` | 16 | H for `relative-chunk` (≥ 1) |
| `--hands` | every recorded pose feature | e.g. `left_sense,right_sense` |
| `--max-gap` | 3 | longest untracked run (rows) that is filled (≥ 0) |
| `--output` | `<recording output>-<action>` | refused if it exists |
| `--repo-id` | `<repo_id>-<action>` | new dataset name |

The source is the configuration's `output` with default options (no `--with`/`--mock`).

Python (not exported from `roboloom`; import the module):

```python
from roboloom.handheld.convert import convert, read_metadata

report = convert(
    ".roboloom/pika-handheld-mock/datasets/pika-handheld-mock",  # source dataset dir
    ".roboloom/pika-handheld-mock/datasets/pika-handheld-mock-delta",
    "local/pika-handheld-mock-delta",
    action="delta",  # or "relative-chunk"
    horizon=16,
    hands=None,
    max_gap=3,
    source_repo_id="local/pika-handheld-mock",
)
print(report.describe())  # Report: output, episodes, frames, dropped, filled_rows
meta = read_metadata(report.output)  # meta/roboloom_handheld.json
```

Errors are `roboloom.ConfigError` (source not a dataset, already has `action`, unknown
hands, output exists, no usable episode, lerobot missing).

## Output layout

A relative pose is 9 numbers: `x y z` + 6D rotation `r0..r5` (first two columns of the
rotation matrix). Per hand, P[t] is its pose in row t.

| Feature | Content | Size (2 Senses) |
| --- | --- | --- |
| `action` (`delta`) | per hand `inv(P[t])·P[t+1]` + jaw at t+1; names `<hand>.x … <hand>.gripper` | 20 |
| `action` (`relative-chunk`) | `inv(P[t])·P[t+k]` + jaw at t+k, k = 1..H, k-major; names `k01.<hand>.x …` | H×20 |
| `observation.state` | per hand `inv(P[t])·P[t-1]` (`<hand>.prev_*`) + jaw at t; then each further hand seen from the first (`<first>_to_<hand>.*`) | 29 |

Images, raw `observation.<sense>` and `observation.meta.*` stay; videos are copied. Past
an episode's end the last pose is repeated. `meta/roboloom_handheld.json` keeps `action`,
`horizon`, `hands`, `pose`, `rotation`, `fps`, `max_gap`, `source`, `dropped_episodes`.
`roboloom.handheld.poses` has `targets_from_deltas` / `targets_from_chunk` to turn outputs
back into absolute poses (no robot execution exists yet).

## Tracking gaps

- A row counts as untracked when `tracking` is 0 **or** it was recorded without a sample
  (zero quaternion / non-finite values) — such rows no longer abort the conversion.
- Gaps up to `--max-gap` rows are filled: inside an episode position linearly and rotation
  by slerp; at an episode's start or end, the nearest tracked pose.
- A longer gap, or a hand never tracked, drops the **whole episode** with a reason
  (`left out episode N: <hand>: tracking lost for K rows from row R`). Raising `--max-gap`
  is a data-quality decision for the user, not a fix.

## Training

`relative-chunk` needs `--policy.chunk_size=1 --policy.n_action_steps=1` in
`lerobot-train`; `delta` works with ACT/Diffusion as is. See [../policy.md](../policy.md)
and [../recording.md](../recording.md); check GPU availability before training.

## Limitations

Unverified on hardware (Sense, libsurvive, base stations, fisheye cameras); fisheye pose
relative to the jaws on Sense vs. Gripper unmeasured; no PiPER inference from this data
(relative pose → IK); motions PiPER cannot do are not filtered; no latency matching; the
two mock Senses move identically.
