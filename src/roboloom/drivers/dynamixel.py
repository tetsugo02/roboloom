"""Dynamixel Protocol 2.0 position bus."""

from __future__ import annotations

import dynamixel_sdk as dxl


class DynamixelBus:
    """Minimal sync position I/O in the given motor order.

    No EEPROM register is written. The device's operating mode and limits must
    be configured and checked during the separate hardware commissioning step.
    """

    def __init__(self, port: str, motor_ids: list[int], baudrate: int = 1_000_000):
        self.ids = motor_ids
        self.port = dxl.PortHandler(port)
        self.packet = dxl.PacketHandler(2.0)
        if not self.port.openPort() or not self.port.setBaudRate(baudrate):
            raise ConnectionError(f"cannot open Dynamixel bus {port}")

    def _read(self, address: int, size: int) -> list[int]:
        group = dxl.GroupSyncRead(self.port, self.packet, address, size)
        for motor_id in self.ids:
            if not group.addParam(motor_id):
                raise ConnectionError(f"cannot register motor {motor_id}")
        if group.txRxPacket() != dxl.COMM_SUCCESS:
            raise ConnectionError("Dynamixel sync read failed")
        values = []
        for motor_id in self.ids:
            if not group.isAvailable(motor_id, address, size):
                raise ConnectionError(f"missing motor {motor_id}")
            raw = group.getData(motor_id, address, size)
            values.append(raw - 2 ** (size * 8) if raw >= 2 ** (size * 8 - 1) else raw)
        return values

    def _write(self, address: int, size: int, values: list[int]) -> None:
        group = dxl.GroupSyncWrite(self.port, self.packet, address, size)
        for motor_id, value in zip(self.ids, values, strict=True):
            data = list(int(value).to_bytes(size, "little", signed=True))
            if not group.addParam(motor_id, data):
                raise ConnectionError(f"cannot register motor {motor_id}")
        if group.txPacket() != dxl.COMM_SUCCESS:
            raise ConnectionError("Dynamixel sync write failed")

    def read_positions(self) -> list[float]:
        return [float(x) for x in self._read(132, 4)]

    def write_positions(self, values: list[float]) -> None:
        self._write(116, 4, [round(x) for x in values])

    def enable_torque(self) -> None:
        self._write(64, 1, [1] * len(self.ids))

    def close(self) -> None:
        self.port.closePort()
