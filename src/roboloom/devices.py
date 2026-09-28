"""Exclusive device owners. Hardware drivers import SDKs only when selected."""

from __future__ import annotations

import time
from importlib import import_module
from typing import Any

import numpy as np

from .config import MOTOR_IDS


class MockBus:
    def __init__(self, initial: float = 2048, dimension: int = 17):
        self.values = [float(initial)] * dimension
        self.enabled = False

    def read_positions(self) -> list[float]:
        return self.values.copy()

    def write_positions(self, values: list[float]) -> None:
        self.values = list(values)

    def enable_torque(self) -> None:
        self.enabled = True

    def close(self) -> None:
        self.enabled = False


class DynamixelBus:
    """Minimal Protocol 2.0 position I/O, based on robopy's Rakuda motor order.

    No EEPROM register is written. The device's operating mode and limits must
    be configured and checked during the separate hardware commissioning step.
    """

    def __init__(self, port: str, motor_ids: list[int]):
        dxl = import_module("dynamixel_sdk")

        if tuple(motor_ids) != MOTOR_IDS:
            raise ValueError("unexpected Rakuda motor IDs")
        self.dxl = dxl
        self.ids = motor_ids
        self.port = dxl.PortHandler(port)
        self.packet = dxl.PacketHandler(2.0)
        if not self.port.openPort() or not self.port.setBaudRate(1_000_000):
            raise ConnectionError(f"cannot open Dynamixel bus {port}")

    def _read(self, address: int, size: int) -> list[int]:
        group = self.dxl.GroupSyncRead(self.port, self.packet, address, size)
        for motor_id in self.ids:
            if not group.addParam(motor_id):
                raise ConnectionError(f"cannot register motor {motor_id}")
        if group.txRxPacket() != self.dxl.COMM_SUCCESS:
            raise ConnectionError("Dynamixel sync read failed")
        values = []
        for motor_id in self.ids:
            if not group.isAvailable(motor_id, address, size):
                raise ConnectionError(f"missing motor {motor_id}")
            raw = group.getData(motor_id, address, size)
            values.append(raw - 2 ** (size * 8) if raw >= 2 ** (size * 8 - 1) else raw)
        return values

    def _write(self, address: int, size: int, values: list[int]) -> None:
        group = self.dxl.GroupSyncWrite(self.port, self.packet, address, size)
        for motor_id, value in zip(self.ids, values, strict=True):
            data = list(int(value).to_bytes(size, "little", signed=True))
            if not group.addParam(motor_id, data):
                raise ConnectionError(f"cannot register motor {motor_id}")
        if group.txPacket() != self.dxl.COMM_SUCCESS:
            raise ConnectionError("Dynamixel sync write failed")

    def read_positions(self) -> list[float]:
        return [float(x) for x in self._read(132, 4)]

    def write_positions(self, values: list[float]) -> None:
        self._write(116, 4, [round(x) for x in values])

    def enable_torque(self) -> None:
        self._write(64, 1, [1] * 17)

    def close(self) -> None:
        self.port.closePort()


def open_bus(cfg: dict, mock: bool):
    return MockBus() if mock else DynamixelBus(cfg["port"], cfg["motor_ids"])


def read_camera(cfg: dict, mock: bool) -> Any:
    if mock:
        return np.zeros((cfg["height"], cfg["width"], 3), dtype=np.uint8), time.monotonic_ns()
    rs = import_module("pyrealsense2")

    pipeline = rs.pipeline()
    conf = rs.config()
    conf.enable_device(cfg["serial"])
    conf.enable_stream(rs.stream.color, cfg["width"], cfg["height"], rs.format.rgb8, cfg["fps"])
    pipeline.start(conf)
    return pipeline


def read_digit(cfg: dict, mock: bool) -> Any:
    if mock:
        return np.zeros((cfg["height"], cfg["width"], 3), dtype=np.uint8), time.monotonic_ns()
    Digit = import_module("digit_interface").Digit

    digit = Digit(serial=cfg["serial"], name=cfg.get("name", cfg["serial"]))
    digit.connect()
    digit.set_fps(cfg["fps"])
    return digit
