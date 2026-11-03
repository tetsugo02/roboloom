"""Read-only look at a Pika Sense's serial link (the jaw encoder and the clutch)."""

from __future__ import annotations

import time

from .pika_serial import PORT_HINT, PikaSerial

FEEDBACK = ("AS5047", "Command", "IMU")


def probe(port: str, *, seconds: float = 1.0) -> str:
    """Version, jaw angle, `Command` and feedback rates. Sends only `GET_INFO`; the
    tracker is checked with libsurvive's own tools (see the docs)."""
    link = PikaSerial(port)
    try:
        link.send_line("GET_INFO")
        time.sleep(seconds)
        if all(link.latest(k) is None for k in FEEDBACK):
            raise ConnectionError(
                f"Pika Sense on {port}: no feedback within {seconds:g} s; {PORT_HINT}"
            )
        counts = {k: link.count(k) for k in FEEDBACK}
        jaw = link.latest("AS5047")
        command = link.latest("Command")
        version = link.latest("Version")
        jaw_text = (
            f"{float(jaw[0]['rad']):.4f} rad"
            if jaw and isinstance(jaw[0], dict) and "rad" in jaw[0]
            else "none"
        )
        return "\n".join(
            [
                f"Pika Sense on {port}: version "
                + (str(version[0]) if version else "unknown (no reply to GET_INFO)"),
                f"jaw angle {jaw_text}, Command {command[0] if command else 'none'}",
                "feedback Hz: "
                + ", ".join(f"{k} {n / seconds:.0f}" for k, n in counts.items()),
            ]
        )
    finally:
        link.close()
