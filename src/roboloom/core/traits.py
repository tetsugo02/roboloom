"""Safety-relevant behaviour each device model declares, so prompts and choices follow it.

Two questions decide what the operator must do before roboloom lets go of a device:

- `torque_off`: what its joints do when torque goes off (release, power loss)
  - `falls`: gravity pulls the joints down; support them first
  - `lets_go`: the device stays put, but whatever it grips is released (a gripper)
  - `stays`: nothing moves
- `unattended`: what it does once roboloom stops writing to it without releasing torque
  (quit with the followers holding, a crashed process, a lost cable)
  - `holds`: it keeps its last target
  - `torque_off`: it goes limp (a bus watchdog, a driver that releases on close)
  - `unknown`: not established yet; treated like `torque_off`

Follower models must declare them (`Follower.safety_traits` or `declared_traits()`);
an unknown `unattended` may be filled in per unit by measurement (`roboloom check-hold`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, get_args

TorqueOff = Literal["falls", "stays", "lets_go"]
Unattended = Literal["holds", "torque_off", "unknown"]


@dataclass(frozen=True)
class SafetyTraits:
    torque_off: TorqueOff
    unattended: Unattended

    def __post_init__(self) -> None:
        if self.torque_off not in get_args(TorqueOff):
            raise ValueError(
                f"torque_off must be one of {', '.join(get_args(TorqueOff))}, "
                f"not {self.torque_off!r}"
            )
        if self.unattended not in get_args(Unattended):
            raise ValueError(
                f"unattended must be one of {', '.join(get_args(Unattended))}, "
                f"not {self.unattended!r}"
            )

    @property
    def holds_unattended(self) -> bool:
        return self.unattended == "holds"


# What a device nobody described is assumed to do: the worst case.
WORST_CASE = SafetyTraits(torque_off="falls", unattended="unknown")


def precautions(devices: Mapping[str, SafetyTraits]) -> str:
    """What the operator must do before `devices` lose torque, as one sentence; "" when
    nothing has to be done (every device stays put)."""
    falls = [n for n, t in devices.items() if t.torque_off == "falls"]
    lets_go = [n for n, t in devices.items() if t.torque_off == "lets_go"]
    parts = []
    if falls:
        parts.append(f"support {', '.join(falls)} (falls without torque)")
    if lets_go:
        parts.append(
            f"take any object out of {', '.join(lets_go)} (lets go without torque)"
        )
    return "; ".join(parts)


def unattended_note(devices: Mapping[str, SafetyTraits]) -> str:
    """Which of `devices` go (or may go) limp once roboloom stops commanding them."""
    limp = [n for n, t in devices.items() if t.unattended == "torque_off"]
    unknown = [n for n, t in devices.items() if t.unattended == "unknown"]
    parts = []
    if limp:
        parts.append(f"{', '.join(limp)} goes limp")
    if unknown:
        parts.append(
            f"{', '.join(unknown)} may go limp (not measured: roboloom check-hold)"
        )
    return "; ".join(parts)


def ending_note(devices: Mapping[str, SafetyTraits]) -> str:
    """What happens to `devices` (all left without commands) and what the operator does
    about it: "leader goes limp: support leader (falls without torque)"."""
    note, todo = unattended_note(devices), precautions(devices)
    return f"{note}: {todo}" if note and todo else note or todo
