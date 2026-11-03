"""V4L2 (UVC) cameras against a fake OpenCV: settings, colour order, loss, release."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np
import pytest

from roboloom.sensors.vision.v4l2 import LOST_S, V4l2Reader, V4l2RGB


def camera_cfg(**extra) -> dict:
    return {
        "type": "v4l2_rgb",
        "device": "/dev/v4l/by-path/pci-0000:00:14.0-usb-0:2:1.0-video-index0",
        "width": 64,
        "height": 48,
        "fps": 30,
        **extra,
    }


def fourcc(text: str) -> int:
    return sum(ord(c) << (8 * i) for i, c in enumerate(text))


class FakeCapture:
    """cv2.VideoCapture that accepts settings unless told what it delivers."""

    def __init__(self, path, api, *, opened=True, delivers=None):
        self.path, self.api, self.opened = path, api, opened
        self.props: dict[int, float] = {}
        self.delivers = delivers or {}
        self.frames: list = []
        self.released = False

    def isOpened(self):
        return self.opened

    def set(self, prop, value):
        self.props[prop] = value
        return True

    def get(self, prop):
        return float(self.delivers.get(prop, self.props.get(prop, 0)))

    def read(self):
        if not self.frames:
            return False, None
        return True, self.frames.pop(0)

    def release(self):
        self.released = True


def fake_cv2(monkeypatch, **capture_kwargs):
    made: list[FakeCapture] = []

    def capture(path, api):
        made.append(FakeCapture(path, api, **capture_kwargs))
        return made[-1]

    cv2 = SimpleNamespace(
        CAP_V4L2=200,
        CAP_PROP_FOURCC=6,
        CAP_PROP_FRAME_WIDTH=3,
        CAP_PROP_FRAME_HEIGHT=4,
        CAP_PROP_FPS=5,
        CAP_PROP_BUFFERSIZE=38,
        COLOR_BGR2RGB=4,
        VideoCapture=capture,
        VideoWriter_fourcc=lambda *c: fourcc("".join(c)),
        cvtColor=lambda frame, code: frame[..., ::-1],
    )
    monkeypatch.setitem(sys.modules, "cv2", cv2)
    return made


def test_the_configuration_is_checked():
    camera = V4l2RGB("left_wrist", camera_cfg())
    assert camera.format == "MJPG" and camera.shape == (48, 64, 3)
    assert camera.device_ids()[0] == camera_cfg()["device"]
    for bad in ({"device": "SET_DEVICE"}, {"format": "H264"}, {"fps": 0}):
        with pytest.raises(ValueError):
            V4l2RGB("left_wrist", camera_cfg(**bad))


def test_opening_sets_the_format_and_reads_rgb(monkeypatch):
    made = fake_cv2(monkeypatch)
    reader = V4l2RGB("left_wrist", camera_cfg(format="YUYV")).open_device()
    capture = made[0]
    assert capture.api == 200 and capture.props[38] == 1  # newest frame only
    assert capture.props[6] == fourcc("YUYV") and capture.props[5] == 30.0
    bgr = np.zeros((48, 64, 3), np.uint8)
    bgr[..., 0] = 255  # blue in OpenCV's order
    capture.frames.append(bgr)
    sample = reader.read()
    assert sample is not None and sample.value[0, 0].tolist() == [0, 0, 255]
    reader.close()
    assert capture.released


def test_a_camera_that_does_not_deliver_the_settings_is_refused(monkeypatch):
    made = fake_cv2(monkeypatch, delivers={3: 640, 4: 480})
    with pytest.raises(ValueError, match="delivers 640x480.*v4l2-ctl"):
        V4l2RGB("left_wrist", camera_cfg()).open_device()
    assert made[0].released
    fake_cv2(monkeypatch, opened=False)
    with pytest.raises(ConnectionError, match="by-path"):
        V4l2RGB("left_wrist", camera_cfg()).open_device()


def test_a_camera_that_stops_delivering_is_a_lost_device():
    capture = FakeCapture("/dev/video0", 200)
    clock = SimpleNamespace(now=5.0)
    reader = V4l2Reader(
        capture,
        SimpleNamespace(COLOR_BGR2RGB=4, cvtColor=lambda f, c: f),
        "/dev/video0",
        clock=lambda: clock.now,
    )
    assert reader.read() is None  # one missed frame is fine
    clock.now += LOST_S + 0.1
    with pytest.raises(ConnectionError, match="no frame"):
        reader.read()


def test_the_mock_gives_black_frames_of_the_configured_shape():
    reader = V4l2RGB("left_wrist", camera_cfg()).open(mock=True, dataset_fps=10)
    sample = reader.read()
    assert sample is not None and sample.value.shape == (48, 64, 3)
