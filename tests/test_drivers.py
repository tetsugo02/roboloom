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
        "model_number": [1020, 1220], "operating_mode": [3, 5], "current_limit": [1193, 30],
        "min_position_limit": [0, 0], "max_position_limit": [4095, 4095],
    }
    return {**base, **changes}


def test_verify_accepts_matching_eeprom_and_converts_current_units():
    bus = FakeBus(registers(), [model_by_name("XM430-W350"), model_by_name("XC330-T288")])
    expect = {"operating_mode": {"a": 3, "b": 5}, "current_limit": {"a": 3209, "b": 30}}
    limits = [{"min": 100, "max": 4000}, {"min": 0, "max": 4095}]
    assert verify(bus, ["a", "b"], expect, limits) == []


def test_verify_reports_every_mismatch():
    bus = FakeBus(registers(operating_mode=[0, 5], model_number=[1120, 1220], max_position_limit=[3000, 4095]), [1020, 1220])
    problems = verify(bus, ["a", "b"], {"operating_mode": {"a": 3}}, [{"min": 100, "max": 4000}, {"min": 0, "max": 4095}])
    assert any("model 1120" in p for p in problems)
    assert any("operating_mode 0" in p for p in problems)
    assert any("outside EEPROM" in p for p in problems)
