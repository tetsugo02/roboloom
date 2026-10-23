"""Swappable per-joint control laws between a safety layer and a bus.

A device's joints are split into groups; each group runs one law, and each law
needs one motor operating mode. The same laws serve followers and actuated
leaders, so bilateral control can be added as another law.
"""

LAWS = {
    "free": "roboloom.control.laws:Free",
    "position": "roboloom.control.laws:Position",
    "current_position": "roboloom.control.laws:CurrentPosition",
    "spring": "roboloom.control.laws:Spring",
    "gravity_comp": "roboloom.control.laws:GravityComp",
    "impedance": "roboloom.control.laws:Impedance",
}
