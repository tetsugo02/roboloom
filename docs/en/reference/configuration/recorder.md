# recorder and session

Keys of the node YAML files that `recorder:` and `session:` of `config.yaml` point to. How recording, saving and resuming behave is in [Recording and saving](../../data/recording.md); the recorded columns are in [Dataset features](../dataset-features.md).

## recorder { #recorder }

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `max_age_ms` | `{node: value}` | required | ms | Per node, the oldest sample a row may use. Every input, follower, sensor and `record: true` estimator needs an entry. A row with only older samples is missing (`valid` 0) ([Missing data](../../data/format.md#missing-data)) |
| `grace_ms` | number | `500` | ms | How long a row waits for a silent follower before it is final |
| `image_writer_threads` | integer | `4` | — | Threads of LeRobot's image writer |
| `streaming_encoding` | boolean | `false` | — | Use LeRobot's streaming encoding |
| `queue_s` | number | `0.5` | s | How much each recorder input queue holds; while saving, the oldest is dropped |
| `video_codec` | text | — | — | Codec of `storage: video` images ([below](#video-codec)) |
| `quality` | mapping | `{}` | — | Thresholds of the quality warnings ([below](#quality)) |

A row is final once every follower's commands passed its interval, or after `grace_ms`.

```yaml
# nodes/recorder.yaml
max_age_ms:
  leader: 200
  follower: 200
  camera: 200
grace_ms: 500
image_writer_threads: 4
streaming_encoding: false
queue_s: 0.5
quality:
  max_missing_rate: 0.05
```

## Quality warnings (quality) { #quality }

`max_missing_rate`, `min_action_valid_rate`, and `max_interval_ms` under `recorder.quality` set quality warning thresholds. Check the metrics and warnings in the save result. `control_interval_ms` and `action_missing_rate` (the share of rows without a command) are per follower, and the warnings name the follower.

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `max_missing_rate` | number | `0.05` | fraction | Warns when, for a stream, the share of rows without a fresh sample exceeds this |
| `min_action_valid_rate` | number | `0.9` | fraction | Warns when the share of rows with `action.valid` 1 is below this |
| `max_interval_ms` | number | `100` | ms | Warns when a follower's longest control tick exceeds this |

## Video codec (video_codec) { #video-codec }

The MP4 codec of `storage: video` image sensors is chosen with `video_codec` in `nodes/recorder.yaml`, the same way for every robot. `storage: image` (PNG), audio, joints and the other features are stored as before.

| `video_codec` | Codec | LeRobot encoder (`vcodec`) |
| --- | --- | --- |
| not set | H.264 for a new dataset; when appending, the saved videos' settings | `h264` |
| `av1` (alias `libsvtav1`) | AV1 | `libsvtav1` |
| `h264` | H.264 | `h264` (FFmpeg's libx264) |

The default is H.264 because it plays almost everywhere; LeRobot's own default is AV1. Set `video_codec: av1` for smaller files.

```yaml
# nodes/recorder.yaml
video_codec: av1
```

To choose it per launch, use `video_codec` of `load_config` and `Session.launch`, or `--video-codec` on the CLI. `None` (omitted on the CLI) keeps the YAML's choice.

```python
from roboloom import Session, load_config

cfg = load_config("rakuda2", video_codec="h264")
with Session.launch("rakuda2", video_codec="h264") as session:
    ...
```

```bash
roboloom record --task "pick" --seconds 30 --video-codec h264
roboloom validate --video-codec h264   # the summary shows video codec: h264
```

- When passing a loaded `RobotConfig` to `Session.launch`, choose it in `load_config`; `Session.launch(cfg, video_codec=...)` is an error (as with `sensors` and `observe`).
- In the launcher, "Video codec (storage: video)" under Devices offers `YAML / dataset`, `AV1` and `H.264`. The choice is saved with the last launch.
- The dora nodes reload the configuration with the same choice as the launching process.
- LeRobot does the encoding: roboloom only passes `lerobot.configs.video.RGBEncoderConfig(vcodec=...)` to `LeRobotDataset.create` and `resume`. CRF, GOP and preset stay at LeRobot's defaults (CRF 30, GOP 2) and are not settings.
- When this environment's FFmpeg (PyAV) lacks the chosen codec's encoder, the launch (including `validate`) stops with the reason instead of switching to another codec. Nothing is recorded.

**Appending to an existing dataset**: LeRobot joins a new episode's video onto the existing MP4, so a dataset's videos keep one codec. Without `video_codec`, the codec and settings (CRF, GOP, ...) of the saved videos are reused. When the chosen codec differs from the saved videos, the launch stops before writing and shows the difference, such as `video_codec: 'av1' (saved videos) -> 'h264' (requested)`. To record with another codec, set another `repo_id` and `output` for a separate dataset. roboloom does not choose another output by itself, and does not convert or overwrite existing videos.

| | AV1 | H.264 (default) |
| --- | --- | --- |
| Size | Generally smaller than H.264 at the same quality | Generally larger than AV1 |
| Speed | With LeRobot's defaults (a fast SVT-AV1 preset), similar to H.264 in the measurement below; decoding can be heavier than H.264 | Fast; many devices have a hardware decoder |
| Playback compatibility | Needs a recent player; older players, some browsers' and editors' video previews, and devices without a hardware decoder may not play it | Plays in almost every player and browser |

On this machine, recording 90 synthetic 640×480 frames (30 fps) took about 0.9 s to save with either codec; the files were 238 KiB (AV1) and 209 KiB (H.264). This is one measurement and varies with the content and the machine. The same CRF value does not give the same quality across codecs.

If the VS Code LeRobot Viewer shows AV1 videos (the former default) as black, record a separate H.264 dataset and compare. Whether H.264 displays there has not been checked. The codec choice is <span class="status status--mock">Mock only</span>: it was tested with synthetic frames read back through LeRobot and with the mock dataflow, not with hardware cameras.

## session { #session }

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `type` | text | required | — | Only `terminal` (the operator screen; [Operator screen](../operator-screen.md)) |

```yaml
# nodes/session.yaml
type: terminal
```
