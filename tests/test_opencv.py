"""Webcam contracts without importing OpenCV or touching hardware."""

import sys
from types import SimpleNamespace

import numpy as np
import pytest
from conftest import rakuda2_tree
from test_v4l2 import fake_cv2, fourcc

from roboloom.config import parse_config
from roboloom.sensors import SENSORS
from roboloom.sensors.vision._opencv import OpenCVReader
from roboloom.sensors.vision.base import ShapeCheckedReader
from roboloom.sensors.vision.opencv import OpenCVRGB


def cfg(**changes):
    return dict(type="opencv_rgb", device=0, width=64, height=48, fps=30, **changes)


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


def test_fps_format_warnings_and_shape_validation(monkeypatch):
    made = fake_cv2(monkeypatch, delivers={5: 0, 6: 0})
    with pytest.warns(RuntimeWarning) as warnings:
        reader = OpenCVRGB("camera", cfg(format="MJPG")).open(False, 10)
    assert len(warnings) == 2
    capture = made[0]
    capture.frames.append(np.zeros((480, 640, 3), np.uint8))
    try:
        with pytest.raises(ValueError, match="configured"):
            reader.read()
    finally:
        reader.close()
    assert capture.released


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


def test_path_and_platform_mismatch(monkeypatch, tmp_path):
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


def test_shared_reader_lost_device(monkeypatch):
    from test_v4l2 import FakeCapture

    from roboloom.sensors.vision._opencv import OpenCVReader

    now = SimpleNamespace(value=0)
    reader = OpenCVReader(
        FakeCapture(0, 200), SimpleNamespace(), "0", clock=lambda: now.value
    )
    assert reader.read() is None
    now.value = 1.1
    with pytest.raises(ConnectionError, match="no frame"):
        reader.read()


@pytest.mark.parametrize("reported", [15, 0, float("nan")])
def test_fps_mismatch_warns_and_continues(monkeypatch, reported):
    made = fake_cv2(monkeypatch, delivers={5: reported})
    with pytest.warns(RuntimeWarning, match="fps requested=30"):
        reader = OpenCVRGB("camera", cfg()).open(False, 10)
    reader.close()
    assert made[0].released


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


def test_actual_dtype_is_checked_even_if_properties_match(monkeypatch):
    made = fake_cv2(monkeypatch)
    reader = OpenCVRGB("camera", cfg()).open(False, 10)
    made[0].frames.append(np.zeros((48, 64, 3), np.float32))
    try:
        with pytest.raises(ValueError, match="uint8"):
            reader.read()
    finally:
        reader.close()
    assert made[0].released


def test_format_warning_names_the_reported_fourcc(monkeypatch):
    made = fake_cv2(monkeypatch, delivers={6: fourcc("YUYV")})
    with pytest.warns(RuntimeWarning, match="format requested=MJPG, reported=YUYV"):
        reader = OpenCVRGB("camera", cfg(format="MJPG")).open(False, 10)
    reader.close()
    assert made[0].released


def test_broken_opencv_import_names_the_cause(monkeypatch):
    def broken(name, *args, **kwargs):
        raise ImportError("libGL.so.1: cannot open shared object file")

    monkeypatch.setattr("roboloom.sensors.vision.opencv.import_module", broken)
    with pytest.raises(ImportError, match="libGL.so.1.*core dependency"):
        OpenCVRGB("camera", cfg()).open(False, 10)


def test_frames_are_shape_checked_once(monkeypatch):
    fake_cv2(monkeypatch)
    reader = OpenCVRGB("camera", cfg()).open(False, 10)
    assert isinstance(reader, ShapeCheckedReader)
    assert isinstance(reader.reader, OpenCVReader)
    reader.close()
