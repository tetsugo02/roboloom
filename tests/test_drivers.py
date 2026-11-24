import os

import pytest

from roboloom.drivers.base import claim_serial
from roboloom.drivers.dynamixel import DynamixelBus, verify
from roboloom.drivers.dynamixel_table import model_by_name


class FakeBus(DynamixelBus):
    """DynamixelBus with registers served from a dict instead of a serial port."""

    def __init__(self, registers, models=None):
        self.registers, self.models, self.ids = registers, models, [1, 2]

    def read_register(self, name):
        return self.registers[name]


def registers(**changes):
    base = {
        "model_number": [1020, 1220],
        "operating_mode": [3, 5],
        "current_limit": [1193, 30],
        "min_position_limit": [0, 0],
        "max_position_limit": [4095, 4095],
    }
    return {**base, **changes}


def test_verify_accepts_matching_eeprom_and_converts_current_units():
    bus = FakeBus(
        registers(), [model_by_name("XM430-W350"), model_by_name("XC330-T288")]
    )
    expect = {"operating_mode": {"a": 3, "b": 5}, "current_limit": {"a": 3209, "b": 30}}
    limits = [{"min": 100, "max": 4000}, {"min": 0, "max": 4095}]
    assert verify(bus, ["a", "b"], expect, limits) == []


def test_verify_reports_every_mismatch():
    bus = FakeBus(
        registers(
            operating_mode=[0, 5],
            model_number=[1120, 1220],
            max_position_limit=[3000, 4095],
        ),
        [1020, 1220],
    )
    problems = verify(
        bus,
        ["a", "b"],
        {"operating_mode": {"a": 3}},
        [{"min": 100, "max": 4000}, {"min": 0, "max": 4095}],
    )
    assert any("model 1120" in p for p in problems)
    assert any("operating_mode 0" in p for p in problems)
    assert any("outside EEPROM" in p for p in problems)


# -- serial locking -------------------------------------------------------------------


def test_a_serial_port_is_taken_by_the_first_process_only():
    _, slave = os.openpty()
    name = os.ttyname(slave)
    first = os.open(name, os.O_RDWR | os.O_NOCTTY)
    try:
        claim_serial(first, name)
        # the second opener is stopped: at open (TIOCEXCL) or at its own claim (the lock)
        with pytest.raises(OSError):
            second = os.open(name, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            try:
                claim_serial(second, name)
            finally:
                os.close(second)
    finally:
        os.close(first)


def test_the_lock_names_the_port_and_what_may_hold_it(tmp_path):
    path = tmp_path / "ttyFAKE"  # a file takes the lock; it has no TIOCEXCL
    path.write_bytes(b"")
    first, second = os.open(path, os.O_RDWR), os.open(path, os.O_RDWR)
    try:
        claim_serial(first, str(path))
        with pytest.raises(ConnectionError, match="ttyFAKE is in use by another"):
            claim_serial(second, str(path))
    finally:
        os.close(first)
        os.close(second)
    third = os.open(path, os.O_RDWR)  # released when its holder closed it
    try:
        claim_serial(third, str(path))
    finally:
        os.close(third)


# -- fast sync read and retries -------------------------------------------------------


@pytest.mark.parametrize(
    ("firmware", "trial_fails", "expected_fast", "note_fragment"),
    [
        ([46, 44], False, False, "firmware 44"),
        ([46, 49], True, False, "fast sync read failed"),
        ([46, 49], False, True, "fast sync read"),
    ],
)
def test_fast_sync_read_selection(firmware, trial_fails, expected_fast, note_fragment):
    pytest.importorskip("dynamixel_sdk")
    bus = DynamixelBus.__new__(DynamixelBus)
    bus.fast_read, bus.read_note = False, "sync read"
    bus.read_register = lambda name: list(firmware)
    if trial_fails:

        def fail():
            raise ConnectionError("Dynamixel sync read failed")

        bus.read_state = fail
    else:
        bus.read_state = lambda: None
    assert bus.use_fast_read() is expected_fast
    assert bus.fast_read is expected_fast and note_fragment in bus.read_note


class Replies:
    """A Dynamixel sync-read group answering with `results` in turn, then success."""

    def __init__(self, results: list, missing: list[int] | None = None):
        import dynamixel_sdk as dxl

        self.ok = dxl.COMM_SUCCESS
        self.results, self.missing, self.calls = list(results), missing or [], 0

    def txRxPacket(self):
        self.calls += 1
        return self.results.pop(0) if self.results else self.ok

    def isAvailable(self, motor, address, size):
        if self.missing and self.missing[0] == motor:
            self.missing.pop(0)  # missing from this reply only
            return False
        return True

    def getData(self, motor, address, size):
        return 2000 + motor


def _retry_bus(group: Replies, retries: int = 1):
    import dynamixel_sdk as dxl

    class Port:
        class ser:
            dropped = 0

            @classmethod
            def reset_input_buffer(cls):
                cls.dropped += 1

    bus = DynamixelBus.__new__(DynamixelBus)
    bus.ids, bus.fast_read, bus.port = [1, 2], False, Port()
    bus.read_retries, bus.retries = retries, 0
    bus._readers = {(132, 4): group}
    return bus, dxl.COMM_RX_TIMEOUT


def test_a_read_that_fails_once_is_repeated_and_counted():
    bus, timeout = _retry_bus(Replies([]))
    assert bus._read(132, 4) == [[2001], [2002]] and bus.retries == 0
    group = Replies([timeout])
    bus, _ = _retry_bus(group)
    assert bus._read(132, 4) == [[2001], [2002]]
    assert bus.retries == 1 and group.calls == 2
    assert bus.port.ser.dropped == 1  # the rest of the failed reply was dropped first
    bus, _ = _retry_bus(Replies([], missing=[2]))  # missing motor 2, then a whole one
    assert bus._read(132, 4) == [[2001], [2002]] and bus.retries == 1


def test_a_read_that_keeps_failing_still_raises():
    _, timeout = _retry_bus(Replies([]))
    group = Replies([timeout, timeout])
    bus, _ = _retry_bus(group)
    with pytest.raises(ConnectionError, match="sync read failed"):
        bus._read(132, 4)
    assert group.calls == 2 and bus.retries == 1
    bus, _ = _retry_bus(Replies([timeout]), retries=0)  # no retries configured
    with pytest.raises(ConnectionError):
        bus._read(132, 4)
