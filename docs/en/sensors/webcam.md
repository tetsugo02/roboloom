# Web camera

Capture USB / built-in web cameras through OpenCV. The driver targets Linux, macOS and Windows, but has only been tested with fake OpenCV and mocks, without hardware. This does not provide Windows support for the full Session / recording runtime, which uses Unix FIFOs and process control.

## Installation

```bash
uv add git+https://github.com/tetsugo02/roboloom.git
```

OpenCV is a core dependency; no camera extra is needed. Recording also needs `record`, and robots need their own extras.

## Configuration

```yaml
# nodes/camera.yaml
type: opencv_rgb
device: 0
backend: auto
width: 640
height: 480
fps: 30
storage: video
```

| Key | Behaviour |
| --- | --- |
| `device` | Required non-negative integer. Linux also accepts `/dev/videoN` or `/dev/v4l/by-id/...`, `by-path/...`. Files / URLs are refused |
| `backend` | Defaults to `auto`: Linux → `v4l2`, macOS → `avfoundation`, Windows → `msmf`. Windows also accepts `dshow`. No automatic fallback |
| `width`, `height` | Required positive integers. Actual frame dimensions must match at read time; no automatic resize |
| `fps` | Required requested rate. Unsupported, unavailable or reported rates differing by more than 0.5 fps produce a warning and continue |
| `format` | Optional `MJPG` / `YUYV`; omitted uses the backend default. Unsupported, unconfirmed or different settings warn |
| `storage` | `video` (default) / `image`. See [storage](../reference/configuration.md#image-storage) |

Prefer stable device paths on Linux. Use `ls -l /dev/v4l/by-path/` and `v4l2-ctl -d <device> --list-formats-ext` for paths and supported modes (requires v4l-utils). On macOS / Windows, consult camera specifications and OS camera apps for modes, then check an explicit index. Indices can change with connection order. Check device permissions on Linux, camera permission for the launching app on macOS, and desktop-app camera permissions on Windows.

Duplicate indices are refused. Linux also detects duplicates between indices, paths and symlinks. Complete physical identity across different backends is not guaranteed on macOS / Windows.

Register `sensors.camera: nodes/camera.yaml` in `config.yaml` and set Recorder `max_age_ms.camera` (see [Sensors](index.md)). On Rakuda2 replace the existing `nodes/camera.yaml` with the configuration above, keeping the node name. The default template stays RealSense. Prefer a separate dataset output after changing cameras because policy inputs change; a different size or storage requires a separate output.

## Python API

```python
import time

from roboloom.sensors.vision.opencv import OpenCVRGB

camera = OpenCVRGB("camera", {
    "device": 0, "width": 640, "height": 480, "fps": 30,
})
reader = camera.open(mock=False, dataset_fps=10)
try:
    for _ in range(30):
        sample = reader.read()
        if sample is not None:
            print(sample.value.shape, sample.capture_ns)
        time.sleep(1 / 30)
finally:
    reader.close()
```

This example opens only the camera. `mock=True` returns black frames without importing OpenCV or connecting hardware. When passing `reader.read` to `InProcessSession.sensors`, the caller must still call `reader.close()` at shutdown.

## Output and limitations

Frames are HWC uint8 RGB, under `observation.images.<name>`. Timestamps use the monotonic clock after reception, not exposure time. Cameras are not synchronized. `fps` is the requested capture rate; `dataset_fps` is the recording rate.

Reads are synchronous. A failed acquisition returns `None`; after more than one second without a frame, the next returning read raises `ConnectionError`. There is no forced timeout for a stalled native `read()`. A one-frame buffer is requested, but backends may ignore it, so newest-frame delivery is not guaranteed. No automatic reconnection is performed.

Existing Linux `v4l2_rgb` retains strict format, size and fps checks. This adds no depth, calibration, exposure controls or GUI preview.
