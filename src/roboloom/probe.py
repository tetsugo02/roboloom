"""Read-only Dynamixel bus inspection: identify a port and gather values for the node YAML."""

from __future__ import annotations

import time

from .drivers.dynamixel_table import MODELS, REGISTERS

SHOWN = (
    "model_number",
    "operating_mode",
    "drive_mode",
    "homing_offset",
    "current_limit",
    "return_delay",
    "shutdown",
    "min_position_limit",
    "max_position_limit",
    "torque_enable",
    "bus_watchdog",
    "hardware_error",
    "present_temperature",
    "present_position",
)


def probe(
    port: str,
    ids: list[int] | None = None,
    baudrate: int = 1_000_000,
    repeats: int = 50,
) -> str:
    """Ping IDs (all 0..252 if none given), read registers, and time the state sync read. Never writes."""
    import dynamixel_sdk as dxl

    from .drivers.dynamixel import DynamixelBus, latency_timer_ms

    handler = dxl.PortHandler(port)
    packet = dxl.PacketHandler(2.0)
    if not handler.openPort() or not handler.setBaudRate(baudrate):
        raise ConnectionError(f"cannot open {port}")
    try:
        if ids is None:
            found, result = packet.broadcastPing(handler)
            if result != dxl.COMM_SUCCESS:
                raise ConnectionError(
                    f"broadcast ping failed: {packet.getTxRxResult(result)}"
                )
            ids = sorted(found)
    finally:
        handler.closePort()
    if not ids:
        return f"{port}: no motors answered"
    bus = DynamixelBus(port, ids, baudrate=baudrate)
    try:
        table = {name: bus.read_register(name) for name in SHOWN}
        start = time.perf_counter()
        for _ in range(repeats):
            bus.read_state()
        read_ms = (time.perf_counter() - start) / repeats * 1e3
    finally:
        bus.close()
    lines = [
        f"{port}: {len(ids)} motors, latency_timer {latency_timer_ms(port)} ms, state read {read_ms:.2f} ms"
    ]
    lines.append("id  model        " + " ".join(f"{n[:12]:>12}" for n in SHOWN[1:]))
    for i, motor_id in enumerate(ids):
        model = MODELS.get(table["model_number"][i])
        cells = []
        for name in SHOWN[1:]:
            value = table[name][i]
            if name == "current_limit" and model:
                cells.append(f"{value * model.current_mA:>10.0f}mA")
            elif name == "return_delay":
                cells.append(f"{value * 2:>10}us")
            else:
                cells.append(f"{value:>12}")
        lines.append(
            f"{motor_id:<3} {model.name if model else table['model_number'][i]!s:<12} "
            + " ".join(cells)
        )
    assert set(SHOWN) <= set(REGISTERS)
    return "\n".join(lines)
