"""DIGIT seam detection and stream recovery, without hardware or network."""

import time

import numpy as np
import pytest
import yaml

from roboloom.config import load_config
from roboloom.core.source import ConstantReader, Sample
from roboloom.errors import ConfigError
from roboloom.sensors.tactile.digit import DigitReader, DigitSensor
from roboloom.sensors.tactile.seam import find_seam
from roboloom.sensors.vision.base import ShapeCheckedReader
from roboloom.ui.render import RENDERERS


def native_image() -> np.ndarray:
    """A DIGIT-like native frame (240x320x3 uint8): smooth asymmetric illumination
    with a few soft blobs, no hard horizontal edges."""
    y, x = np.mgrid[0:240, 0:320].astype(np.float64)
    r2 = ((y - 120) / 240) ** 2 + ((x - 160) / 320) ** 2
    base = 220.0 - 0.6 * y - 40.0 * r2
    img = np.stack([base, base * 0.92, base * 0.85], axis=2)
    for by, bx, sigma, amp in (
        (60, 80, 25, 40),
        (170, 240, 30, 35),
        (120, 160, 45, 25),
    ):
        blob = amp * np.exp(-((y - by) ** 2 + (x - bx) ** 2) / (2 * sigma**2))
        img += blob[..., None]
    return np.clip(img, 0, 255).astype(np.uint8)


def to_get_frame(native: np.ndarray) -> np.ndarray:
    """What digit.get_frame() returns: the native frame transposed."""
    return native.transpose(1, 0, 2)


def test_clean_image_has_no_seam():
    assert find_seam(to_get_frame(native_image())) is None


def test_contact_shapes_have_no_seam():
    native = native_image()
    y, x = np.mgrid[0:240, 0:320]
    ellipse = native.copy()  # a bright filled ellipse: contact in the middle
    ellipse[((y - 120) / 35) ** 2 + ((x - 160) / 90) ** 2 <= 1] = 255
    assert find_seam(to_get_frame(ellipse)) is None
    circle = native.copy()  # a bright filled circle touching the top edge
    circle[(y - 28) ** 2 + (x - 160) ** 2 <= 28**2] = 255
    assert find_seam(to_get_frame(circle)) is None


@pytest.mark.parametrize("shift", [1, 37, 120, 239 - 1])
def test_rolled_image_seam_is_the_shift(shift):
    rolled = np.roll(native_image(), shift, axis=0)
    assert find_seam(to_get_frame(rolled)) == shift


def test_find_seam_does_not_mutate_the_frame():
    frame = to_get_frame(np.roll(native_image(), 37, axis=0))
    before = frame.copy()
    find_seam(frame)
    np.testing.assert_array_equal(frame, before)


def test_find_seam_rejects_a_2d_array():
    with pytest.raises(ValueError):
        find_seam(np.zeros((240, 320), np.uint8))


def test_find_seam_is_fast_enough_for_every_tick():
    frame = to_get_frame(native_image())  # 320x240x3, as get_frame returns it
    began = time.perf_counter()
    for _ in range(200):
        find_seam(frame)
    assert time.perf_counter() - began < 2.0


class FakeDigit:
    """A list of frames to return in order; counts get_frame calls and disconnects."""

    def __init__(self, frames):
        self.frames = list(frames)
        self.calls = 0
        self.disconnects = 0

    def get_frame(self):
        frame = self.frames[self.calls]
        self.calls += 1
        return frame

    def disconnect(self):
        self.disconnects += 1


class Opener:
    """Hands out digits in order; after the first, raises while `fail` is set."""

    def __init__(self, *digits, fail=False):
        self.digits = list(digits)
        self.opens = 0
        self.fail = fail

    def __call__(self):
        self.opens += 1
        if self.opens > 1 and self.fail:
            raise ConnectionError("usb gone")
        return self.digits.pop(0)  # a failed attempt hands out no digit


def test_warmup_frames_are_discarded_at_open():
    clean = to_get_frame(native_image())
    digit = FakeDigit([clean] * 12)
    opener = Opener(digit)
    reader = DigitReader(opener, "digit", warmup_frames=10, log=lambda _: None)
    assert opener.opens == 1
    assert digit.calls == 10
    sample = reader.read()
    assert isinstance(sample, Sample)
    assert digit.calls == 11
    np.testing.assert_array_equal(sample.value, clean[..., ::-1])
    reader.close()
    assert digit.disconnects == 1


def test_persistent_seams_reopen_the_stream_once():
    native = native_image()
    clean = to_get_frame(native)
    seamed = to_get_frame(np.roll(native, 37, axis=0))
    assert not np.array_equal(clean[..., 0], clean[..., 2])  # channels differ
    first = FakeDigit([seamed] * 6)  # 3 warmup + 3 seam reads
    second = FakeDigit([clean] * 4)  # 3 warmup + 1 read
    opener = Opener(first, second)
    logs = []
    reader = DigitReader(
        opener, "digit", recover_after=3, warmup_frames=3, log=logs.append
    )
    assert first.calls == 3
    for _ in range(3):
        assert reader.read() is None
    assert reader.status() == {"seams": 3, "recoveries": 1, "seam_row": 37}
    assert first.disconnects == 1
    assert opener.opens == 2
    assert second.calls == 3  # warmup discarded after the reopen
    assert logs == ["digit: row seam at 37, reopening the DIGIT stream (recovery 1)"]
    sample = reader.read()  # the next clean frame, BGR reversed to RGB
    np.testing.assert_array_equal(sample.value, clean[..., ::-1])
    assert second.calls == 4
    assert reader.status()["recoveries"] == 1


def test_a_clean_frame_resets_the_consecutive_count():
    native = native_image()
    clean = to_get_frame(native)
    seamed = to_get_frame(np.roll(native, 37, axis=0))
    digit = FakeDigit([seamed, seamed, clean, seamed, seamed])
    opener = Opener(digit)
    reader = DigitReader(
        opener, "digit", recover_after=3, warmup_frames=0, log=lambda _: None
    )
    assert reader.read() is None
    assert reader.read() is None
    assert reader.read() is not None  # clean: resets the count
    assert reader.read() is None
    assert reader.read() is None
    assert reader.status() == {"seams": 4, "recoveries": 0, "seam_row": 37}
    assert opener.opens == 1
    assert digit.disconnects == 0


def test_seam_check_off_returns_every_frame():
    seamed = to_get_frame(np.roll(native_image(), 37, axis=0))
    digit = FakeDigit([seamed] * 5)
    reader = DigitReader(
        Opener(digit), "digit", seam_check=False, warmup_frames=0, log=lambda _: None
    )
    for _ in range(5):
        sample = reader.read()
        np.testing.assert_array_equal(sample.value, seamed[..., ::-1])
    assert reader.status() == {}


def test_failed_reopen_retries_slowly_then_raises():
    native = native_image()
    clean = to_get_frame(native)
    seamed = to_get_frame(np.roll(native, 37, axis=0))
    first = FakeDigit([seamed] * 3)
    second = FakeDigit([clean] * 2)
    opener = Opener(first, second, fail=True)
    now = [0.0]
    attempts = []

    def open_digit():
        if opener.opens:  # reopens only; the first open is not a recovery attempt
            attempts.append(now[0])
        return opener()

    reader = DigitReader(
        open_digit,
        "digit",
        recover_after=3,
        warmup_frames=0,
        lost_s=5.0,
        clock=lambda: now[0],
        log=lambda _: None,
    )
    for _ in range(3):
        assert reader.read() is None
    assert attempts == [0.0]  # recovery started at t=0: the immediate reopen failed
    assert reader.status()["recoveries"] == 1
    now[0] = 0.4
    assert reader.read() is None
    assert attempts == [0.0]  # no retry before 0.5 s
    for t in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0):
        now[0] = t
        assert reader.read() is None
    assert attempts == [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]
    now[0] = 5.5  # failing for longer than lost_s since the recovery started
    with pytest.raises(
        ConnectionError, match="digit: cannot reopen the DIGIT stream for 5 s: usb gone"
    ):
        reader.read()
    opener.fail = False  # a later success clears the failure
    now[0] = 6.0
    sample = reader.read()
    np.testing.assert_array_equal(sample.value, clean[..., ::-1])
    assert reader.status()["recoveries"] == 1
    assert reader.read() is not None


def digit_cfg(**extra):
    cfg = {"height": 320, "width": 240, "fps": 30, "serial": "D1"}
    cfg.update(extra)
    return cfg


def test_sensor_defaults():
    sensor = DigitSensor("digit", digit_cfg())
    assert sensor.seam_check is True
    assert sensor.recover_after == 3
    assert sensor.warmup_frames == 10


@pytest.mark.parametrize("value", ["yes", 1, 0, None])
def test_seam_check_must_be_a_bool(value):
    with pytest.raises(TypeError, match="digit.seam_check"):
        DigitSensor("digit", digit_cfg(seam_check=value))


@pytest.mark.parametrize("value", [0, True, 1.5, -1, "3"])
def test_recover_after_must_be_an_int_at_least_one(value):
    with pytest.raises(ValueError, match="digit.recover_after"):
        DigitSensor("digit", digit_cfg(recover_after=value))


@pytest.mark.parametrize("value", [-1, True, 2.5, "10"])
def test_warmup_frames_must_be_a_non_negative_int(value):
    with pytest.raises(ValueError, match="digit.warmup_frames"):
        DigitSensor("digit", digit_cfg(warmup_frames=value))


def write_project(tmp_path, digit_cfg_extra):
    (tmp_path / "digit.yaml").write_text(
        yaml.safe_dump(
            {
                "type": "digit",
                "height": 320,
                "width": 240,
                "fps": 30,
                "serial": "D1",
                **digit_cfg_extra,
            }
        )
    )
    (tmp_path / "recorder.yaml").write_text("max_age_ms: {digit: 1000}\n")
    (tmp_path / "session.yaml").write_text("type: terminal\n")
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "repo_id": "local/seam",
                "output": "data",
                "mode": "mock",
                "dataset_fps": 10,
                "followers": {},
                "sensors": {"digit": "digit.yaml"},
                "recorder": "recorder.yaml",
                "session": "session.yaml",
            }
        )
    )
    return path


def test_unknown_keys_are_refused_at_config_load(tmp_path):
    path = write_project(tmp_path, {"seam_chek": True})
    with pytest.raises(ConfigError, match="sensors.digit: unknown keys seam_chek"):
        load_config(path)


def test_new_keys_load(tmp_path):
    path = write_project(
        tmp_path, {"seam_check": False, "recover_after": 5, "warmup_frames": 2}
    )
    sensor = load_config(path).sensors["digit"]
    assert sensor.seam_check is False
    assert sensor.recover_after == 5
    assert sensor.warmup_frames == 2


def test_shape_checked_reader_forwards_status():
    class Inner:
        def read(self):
            return None

        def close(self):
            pass

        def status(self):
            return {"seams": 2}

    reader = ShapeCheckedReader("digit", Inner(), (320, 240, 3))
    assert reader.status() == {"seams": 2}


def test_shape_checked_reader_without_inner_status():
    reader = ShapeCheckedReader(
        "cam", ConstantReader(np.zeros((320, 240, 3), np.uint8)), (320, 240, 3)
    )
    assert reader.status() == {}


def test_source_render_shows_seams_and_recoveries():
    _, detail = RENDERERS["sensor"](
        {"rate_hz": 30, "age_ms": 10, "misses": 4, "seams": 3, "recoveries": 1}
    )
    assert "seams 3  recoveries 1" in detail.plain
    spans = {detail.plain[s.start : s.end]: str(s.style) for s in detail.spans}
    assert spans["seams 3  recoveries 1"] == "yellow"
    _, detail = RENDERERS["sensor"]({"rate_hz": 30, "age_ms": 10, "misses": 0})
    assert "seams" not in detail.plain
    _, detail = RENDERERS["sensor"](
        {"rate_hz": 30, "age_ms": 10, "seams": 0, "recoveries": 0}
    )
    assert "seams" not in detail.plain
