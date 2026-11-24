"""OpenCV and V4L2 webcam contracts without importing OpenCV or touching hardware."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np
import pytest
from conftest import rakuda2_tree

from roboloom.config import parse_config
from roboloom.sensors import SENSORS
from roboloom.sensors.vision._opencv import OpenCVReader
from roboloom.sensors.vision.base import ShapeCheckedReader
from roboloom.sensors.vision.opencv import OpenCVRGB
from roboloom.sensors.vision.v4l2 import LOST_S, V4l2Reader, V4l2RGB


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


def cfg(**changes):
    return dict(type="opencv_rgb", device=0, width=64, height=48, fps=30, **changes)


def v4l2_cfg(**extra) -> dict:
    return {
        "type": "v4l2_rgb",
        "device": "/dev/v4l/by-path/pci-0000:00:14.0-usb-0:2:1.0-video-index0",
        "width": 64,
        "height": 48,
        "fps": 30,
        **extra,
    }


@pytest.mark.parametrize(
    "platform,backend,api",
    [
        ("linux", "auto", 200),
        ("darwin", "auto", 1200),
        ("win32", "auto", 1400),
        ("win32", "dshow", 700),
    ],
)
def test_backends_and_rgb(monkeypatch, platform, backend, api):
    made = fake_cv2(monkeypatch)
    monkeypatch.setattr(sys, "platform", platform)
    camera = OpenCVRGB("camera", cfg(backend=backend))
    reader = camera.open(False, 10)
    assert isinstance(reader, ShapeCheckedReader)
    assert isinstance(reader.reader, OpenCVReader)
    capture = made[0]
    assert capture.path == 0 and capture.api == api
    capture.frames.append(np.full((48, 64, 3), [255, 0, 0], np.uint8))
    sample = reader.read()
    assert sample.value[0, 0].tolist() == [0, 0, 255]
    assert sample.value.flags.c_contiguous and sample.capture_ns > 0
    reader.close()
    assert capture.released


@pytest.mark.parametrize(
    "changes",
    [
        {"device": True},
        {"device": -1},
        {"device": "0"},
        {"device": "movie.mp4"},
        {"device": "rtsp://camera"},
        {"device": "/dev/../movie"},
        {"device": None},
        {"backend": "bogus"},
        {"fps": 0},
        {"width": 1.5},
        {"height": True},
        {"format": "H264"},
    ],
)
def test_invalid_config(changes):
    with pytest.raises(ValueError):
        OpenCVRGB("camera", {**cfg(), **changes})


def test_validation_and_mock_do_not_import_opencv(monkeypatch):
    monkeypatch.setitem(sys.modules, "cv2", None)
    camera = SENSORS.get("opencv_rgb")("camera", cfg())
    reader = camera.open(True, 10)
    assert reader.read().value.shape == (48, 64, 3)
    reader.close()
    with pytest.raises(ModuleNotFoundError, match="core dependency"):
        camera.open(False, 10)


@pytest.mark.parametrize(
    ("delivers", "extra", "expected_count", "match"),
    [
        ({5: 0, 6: 0}, {"format": "MJPG"}, 2, None),
        ({5: 15}, {}, 1, "fps requested=30"),
        ({5: 0}, {}, 1, "fps requested=30"),
        ({5: float("nan")}, {}, 1, "fps requested=30"),
        (
            {6: fourcc("YUYV")},
            {"format": "MJPG"},
            1,
            "format requested=MJPG, reported=YUYV",
        ),
    ],
)
def test_fps_and_format_warnings(monkeypatch, delivers, extra, expected_count, match):
    made = fake_cv2(monkeypatch, delivers=delivers)
    with pytest.warns(RuntimeWarning, match=match) as warnings:
        reader = OpenCVRGB("camera", cfg(**extra)).open(False, 10)
    assert len(warnings) == expected_count
    reader.close()
    assert made[0].released


@pytest.mark.parametrize(
    ("frame", "match"),
    [
        (np.zeros((480, 640, 3), np.uint8), "configured"),
        (np.zeros((48, 64, 3), np.float32), "uint8"),
    ],
)
def test_invalid_frame_shape_or_dtype_raises_and_releases(monkeypatch, frame, match):
    made = fake_cv2(monkeypatch)
    reader = OpenCVRGB("camera", cfg()).open(False, 10)
    made[0].frames.append(frame)
    try:
        with pytest.raises(ValueError, match=match):
            reader.read()
    finally:
        reader.close()
    assert made[0].released


def test_failed_open_and_configuration_exception_release(monkeypatch):
    made = fake_cv2(monkeypatch, opened=False)
    with pytest.raises(ConnectionError, match="permissions"):
        OpenCVRGB("camera", cfg()).open(False, 10)
    assert made[0].released
    made = fake_cv2(monkeypatch)
    cv2 = sys.modules["cv2"]
    constructor = cv2.VideoCapture

    def capture(path, api):
        result = constructor(path, api)
        result.set = lambda *args: (_ for _ in ()).throw(RuntimeError("setting failed"))
        return result

    monkeypatch.setattr(cv2, "VideoCapture", capture)
    with pytest.raises(RuntimeError, match="setting failed"):
        OpenCVRGB("camera", cfg()).open(False, 10)
    assert made[0].released


def test_path_and_platform_mismatch(monkeypatch):
    made = fake_cv2(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        "roboloom.sensors.vision.opencv.os.path.realpath", lambda path: "/dev/video2"
    )
    camera = OpenCVRGB("camera", {**cfg(), "device": "/dev/v4l/by-id/camera"})
    reader = camera.open(False, 10)
    assert made[0].path == "/dev/video2"
    reader.close()
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(ValueError, match="unavailable"):
        camera.open(False, 10)
    assert len(made) == 1


def test_duplicate_indices_paths_and_legacy_v4l2(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    tree = rakuda2_tree()
    tree["sensors"]["camera"] = cfg()
    tree["sensors"]["other"] = {**cfg(), "type": "v4l2_rgb", "device": "/dev/video0"}
    tree["recorder"]["max_age_ms"]["other"] = 200
    with pytest.raises(ValueError, match="duplicate"):
        parse_config(tree)
    for platform in ("darwin", "win32"):
        monkeypatch.setattr(sys, "platform", platform)
        tree["sensors"]["other"] = cfg()
        with pytest.raises(ValueError, match="duplicate"):
            parse_config(tree)


def test_shared_reader_lost_device():
    assert issubclass(V4l2Reader, OpenCVReader)
    now = SimpleNamespace(value=5.0)
    reader = OpenCVReader(
        FakeCapture(0, 200), SimpleNamespace(), "0", clock=lambda: now.value
    )
    assert reader.read() is None
    now.value += LOST_S + 0.1
    with pytest.raises(ConnectionError, match="no frame"):
        reader.read()


def test_configuration_builds_camera_dataflow_without_cv2(monkeypatch):
    from roboloom.runtime.flow import build_flow

    monkeypatch.setitem(sys.modules, "cv2", None)
    tree = rakuda2_tree()
    tree["sensors"]["camera"] = cfg()
    config = parse_config(tree)
    assert isinstance(config.sensors["camera"], OpenCVRGB)
    assert config.sensors["camera"].features(10)["observation.images.camera"][
        "shape"
    ] == (48, 64, 3)
    assert any(node["id"] == "camera" for node in build_flow(config)["nodes"])


def test_broken_opencv_import_names_the_cause(monkeypatch):
    def broken(name, *args, **kwargs):
        raise ImportError("libGL.so.1: cannot open shared object file")

    monkeypatch.setattr("roboloom.sensors.vision.opencv.import_module", broken)
    with pytest.raises(ImportError, match="libGL.so.1.*core dependency"):
        OpenCVRGB("camera", cfg()).open(False, 10)


# -- V4L2 ----------------------------------------------------------------------------


def test_v4l2_configuration_is_checked():
    camera = V4l2RGB("left_wrist", v4l2_cfg())
    assert camera.format == "MJPG" and camera.shape == (48, 64, 3)
    assert camera.device_ids()[0] == v4l2_cfg()["device"]
    for bad in ({"device": "SET_DEVICE"}, {"format": "H264"}, {"fps": 0}):
        with pytest.raises(ValueError):
            V4l2RGB("left_wrist", v4l2_cfg(**bad))


def test_v4l2_opening_sets_the_format_and_reads_rgb(monkeypatch):
    made = fake_cv2(monkeypatch)
    reader = V4l2RGB("left_wrist", v4l2_cfg(format="YUYV")).open_device()
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


def test_v4l2_camera_that_does_not_deliver_the_settings_is_refused(monkeypatch):
    made = fake_cv2(monkeypatch, delivers={3: 640, 4: 480})
    with pytest.raises(ValueError, match="delivers 640x480.*v4l2-ctl"):
        V4l2RGB("left_wrist", v4l2_cfg()).open_device()
    assert made[0].released
    fake_cv2(monkeypatch, opened=False)
    with pytest.raises(ConnectionError, match="by-path"):
        V4l2RGB("left_wrist", v4l2_cfg()).open_device()
