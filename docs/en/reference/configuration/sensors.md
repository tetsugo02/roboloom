# Sensors (sensors)

Keys of the node YAML under `sensors:`. A sensor is only recorded; listed in `observe`, it is also given to the policy. For each device's setup and limits see the pages of [Sensors](../../sensors/index.md). The recorder's `max_age_ms` needs an entry for every sensor ([recorder](recorder.md#recorder)).

## Keys of every sensor { #common }

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `type` | text | required | — | `realsense_rgb`, `digit`, `v4l2_rgb`, `opencv_rgb`, `pcm_mono`, `mel_mono` or `module:Class` |
| `fps` | number | required for image sensors | Hz | Rate at which it is read (follows the rules of [Control rate](followers.md#control-rate)); audio sensors have none (refused) |

## Keys of image sensors { #image }

The keys `realsense_rgb`, `digit`, `v4l2_rgb` and `opencv_rgb` read. Images are HWC uint8 RGB, recorded as `observation.images.<sensor>`; a frame whose shape differs from the configuration is refused.

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `fps` | number | required | Hz | Rate requested from the camera |
| `width` | integer | required | px | Width |
| `height` | integer | required | px | Height |
| `storage` | text | `video` | — | `video` (lossy MP4) or `image` (lossless PNG) ([below](#image-storage)) |

## Image storage (storage) { #image-storage }

Set `storage: video | image` in each image sensor's node YAML (RealSense, DIGIT, V4L2 including Pika wrist cameras). The default is `video`: the existing lossy MP4 encoding. `image` embeds lossless PNG frames in Parquet; use it for DIGIT/background pixel differences. Formats can be mixed in one dataset. Invalid values are refused at configuration load, including `validate`.

PNG generally needs more disk space and PNG compression/write work; actual size and throughput depend on image content and hardware. As an uncompressed RGB reference, 320×240×3 at 30 dataset fps is 6.9 MB/s per sensor (640×480: 27.6 MB/s); these are not measured PNG rates. LeRobot 0.7.0 uses PNG compression level 6 for `image`. Changing storage changes the feature dtype: choose a separate dataset `output`; resume into the previous schema is refused.

Live observations remain HWC uint8 RGB, and LeRobot dataset reads return CHW float32 in [0, 1] for either format by default. Checkpoint inputs remain `VISUAL`. Storage is <span class="status status--mock">Mock only</span>: it was tested with mock/synthetic frames only, without hardware. The codec of `storage: video` is chosen with [the recorder's `video_codec`](recorder.md#video-codec).

## realsense_rgb { #realsense }

The colour stream of an Intel RealSense ([RealSense](../../sensors/realsense.md)).

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `serial` | text | required | — | Serial number (`rs-enumerate-devices`) |

## digit { #digit }

Tactile images of a DIGIT ([DIGIT](../../sensors/digit.md)).

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `serial` | text | required | — | Serial number |
| `resolution` | text | `QVGA` | — | `QVGA` or `VGA`; `height` and `width` must match it (`QVGA`: `height: 320`, `width: 240`; `VGA`: `height: 640`, `width: 480`) |
| `name` | text | the `serial` value | — | Name passed to `digit_interface` |

`fps` must be a rate the device supports at that resolution (checked when it opens).

## v4l2_rgb <span class="status status--dev">In development</span> { #v4l2 }

USB (UVC) cameras through Video4Linux2, used for the fisheye cameras of the Pika Sense and Pika Gripper ([Pika cameras](../../sensors/pika-cameras.md)). Opening sets the format, size and rate and refuses a camera that does not deliver them.

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `device` | text | required | — | `/dev/v4l/by-path/...` or `/dev/v4l/by-id/...` (`/dev/video<n>` can change between boots) |
| `format` | text | `MJPG` | — | `MJPG` or `YUYV` |

## Web camera (opencv_rgb) <span class="status status--dev">In development</span> { #webcam }

USB and built-in cameras read through OpenCV. It has not been checked on hardware. See [Web camera](../../sensors/webcam.md) for details and per-OS limits. The size is checked strictly; `fps` and `format` are sent as requests.

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `device` | integer ≥ 0 or a `/dev/` path | required | — | Camera index or path; a path works only with `backend` `auto` or `v4l2` |
| `backend` | text | `auto` | — | `auto`, `v4l2`, `avfoundation`, `msmf`, `dshow` |
| `format` | text | — | — | `MJPG` or `YUYV` |

## Audio (pcm_mono, mel_mono) <span class="status status--dev">In development</span> { #audio }

A mono microphone ([Audio](../../sensors/audio.md)). One chunk per dataset frame is recorded as `observation.audio.<sensor>`; there is no `fps`.

`pcm_mono` records int16 PCM (`sample_rate / dataset_fps` samples).

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `device` | text | required | — | Input device |
| `channels` | integer | required | — | Only `1` |
| `sample_rate` | number | required | Hz | Sample rate |

`mel_mono` records the log mel power of the last `window_seconds` (float32, `[n_mels, 1 + window samples // hop_length]`). Besides the keys of `pcm_mono` it reads the following.

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `sample_rate` | number | `44100` | Hz | Sample rate |
| `window_seconds` | number | `1.0` | s | Window length; at least `n_fft` samples |
| `n_fft` | integer | `2048` | samples | FFT length |
| `hop_length` | integer | `690` | samples | Frame step |
| `n_mels` | integer | `64` | — | Number of mel bands |
| `fmax` | number | `15000` | Hz | Highest frequency (at most the Nyquist frequency) |

## Sensor selection { #sensor-selection }

`load_config(..., sensors=[...], observe=[...])` and `Session.launch(..., sensors=[...], observe=[...])` select the sensors that run and are recorded independently from the observations given to the policy. `None` keeps the configuration's defaults; `[]` selects none. Follower state is always observed. When passing a `RobotConfig`, select in `load_config` (`Session.launch` rejects additional selection arguments).

```python
with Session.launch(
    "rakuda2",
    options=["policy"],
    sensors=["camera", "audio"],
    observe=["camera"],
    policy="my_lab.policies:load",
) as session:
    session.wait_ready()
    session.record("pick", seconds=20)
```

- On the CLI the same selection is `--sensors camera,audio --observe camera`; `--sensors "" --observe ""` selects none.
- The launcher has separate checkboxes for sensors and policy observations and remembers the selection.
- Unselected sensor YAML files are not loaded. Observing a sensor that does not run is an error.
- Sensors introduced by options can also be selected individually, including either DIGIT.
- A sensor that does not run by default is declared in `config.yaml` as `{file: nodes/audio.yaml, default: false}`; plain path strings are enabled by default. The selection is resolved after the options are applied.
- A sensor that runs is recorded even when it is not in `observe`.

## Example { #example }

```yaml
# nodes/camera.yaml
type: realsense_rgb
serial: SET_REALSENSE_SERIAL  # rs-enumerate-devices
width: 640
height: 480
fps: 30
storage: video
```
