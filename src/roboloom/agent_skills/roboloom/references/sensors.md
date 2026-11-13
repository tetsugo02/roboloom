# Sensors

A sensor is a node under `sensors:` in `config.yaml`; its YAML `type` picks the driver.
The node name becomes the dataset feature name. RealSense uses the `hardware` extra; audio uses `audio` (also retained in `hardware` for PCM)
(`pyrealsense2`, `sounddevice`); DIGIT uses the `digit` extra (`digit-interface`,
from a fork that depends on opencv-python-headless; see [installation.md](installation.md)):

```bash
uv add git+https://github.com/tetsugo02/roboloom.git --extra record --extra hardware --extra digit
```

OpenCV (`opencv-python-headless`) is a core dependency for `opencv_rgb` and `v4l2_rgb`.
Camera access alone needs no extra and does not use pysurvive. D405 RGB still needs `hardware` for pyrealsense2.

| `type` | Device | Status | Feature |
| --- | --- | --- | --- |
| `realsense_rgb` | Intel RealSense, colour only | Hardware-verified (Rakuda2) | `observation.images.<name>` (video by default; H×W×3 RGB) |
| `digit` | DIGIT tactile sensor | Hardware-verified (Rakuda2) | `observation.images.<name>` (video by default; H×W×3 RGB) |
| `opencv_rgb` | USB / built-in webcam, Linux/macOS/Windows driver | Mock only; hardware unverified | `observation.images.<name>` |
| `v4l2_rgb` | UVC camera via V4L2/OpenCV (Pika wrist fisheye) | In development, mock only | `observation.images.<name>` |
| `pcm_mono` | Microphone via `sounddevice` | Hardware unverified | `observation.audio.<name>` (int16) |

Common rules:

- `fps` is the capture rate; `dataset_fps` in `config.yaml` is the recording rate.
- Every sensor needs an entry in `nodes/recorder.yaml` `max_age_ms` (`<name>: <ms>`), or
  loading fails.
- Serials and device paths must be explicit and unique across the configuration
  (`SET_...` values and duplicates are refused). `roboloom probe` does **not** read
  sensors; it is for Dynamixel, PiPER and Pika buses.
- `--mock` / `mock=True` gives black frames (zeros) of the configured shape; a real frame
  of another shape or dtype stops the node.
- Adding a sensor that changes recorded features needs its own option `dataset:` name
  ([configuration.md](configuration.md)).

## RealSense RGB (`realsense_rgb`)

```yaml
type: realsense_rgb
serial: SET_REALSENSE_SERIAL   # required
width: 640                     # required
height: 480                    # required
fps: 30                        # required
```

- Opens the colour stream as `rgb8` with this size and rate; choose a combination the
  device supports. No depth, point clouds or intrinsics are recorded.
- Serial: `rs-enumerate-devices` (librealsense tool).
- Warns when the camera is not on USB 3 (frames may drop).
- The Pika D405 is expected to work with this type but is unverified on hardware.

## DIGIT (`digit`)

```yaml
type: digit
serial: SET_DIGIT_LEFT_SERIAL  # required; left and right differ
name: left                     # optional label passed to digit-interface
resolution: QVGA               # QVGA (default) or VGA
height: 320                    # must match resolution
width: 240
fps: 30
```

| `resolution` | `height` | `width` | `fps` (digit-interface) |
| --- | --- | --- | --- |
| `QVGA` | 320 | 240 | 30, 60 |
| `VGA` | 640 | 480 | 15, 30 |

- `height`/`width` are transposed on purpose (`get_frame()` transposes); do not "fix"
  them. A mismatch is refused at load; an unsupported `fps` is refused on connect.
- Frames are converted BGR → RGB.
- Serial: the label on the sensor, or
  `uv run python -c "from digit_interface import DigitHandler; print(DigitHandler.list_digits())"`.
- On Rakuda2 the nodes are `digit_left`/`digit_right`, enabled by option `digit`
  ([robots/rakuda2.md](robots/rakuda2.md)).

## V4L2 fisheye (`v4l2_rgb`) – in development, mock only

```yaml
type: v4l2_rgb
device: /dev/v4l/by-path/...-video-index0   # required; or /dev/v4l/by-id/...
format: MJPG                                 # MJPG (default) or YUYV
width: 640
height: 480
fps: 30
```

- Use a stable `/dev/v4l/by-path/` or `by-id/` path, not `/dev/video<n>`. A by-path and
  by-id name of the same camera count as one device.
- Opening sets format, size and rate and refuses a camera that delivers anything else
  (OpenCV would silently fall back). A one-frame buffer is requested (not a newest-frame guarantee); no frame for 1 s
  stops the node ("cable or camera lost").
- Find paths and modes: `ls -l /dev/v4l/by-path/`,
  `v4l2-ctl -d <device> --list-formats-ext` (package v4l-utils; ask an administrator).
- Tested only with a fake OpenCV and mock devices. Unverified on hardware: delivered
  modes, which `video-index` gives frames, USB bandwidth with several cameras, MJPG
  decode latency. Tell the user before relying on it. See
  [robots/piper-pika.md](robots/piper-pika.md) and [robots/handheld.md](robots/handheld.md).

## Microphone (`pcm_mono`, `mel_mono`) – hardware unverified

```yaml
type: pcm_mono
device: mock-microphone  # required string; on hardware a sounddevice device name
sample_rate: 16000     # required
channels: 1            # required, must be 1
```

- Records one int16 chunk of `sample_rate / dataset_fps` samples per frame (no `fps`
  key; the rate is `dataset_fps`). Missing samples are zero-padded.
- Documented PCM/mel capture is verified with synthetic and mock data; physical microphones remain unverified.

New sensor types: [extending.md](extending.md); in-process readers:
[in-process.md](in-process.md).

### Image storage

Set `storage: video | image` in each image sensor's node YAML (RealSense, DIGIT, V4L2 including Pika wrist cameras). The default is `video`: the existing lossy MP4 encoding. `image` embeds lossless PNG frames in Parquet; use it for DIGIT/background pixel differences. Formats can be mixed in one dataset. Invalid values are refused at configuration load, including `validate`.

PNG generally needs more disk space and PNG compression/write work; actual size and throughput depend on image content and hardware. As an uncompressed RGB reference, 320×240×3 at 30 dataset fps is 6.9 MB/s per sensor (640×480: 27.6 MB/s); these are not measured PNG rates. LeRobot 0.6.1 uses PNG compression level 6 for `image`. Changing storage changes the feature dtype: choose a separate dataset `output`; resume into the previous schema is refused.

Live observations remain HWC uint8 RGB, and LeRobot dataset reads return CHW float32 in [0, 1] for either format by default. Checkpoint inputs remain `VISUAL`. Storage was tested with mock/synthetic frames only, without hardware.

## Web camera (`opencv_rgb`)

Install `uv add git+https://github.com/tetsugo02/roboloom.git`; OpenCV is a core dependency. Required: `device` (non-negative integer;
Linux also accepts `/dev/` paths), positive integer `width`, `height`, and positive `fps`.
Optional `backend: auto` selects Linux V4L2, macOS AVFoundation, Windows MSMF;
Windows also allows `dshow`. No fallback. Optional `format: MJPG | YUYV` defaults to
backend choice. A backend that does not match the OS, or a `/dev/` path outside Linux,
passes config loading/mock and raises `ValueError` only when the real camera opens; use
`backend: auto` for configs shared across OSes. Unavailable/mismatched fps or format warns (format
warnings name the reported FOURCC); actual frame dimensions
and uint8 RGB contract are strict. `storage: video | image` defaults to video.

Use `roboloom.sensors.vision.opencv.OpenCVRGB(name, cfg).open(mock=False, dataset_fps=10)`
as a Reader and always close it in `finally`. Mock needs no OpenCV. Reads are synchronous;
loss is detected after >1 s only when native read returns, with no forced timeout.
Buffer size 1 is a request, not a newest-frame guarantee. Timestamps are reception time,
not exposure time; no synchronization/reconnection. Indices may change; prefer stable
Linux paths. Set Recorder `max_age_ms` for the node. Changing size/storage requires
separate dataset output. Hardware is unverified on all three OSes; full Windows Session
support is excluded (Unix FIFO/process APIs). Docs: `docs/*/contribution/webcam.md` (in development).
Never open a camera without user authorization.

mel_mono uses float32[n_mels, n_frames], ascending frequency, with defaults 44100 Hz, 1 second, 64 bins, n_fft=2048, hop_length=690, fmax=15000. Install the audio extra. Select independently through sensors/observe.
