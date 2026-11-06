# Pika Sense hand-held mock

Mock devices only: two Pika Senses held in the hands (`left_sense`, `right_sense`) and
their fisheye cameras (`left_wrist`, `right_wrist`), with no robot (UMI-style
collection). The configuration has no followers, so the dataset has no `action`;
`roboloom convert-handheld` makes a training dataset with relative pose actions.

```bash
uv run roboloom record pika-handheld-mock --task pick --seconds 15 --episodes 5 --plain
uv run roboloom convert-handheld pika-handheld-mock --action delta
uv run roboloom convert-handheld pika-handheld-mock --action relative-chunk --horizon 16
```

| file | what |
| --- | --- |
| `config.yaml` | inputs and cameras; `followers: {}` |
| `nodes/*_sense.yaml` | Pika Sense inputs (serial port and libsurvive tracker on hardware); `poll_hz` is required without followers |
| `nodes/*_wrist.yaml` | the Senses' fisheye cameras (`v4l2_rgb`; a `/dev/v4l/by-path/...` path on hardware) |
| `nodes/recorder.yaml` | the oldest sample a row may use, per node |

Nothing here has run on hardware, and running a trained policy on PiPER does not exist
yet; see the docs page "Hand-held collection with Pika Sense" under Contribution.
