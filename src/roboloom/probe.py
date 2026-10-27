"""Read-only Dynamixel bus inspection: identify a port and gather values for the node YAML."""

from __future__ import annotations

import time

from .drivers.dynamixel_table import MODELS, REGISTERS

SHOWN = (
    "model_number",
    "firmware_version",
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
    """Ping IDs (all 0..252 if none given), read registers, and time the state read (plain and
    Fast Sync Read) and the Bus Watchdog read. Never writes."""
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
            ids = sorted(found) if found is not None else []
    finally:
        handler.closePort()
    if not ids:
        return f"{port}: no motors answered"
    bus = DynamixelBus(port, ids, baudrate=baudrate)

    def timed(read) -> float:
        start = time.perf_counter()
        for _ in range(repeats):
            read()
        return (time.perf_counter() - start) / repeats * 1e3

    try:
        table = {name: bus.read_register(name) for name in SHOWN}
        read_ms = timed(bus.read_state)
        fast = bus.use_fast_read()
        fast_ms = timed(bus.read_state) if fast else None
        watchdog_ms = timed(lambda: bus.read_register("bus_watchdog"))
        note = bus.read_note
    finally:
        bus.close()
    tick_ms = (fast_ms or read_ms) + 1.0  # + about 1 ms of goal writes
    fast_text = f"{fast_ms:.2f} ms" if fast_ms is not None else f"unavailable: {note}"
    firmware = sorted(set(table["firmware_version"]))
    lines = [
        f"{port}: {len(ids)} motors, latency_timer {latency_timer_ms(port)} ms, firmware {firmware}",
        (
            f"state read {read_ms:.2f} ms, fast sync read {fast_text}, "
            f"bus_watchdog read {watchdog_ms:.2f} ms ({note})"
        ),
        (
            f"rough control-rate limit: {700 / tick_ms:.0f} Hz (70% of the period for one "
            "state read + goal writes); check work_ms on the run screen"
        ),
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
