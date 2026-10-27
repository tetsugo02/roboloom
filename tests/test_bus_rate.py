"""Bus-time savings that let the control loops run faster than 60 Hz."""

from collections import deque

import pytest

from roboloom.runtime.node import _work_fields


def bare_bus(firmware):
    """A DynamixelBus without a port: reads are stubbed."""
    pytest.importorskip("dynamixel_sdk")
    from roboloom.drivers.dynamixel import DynamixelBus

    bus = DynamixelBus.__new__(DynamixelBus)
    bus.fast_read, bus.read_note = False, "sync read"
    bus.read_register = lambda name: list(firmware)
    return bus


def test_fast_sync_read_needs_recent_firmware_on_every_motor():
    bus = bare_bus([46, 44])
    assert not bus.use_fast_read()
    assert not bus.fast_read and "firmware 44" in bus.read_note


def test_fast_sync_read_falls_back_when_the_trial_read_fails():
    bus = bare_bus([46, 49])

    def fail():
        raise ConnectionError("Dynamixel sync read failed")

    bus.read_state = fail
    assert not bus.use_fast_read()
    assert not bus.fast_read and "fast sync read failed" in bus.read_note


def test_fast_sync_read_is_used_when_supported():
    bus = bare_bus([46, 49])
    bus.read_state = lambda: None
    assert bus.use_fast_read() and bus.fast_read and bus.read_note == "fast sync read"


def test_work_time_is_reported_for_the_status_screen():
    assert _work_fields(deque()) == {"work_ms": None, "work_max_ms": None}
    assert _work_fields(deque([4.04, 6.51, 4.2])) == {
        "work_ms": 4.2,
        "work_max_ms": 6.5,
    }
