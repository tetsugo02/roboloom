# Sensors

A sensor is a node that captures observations such as camera or tactile images. The recorder aligns them to the dataset rows, and a policy gets those chosen with `observe`. Images are handled as HWC, 3-channel RGB. A sensor's `fps` is its capture rate; the configuration's `dataset_fps` is the recording rate.

| Sensor | `type` | Output | Status |
| --- | --- | --- | --- |
| [RealSense](realsense.md) | `realsense_rgb` | RGB camera image | <span class="status status--verified">Hardware-verified</span> |
| [DIGIT](digit.md) | `digit` | Tactile RGB image | <span class="status status--verified">Hardware-verified</span> |
| [Audio](audio.md) | `mel_mono`, `pcm_mono` | Mel spectrogram, PCM | <span class="status status--dev">In development</span> |
| [Pika wrist cameras](pika-cameras.md) | `v4l2_rgb`, `realsense_rgb` | Fisheye and D405 RGB images | <span class="status status--dev">In development</span> |
| [Web camera](webcam.md) | `opencv_rgb` | RGB camera image | <span class="status status--dev">In development</span> |

## By robot { #by-robot }

| Robot | RealSense | DIGIT | Audio | Pika wrist cameras | Web camera |
| --- | --- | --- | --- | --- | --- |
| [Rakuda2](../robots/rakuda2/sensors.md) | <span class="status status--verified">Hardware-verified</span> | <span class="status status--verified">Hardware-verified</span> | <span class="status status--dev">In development</span> | — | <span class="status status--dev">In development</span> |
| [PiPER + Pika Gripper](../robots/piper/index.md) | <span class="status status--dev">In development</span> | — | <span class="status status--dev">In development</span> | <span class="status status--dev">In development</span> | <span class="status status--dev">In development</span> |
| [Pika Sense in the hand](../tutorials/pika-handheld.md) | — | — | — | <span class="status status--dev">In development</span> | — |

Audio and the web camera can be added to any robot's configuration. The table that also covers the kinds of policies is the [Support matrix](../get-started/support-matrix.md).

## Recorder entry { #recorder }

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

The codec of `storage: video` images (AV1 or H.264) is chosen with `video_codec` in the same `nodes/recorder.yaml` ([Video codec](../reference/configuration/recorder.md#video-codec)).
