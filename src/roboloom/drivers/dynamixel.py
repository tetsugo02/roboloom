"""Dynamixel Protocol 2.0 X-series bus.

Startup only reads EEPROM: `verify` compares it with the configuration and the
caller refuses to run on any mismatch. RAM registers written here are goal
values, torque enable and Bus Watchdog.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

import dynamixel_sdk as dxl

from .base import HEALTH_FIELDS, Health, JointState, health_from
from .dynamixel_table import (
    COUNTS_PER_REV,
    FAST_SYNC_READ_FIRMWARE,
    MODELS,
    REGISTERS,
    STATE_ADDRESS,
    STATE_SIZE,
    VELOCITY_RPM,
    WATCHDOG_MS,
    Register,
)


def _signed(raw: int, size: int) -> int:
    return raw - 2 ** (size * 8) if raw >= 2 ** (size * 8 - 1) else raw


def latency_timer_ms(port: str) -> int | None:
    """FTDI latency timer of a /dev/ttyUSB* port (by-id links resolved); None if not FTDI."""
    path = (
        Path("/sys/bus/usb-serial/devices")
        / Path(os.path.realpath(port)).name
        / "latency_timer"
    )
    try:
        return int(path.read_text())
    except (OSError, ValueError):
        return None


class DynamixelBus:
    """Sync I/O in the given motor order. `models` are the expected model numbers.

    Reads use Fast Sync Read (one reply packet for every motor) once `use_fast_read`
    found all firmware recent enough; on 17 motors at 1 Mbps the state read drops from
    5 to 4 ms (2026-10-27).
    """

    def __init__(
        self,
        port: str,
        motor_ids: list[int],
        models: list[int] | None = None,
        baudrate: int = 1_000_000,
    ):
        self.ids = list(motor_ids)
        self.models = list(models) if models is not None else None
        self.port_name = port
        self.port = dxl.PortHandler(port)
        self.packet = dxl.PacketHandler(2.0)
        self._readers: dict[tuple[int, int], dxl.GroupSyncRead] = {}
        self._units: list[float] | None = None
        self.fast_read = False
        self.read_note = "sync read"  # how reads are done, for probe and status
        if not self.port.openPort() or not self.port.setBaudRate(baudrate):
            raise ConnectionError(f"cannot open Dynamixel bus {port}")
        # The SDK drains the serial output (tcdrain) before every packet, so each write
        # waits for the previous one to leave the adapter: 1.9 ms per leader tick on FTDI
        # (2026-10-27). Packets stay in order without it (one writer per bus), and reads
        # still wait for their replies.
        self.port.clearPort = lambda: None
        if self.models is not None and len(self.models) != len(self.ids):
            raise ValueError("one model per motor ID required")

    def _read(
        self, address: int, size: int, fields: list[tuple[int, int]] | None = None
    ) -> list[list[int]]:
        """Sync-read `size` bytes from `address`; return signed `fields` (address, size) per motor."""
        group = self._readers.get((address, size))
        if group is None:
            group = dxl.GroupSyncRead(self.port, self.packet, address, size)
            for motor_id in self.ids:
                if not group.addParam(motor_id):
                    raise ConnectionError(f"cannot register motor {motor_id}")
            self._readers[(address, size)] = group
        result = group.fastSyncRead() if self.fast_read else group.txRxPacket()
        if result != dxl.COMM_SUCCESS:
            raise ConnectionError("Dynamixel sync read failed")
        out = []
        for motor_id in self.ids:
            if not group.isAvailable(motor_id, address, size):
                raise ConnectionError(f"missing motor {motor_id}")
            out.append(
                [
                    _signed(group.getData(motor_id, a, n), n)
                    for a, n in fields or [(address, size)]
                ]
            )
        return out

    def _write(
        self, address: int, size: int, values: list[int], ids: list[int] | None = None
    ) -> None:
        group = dxl.GroupSyncWrite(self.port, self.packet, address, size)
        for motor_id, value in zip(ids or self.ids, values, strict=True):
            data = list(int(value).to_bytes(size, "little", signed=True))
            if not group.addParam(motor_id, data):
                raise ConnectionError(f"cannot register motor {motor_id}")
        if group.txPacket() != dxl.COMM_SUCCESS:
            raise ConnectionError("Dynamixel sync write failed")

    def read_register(self, name: str) -> list[int]:
        reg: Register = REGISTERS[name]
        return [values[0] for values in self._read(reg.address, reg.size)]

    def _current_unit(self) -> list[float]:
        if self._units is None:
            models = self.models or self.read_register("model_number")
            self._units = [
                MODELS[m].current_mA if m in MODELS else float("nan") for m in models
            ]
        return self._units

    def read_positions(self) -> list[float]:
        return [float(x) for x in self.read_register("present_position")]

    def read_state(self) -> JointState:
        rows = self._read(STATE_ADDRESS, STATE_SIZE, [(126, 2), (128, 4), (132, 4)])
        current, velocity, position = zip(*rows, strict=True)
        per_s = VELOCITY_RPM / 60 * COUNTS_PER_REV
        return JointState(
            positions=[float(x) for x in position],
            velocities=[v * per_s for v in velocity],
            currents_mA=[
                c * unit for c, unit in zip(current, self._current_unit(), strict=True)
            ],
        )

    def use_fast_read(self) -> bool:
        """Switch reads to Fast Sync Read when every motor's firmware supports it and one
        trial read succeeds; otherwise keep the plain sync read. Returns whether it is on."""
        firmware = self.read_register("firmware_version")
        if min(firmware) < FAST_SYNC_READ_FIRMWARE:
            self.read_note = (
                f"sync read (firmware {min(firmware)} < {FAST_SYNC_READ_FIRMWARE})"
            )
            return False
        self.fast_read = True
        try:
            self.read_state()
        except ConnectionError as exc:
            self.fast_read = False
            self.read_note = f"sync read (fast sync read failed: {exc})"
            return False
        self.read_note = "fast sync read"
        return True

    def read_health_field(self, name: str) -> list[int]:
        """One of HEALTH_FIELDS, so a caller can spread health reads over ticks."""
        if name not in HEALTH_FIELDS:
            raise KeyError(name)
        return self.read_register(name)

    def read_health(self) -> Health:
        return health_from({n: self.read_health_field(n) for n in HEALTH_FIELDS})

    def write_positions(self, values: list[float]) -> None:
        reg = REGISTERS["goal_position"]
        self._write(reg.address, reg.size, [round(x) for x in values])

    def enable_torque(self) -> None:
        self._write(REGISTERS["torque_enable"].address, 1, [1] * len(self.ids))

    def disable_torque(self) -> None:
        self._write(REGISTERS["torque_enable"].address, 1, [0] * len(self.ids))

    def write_goal_positions(self, indices: list[int], values: list[float]) -> None:
        reg = REGISTERS["goal_position"]
        self._write(
            reg.address,
            reg.size,
            [round(x) for x in values],
            [self.ids[i] for i in indices],
        )

    def write_goal_currents(self, indices: list[int], values_mA: list[float]) -> None:
        """Goal Current in mA, converted per motor model; the motor clips at Current Limit."""
        units = self._current_unit()
        counts = [
            max(-32767, min(32767, round(v / units[i])))
            for i, v in zip(indices, values_mA, strict=True)
        ]
        reg = REGISTERS["goal_current"]
        self._write(reg.address, reg.size, counts, [self.ids[i] for i in indices])

    def read_goal_currents(self) -> list[float]:
        return [
            c * u
            for c, u in zip(
                self.read_register("goal_current"), self._current_unit(), strict=True
            )
        ]

    def set_torque(self, indices: list[int], on: bool) -> None:
        self._write(
            REGISTERS["torque_enable"].address,
            1,
            [int(on)] * len(indices),
            [self.ids[i] for i in indices],
        )

    def write_eeprom(self, name: str, indices: list[int], values: list[int]) -> None:
        """EEPROM write for commissioning only; the motors must already have torque off."""
        reg = REGISTERS[name]
        if not reg.eeprom:
            raise ValueError(f"{name} is not an EEPROM register")
        torque = self.read_register("torque_enable")
        if any(torque[i] for i in indices):
            raise RuntimeError("torque must be off before writing EEPROM")
        self._write(reg.address, reg.size, values, [self.ids[i] for i in indices])
        back = self.read_register(name)
        if [back[i] for i in indices] != list(values):
            raise ConnectionError(f"{name} read-back mismatch")

    def current_units_mA(self) -> list[float]:
        return list(self._current_unit())

    def set_bus_watchdog(self, period_ms: float | None) -> None:
        """Write Bus Watchdog (RAM, lost at power-off) and read it back. None or 0 disables it."""
        count = 0 if not period_ms else round(period_ms / WATCHDOG_MS)
        if not 0 <= count <= 127:
            raise ValueError("bus watchdog must be 20..2540 ms")
        self._write(
            REGISTERS["bus_watchdog"].address, 1, [0] * len(self.ids)
        )  # clears a fired watchdog
        if count:
            self._write(REGISTERS["bus_watchdog"].address, 1, [count] * len(self.ids))
        if self.read_register("bus_watchdog") != [count] * len(self.ids):
            raise ConnectionError("bus watchdog read-back mismatch")

    def close(self) -> None:
        self.port.closePort()


def verify(
    bus: DynamixelBus,
    joints: list[str],
    expect: Mapping[str, Mapping[str, float]],
    limits: list[dict] | None = None,
) -> list[str]:
    """Compare EEPROM and model with the configuration; return human-readable mismatches.

    `expect` maps a register to per-joint values. Current registers use mA and
    `return_delay` uses microseconds; both are converted per model before comparing.
    """
    problems = []
    models = bus.read_register("model_number")
    if bus.models is not None:
        for joint, model_want, got in zip(joints, bus.models, models, strict=True):
            if model_want != got:
                problems.append(f"{joint}: model {got} != expected {model_want}")
    units = [MODELS[m].current_mA if m in MODELS else None for m in models]
    for joint, model, unit in zip(joints, models, units, strict=True):
        if unit is None:
            problems.append(f"{joint}: unknown model number {model}")
    for name, per_joint in expect.items():
        values = bus.read_register(name)
        for joint, got, unit in zip(joints, values, units, strict=True):
            if joint not in per_joint:
                continue
            want = per_joint[joint]
            if name == "current_limit" and unit is not None:
                ok, shown = abs(got * unit - want) <= unit, f"{got * unit:.0f} mA"
            elif name == "return_delay":
                ok, shown = got * 2 == want, f"{got * 2} us"
            else:
                ok, shown = got == want, str(got)
            if not ok:
                problems.append(f"{joint}: {name} {shown} != expected {want}")
    if limits is not None:
        low, high = (
            bus.read_register("min_position_limit"),
            bus.read_register("max_position_limit"),
        )
        for joint, limit, lo, hi in zip(joints, limits, low, high, strict=True):
            if not lo <= limit["min"] < limit["max"] <= hi:
                problems.append(
                    f"{joint}: software limits [{limit['min']}, {limit['max']}] outside EEPROM [{lo}, {hi}]"
                )
    return problems
