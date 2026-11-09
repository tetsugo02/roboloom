"""Pika Sense input: the tracker, the serial link, the clutch, and the mock."""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from roboloom.drivers.survive import SurviveTracker
from roboloom.inputs.base import POSE_FIELDS
from roboloom.inputs.pika_sense.sense import MockSense, PikaSense, SenseReader
from roboloom.inputs.pika_sense.spec import TRACKER_TO_SENSE
from roboloom.kinematics.spec import pose_from


class Clock:
    def __init__(self) -> None:
        self.now = 10.0

    def __call__(self) -> float:
        return self.now


class FakeLink:
    """PikaSerial's `latest` for the Sense keys, stamped by `clock`."""

    def __init__(self, clock: Clock):
        self.clock = clock
        self.values: dict = {"AS5047": {"angle": 40.0, "rad": 0.7}, "Command": 0}
        self.silent = False
        self.closed = False

    def latest(self, key):
        if self.silent or key not in self.values:
            return None
        return self.values[key], self.clock.now

    def close(self):
        self.closed = True


class FakeTracker:
    def __init__(self, clock: Clock):
        self.clock = clock
        self.pose = pose_from([1.0, 2.0, 0.5], [0, 0, 0, 1])
        self.stamp: float | None = clock.now
        self.closed = False

    def latest(self):
        return None if self.stamp is None else (self.pose, self.stamp)

    def close(self):
        self.closed = True


def reader():
    clock = Clock()
    link, tracker = FakeLink(clock), FakeTracker(clock)
    return SenseReader(link, tracker, 0.1, clock), link, tracker, clock


def fields(sample) -> dict:
    return dict(zip(POSE_FIELDS, sample.value.tolist(), strict=True))


def test_the_pose_is_moved_to_the_jaws_and_the_jaw_angle_read():
    sense, _, tracker, _ = reader()
    f = fields(sense.read())
    expected = tracker.pose @ TRACKER_TO_SENSE
    assert [f["x"], f["y"], f["z"]] == pytest.approx(expected[:3, 3].tolist())
    assert f["gripper"] == 0.7 and f["tracking"] == 1.0 and f["engaged"] == 0.0
    # the vendor's offset: 0.172 m forward and 0.076 m down from the tracker
    assert np.linalg.norm(TRACKER_TO_SENSE[:3, 3]) == pytest.approx(
        math.hypot(0.172, 0.076)
    )


def test_each_change_of_command_engages_or_disengages():
    sense, link, _, _ = reader()
    assert fields(sense.read())["engaged"] == 0.0  # the first value is only a baseline
    link.values["Command"] = 1
    assert fields(sense.read())["engaged"] == 1.0
    assert fields(sense.read())["engaged"] == 1.0
    link.values["Command"] = 0
    assert fields(sense.read())["engaged"] == 0.0


def test_losing_the_pose_or_the_serial_link_disengages():
    sense, link, tracker, clock = reader()
    sense.read()
    link.values["Command"] = 1
    assert fields(sense.read())["engaged"] == 1.0
    clock.now += 0.5  # the tracker's pose is 0.5 s old: not tracked
    link.values["Command"] = 1
    tracker.stamp = 10.0
    f = fields(sense.read())
    assert f["tracking"] == 0.0 and f["engaged"] == 0.0
    tracker.stamp = clock.now  # tracked again, but the operator must engage again
    assert fields(sense.read())["engaged"] == 0.0
    link.values["Command"] = 0
    assert fields(sense.read())["engaged"] == 1.0
    link.silent = True  # serial lost: no way to disengage, so it disengages
    f = fields(sense.read())
    assert f["engaged"] == 0.0 and math.isnan(f["gripper"])
    sense.close()
    assert link.closed and tracker.closed


def test_libsurvive_poses_are_kept_for_the_named_tracker_only():
    clock = Clock()
    context = SimpleNamespace(Running=lambda: False)  # the thread ends at once
    tracker = SurviveTracker("WM0", context=context, clock=clock)
    pose = SimpleNamespace(Pos=[0.1, 0.2, 0.3], Rot=[1.0, 0.0, 0.0, 0.0])  # w, x, y, z
    tracker.take("WM1", pose)
    assert tracker.latest() is None and tracker.objects() == ["WM1"]
    tracker.take("WM0", pose)
    got = tracker.latest()
    assert got is not None and got[1] == clock.now
    assert np.allclose(got[0], pose_from([0.1, 0.2, 0.3], [0, 0, 0, 1]))
    tracker.close()


def test_without_pysurvive_the_error_explains_the_extra_and_system_requirements(
    monkeypatch,
):
    import builtins

    real = builtins.__import__

    def no_survive(name, *args, **kwargs):
        if name == "pysurvive":
            raise ImportError("no pysurvive")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_survive)
    with pytest.raises(ConnectionError, match=r"roboloom\[pika\]") as error:
        SurviveTracker("WM0")
    assert "administrator" in str(error.value)


def sense_cfg(**extra) -> dict:
    return {
        "type": "pika_sense",
        "port": "/dev/serial/by-path/mock-sense",
        "tracker": {"name": "WM0"},
        **extra,
    }


def test_the_input_checks_its_configuration_and_records_nine_values():
    sense = PikaSense("left_sense", sense_cfg())
    assert sense.device_ids() == ("/dev/serial/by-path/mock-sense", "libsurvive:WM0")
    for bad, error in (
        ({"port": "SET_PORT"}, ValueError),
        ({"tracker": "WM0"}, TypeError),
        ({"tracker": {"name": "SET_TRACKER"}}, ValueError),
        ({"tracker": {"name": "WM0", "args": "--lh"}}, ValueError),
        ({"stale_ms": 0}, ValueError),
    ):
        with pytest.raises(error):
            PikaSense("left_sense", sense_cfg(**bad))
    feature = sense.features(10)["observation.left_sense"]
    assert feature["shape"] == (10,) and feature["names"][-2:] == [
        "tracking",
        "engaged",
    ]
    payload = sense.encode(MockSense().read())
    assert payload["frame"] == "libsurvive" and payload["tracking"] is True
    frame = sense.frame(None, 10)["observation.left_sense"]
    assert frame.shape == (10,)


def test_the_mock_engages_after_two_seconds_and_cycles():
    clock = Clock()
    mock = MockSense(clock=clock)
    engaged = []
    for t in (0.0, 1.9, 2.1, 11.9, 12.5, 14.1):
        clock.now = 10.0 + t
        engaged.append(fields(mock.read())["engaged"])
    assert engaged == [0.0, 0.0, 1.0, 1.0, 0.0, 1.0]
