# Web camera (in development, not tested on hardware)

!!! warning "In development"
    Notes on capturing USB / built-in web cameras through OpenCV. The driver targets Linux, macOS and Windows, but has been checked only with tests against a fake OpenCV and with mock devices, not on hardware on any OS. Windows support for the full `Session` / recording runtime is out of scope (the current `Session` uses Unix FIFOs and process control).

## Installation

OpenCV (`opencv-python-headless`) is a core dependency; no camera extra is needed. Recording also needs `record`, and robots need their own extras ([Installation](../quick-start/installation.md)).

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
| `device` | Required non-negative integer. Linux also accepts `/dev/videoN`, `/dev/v4l/by-id/...` and `/dev/v4l/by-path/...`. Video files and URLs are refused |
| `backend` | Defaults to `auto`: Linux → `v4l2`, macOS → `avfoundation`, Windows → `msmf`. Windows also accepts `dshow`. No automatic fallback to another backend |
| `width`, `height` | Required positive integers. Frames whose actual size differs are refused at read time; no automatic resize |
| `fps` | Required requested capture rate. An unsupported, unreported, or reported rate differing by more than 0.5 fps warns and continues |
| `format` | Optional `MJPG` or `YUYV`; omitted uses the backend default. An unsupported, unconfirmed or different format warns with the reported format |
| `storage` | `video` (default) or `image`. See [storage](../reference/configuration.md#image-storage) |

A backend that does not match the OS (e.g. `dshow` on Linux) and a `/dev/` path outside Linux are not refused when the configuration is loaded (`validate`, mock); opening the real camera stops with `ValueError`. This keeps a mock configuration checkable on another OS. Use `backend: auto` to share one configuration across operating systems.

Prefer stable device paths on Linux. Find paths and supported modes with `ls -l /dev/v4l/by-path/` and `v4l2-ctl -d <device> --list-formats-ext` (requires v4l-utils). On macOS and Windows, look up modes in the camera specification or the OS camera app, then check an explicit index. Indices can change with connection order. Check device permissions on Linux, camera permission for the launching app on macOS, and desktop-app camera permission on Windows.

The same index on two sensors is refused. Linux also detects duplicates between indices, paths and symlinks. On macOS and Windows, two entries with different backends cannot be identified as the same physical camera.

Register `sensors.camera: nodes/camera.yaml` in `config.yaml` and set Recorder `max_age_ms.camera` ([Sensors](../sensors/index.md)). On Rakuda2, replace the existing `nodes/camera.yaml` with the configuration above and keep the node name; this combination has not been checked on hardware. The template default stays RealSense. Changing cameras changes the policy's input images, so prefer a separate dataset output; a different size or storage requires one.

## Python API

```python
import time

from roboloom.sensors.vision.opencv import OpenCVRGB

camera = OpenCVRGB(
    "camera",
    {
        "device": 0,
        "width": 640,
        "height": 480,
        "fps": 30,
    },
)
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

This example opens only the camera. `mock=True` returns black frames without importing OpenCV or connecting to hardware. When passing `reader.read` to `InProcessSession`'s `sensors`, the caller still calls `reader.close()` at shutdown.

## Output and limitations

Frames are HWC uint8 RGB, under `observation.images.<name>`. Timestamps use the monotonic clock after reception, not exposure time. Cameras are not synchronized. `fps` is the requested capture rate; `dataset_fps` is the recording rate.

Reads are synchronous. A read without a frame returns `None`; after more than one second without a frame, the next read that returns raises `ConnectionError`. A stalled OpenCV `read()` is not forcibly timed out. A one-frame buffer is requested, but backends may ignore it, so the newest frame is not guaranteed. There is no automatic reconnection.

The existing `v4l2_rgb` keeps its strict format, size and fps checks on Linux. This adds no RealSense depth or calibration, exposure controls, or GUI preview.
