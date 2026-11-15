# Sensors

| Sensor | `type` | Output |
| --- | --- | --- |
| [RealSense](realsense.md) | `realsense_rgb` | RGB camera image |
| [DIGIT](digit.md) | `digit` | Tactile RGB image |

Supported combinations are listed in [Rakuda2](../robots/rakuda2.md). Images are handled as HWC, 3-channel RGB. A sensor's `fps` is its capture rate; the configuration's `dataset_fps` is the recording rate.

## Recorder entry

Every sensor needs an entry under `max_age_ms` in `nodes/recorder.yaml`, keyed by its node name. It is the oldest a sample may be, in ms, to be used for a dataset row; an older one is recorded as missing (`valid` 0; the value repeats the last valid sample, zeros only before the first one). Inputs and followers need one too. Without it, loading the configuration fails with `max_age_ms.<name>: expected positive finite number` (for example `max_age_ms.digit_left: expected positive finite number`).

```yaml
max_age_ms:
  leader: 200
  follower: 200
  camera: 200
  digit_left: 200
  digit_right: 200
```

The Rakuda2 template already has the entries for `camera`, `digit_left` and `digit_right`. When you add a sensor or rename its node, add or rename its entry as well. Entries for nodes that are not in the configuration are ignored, so the template keeps the entries of every option (such as `digit_left` without the `digit` option); a misspelled name is ignored in the same way, and loading then reports the correctly named node's entry as missing.

The codec of `storage: video` images (AV1 or H.264) is chosen with `video_codec` in the same `nodes/recorder.yaml` ([Video codec](../reference/configuration.md#video-codec)).

[Audio](audio.md): PCM and mel, shared across robots; hardware unverified.
