# Pika wrist cameras (in development, not tested on hardware)

!!! warning "In development"
    Notes on recording the cameras on the Pika Gripper and Pika Sense. The fisheye camera has been checked only with tests against a fake OpenCV and with mock devices. The D405 is expected to work with `realsense_rgb` unchanged, but this has not been checked on hardware.

## Cameras

The Pika Gripper and the Pika Sense each carry these two cameras (per AgileX's pika_sdk).

| Camera | How it is read | roboloom type |
| --- | --- | --- |
| Fisheye USB camera (UVC) | V4L2, MJPG. pika_sdk defaults to 1280×720@30 | `v4l2_rgb` (new) |
| Intel RealSense D405 | pyrealsense2, selected by serial number | `realsense_rgb` (existing; colour only) |

For policy learning, record the cameras of the Pika Gripper at the end of the arm. The Sense's cameras are meant for hand-held collection (stage 4).

## Fisheye camera (`v4l2_rgb`)

```yaml
# nodes/left_wrist.yaml
type: v4l2_rgb
device: /dev/v4l/by-path/pci-0000:00:14.0-usb-0:2:1.0-video-index0
format: MJPG             # the default; YUYV is also available
width: 640
height: 480
fps: 30
```

| Key | Meaning |
| --- | --- |
| `device` | The camera's path. Use `/dev/v4l/by-path/...` (fixed by the USB socket) or `/dev/v4l/by-id/...` (fixed by the camera model). The number of `/dev/video<n>` can change between boots |
| `format` | The pixel format: `MJPG` (the default) or `YUYV` |
| `width`, `height`, `fps` | The size and rate to record. Opening refuses a camera that delivers different values |

- Opening sets the format, size and rate and checks what the camera actually delivers. OpenCV silently falls back to other values it can deliver, so a mismatch stops the node and says why.
- Only the newest frame is taken, so no backlog of old frames builds up.
- When no frame arrives for 1 s, the camera counts as lost and the node stops.
- Frames are recorded as `observation.images.<name>` (video).
- OpenCV comes with the `hardware` extra.

Find the camera's path and the formats it delivers with the commands below. `v4l2-ctl` is in the v4l-utils package (ask an administrator if it is missing).

```bash
ls -l /dev/v4l/by-path/
v4l2-ctl -d /dev/v4l/by-path/...-video-index0 --list-formats-ext
```

One camera can appear twice, as `video-index0` and `video-index1`. The one that delivers frames is usually `video-index0`.

## D405 (`realsense_rgb`)

The D405's colour stream is expected to work with the existing `realsense_rgb`. Find the serial number with `rs-enumerate-devices` (a librealsense tool).

```yaml
# nodes/left_wrist_d405.yaml
type: realsense_rgb
serial: "230322272619"   # the D405's serial number (example)
width: 640
height: 480
fps: 30
```

Depth is not recorded.

## Checking with mock devices

`.roboloom/piper-mock/` includes the Pika Grippers' fisheye cameras `left_wrist` and `right_wrist`. In mock mode their frames are black.

```bash
uv run roboloom run piper-mock
```

## What to check on hardware

- The formats, sizes and rates the fisheye camera delivers, and whether `video-index0` is the device that delivers frames.
- How many fisheye cameras and D405s one USB controller can carry (up to eight with both hands' Grippers and Senses). If the bandwidth is short, lower the size or rate, or connect them to another controller.
- Whether the D405's colour stream opens as `rgb8`, and which sizes and rates it supports.
- Whether decoding MJPG delays frames (they are stamped when received).
