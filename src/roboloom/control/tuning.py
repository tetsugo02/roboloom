"""Interactive gravity-compensation tuning, independent of the terminal (see `ui/tune.py`).

One gravity_comp group runs live while the operator changes, joint by joint, how much
of the weight is removed (`gain`, a multiple of the identified g(q)) and how hard a push
must be before the joint moves (`hold_mA`). Values apply at once and are saved to the
group's tuning file (`tuning:` in the node YAML).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from .device import JointDevice
from .laws import GravityComp

GAIN_STEP, HOLD_STEP = 0.1, 5.0
MAX_GAIN, MAX_HOLD = 3.0, 100.0


@dataclass
class JointRow:
    joint: str
    motor_id: int | None
    gain: float
    hold_mA: float
    model_mA: float | None  # g(q) at gain 1
    sent_mA: float | None
    measured_mA: float | None
    position: float | None
    velocity: float | None
    state: str  # off / free / holding / sliding / gravity
    hint: str


class TuningSession:
    def __init__(
        self,
        device: JointDevice,
        law: GravityComp,
        path: str | Path,
        motor_ids: dict[str, int] | None = None,
    ):
        self.device, self.law, self.path = device, law, Path(path).resolve()
        self.names = [device.joint_names[i] for i in law.joints]
        data = yaml.safe_load(self.path.read_text()) or {}
        self.data = data
        self.hints = {
            j: str((data.get("joints") or {}).get(j, {}).get("hint", ""))
            for j in self.names
        }
        self.motor_ids = motor_ids or {}
        self.gain = list(law.gain)  # the operator's values; law.gain is what runs
        self.selected = 0
        self.off: set[int] = set()
        self.dirty = False
        self.stopped: str | None = None

    # -- running ----------------------------------------------------------------

    def start(self) -> None:
        self.device.read_state()
        self.device.enable_torque()
        self.stopped = None

    def step(self, now_ns: int | None = None) -> None:
        now = time.monotonic_ns() if now_ns is None else now_ns
        self.device.read_state()  # keeps the view live while stopped, too
        if self.stopped is not None:
            return
        try:
            self.device.command(None, now)
        except RuntimeError as exc:  # runaway or watchdog: the device is already limp
            self.stopped = str(exc)

    def _apply(self) -> None:
        self.law.gain = [0.0 if k in self.off else g for k, g in enumerate(self.gain)]

    # -- keys -------------------------------------------------------------------

    def key(self, key: str) -> str | None:
        """Apply one key; returns a message for the operator, if any."""
        k = self.selected
        name = self.names[k]
        if key in ("down", "j"):
            self.selected = (k + 1) % len(self.names)
        elif key in ("up", "k"):
            self.selected = (k - 1) % len(self.names)
        elif key in ("]", "["):
            step = GAIN_STEP if key == "]" else -GAIN_STEP
            self.gain[k] = round(min(MAX_GAIN, max(0.0, self.gain[k] + step)), 2)
            self.dirty = True
            self._apply()
            return f"{name}: gain {self.gain[k]:.1f}"
        elif key in ("=", "-"):
            step = HOLD_STEP if key == "=" else -HOLD_STEP
            self.law.hold[k] = min(MAX_HOLD, max(0.0, self.law.hold[k] + step))
            self.dirty = True
            return f"{name}: hold {self.law.hold[k]:.0f} mA"
        elif key == "0":
            self.off ^= {k}
            self._apply()
            return f"{name}: gravity compensation {'OFF (compare)' if k in self.off else 'on'}"
        elif key == "r":
            if self.stopped is None:
                return "running"
            self.start()
            return "re-enabled; the current ramps in again"
        elif key == "s":
            return f"saved {self.save()}"
        return None

    # -- view -------------------------------------------------------------------

    def rows(self) -> list[JointRow]:
        state = self.device.state
        out = []
        for k, i in enumerate(self.law.joints):
            hold, gain = self.law.hold[k], self.gain[k]
            q = state.positions[i] if state else None
            if k in self.off:
                mode = "off"
            elif hold > 0 and q is not None and i in self.law.anchor:
                slack = abs(self.law.anchor[i] - q) * self.law.hold_kp
                mode = "sliding" if slack >= hold - 0.5 else "holding"
            elif gain > 0:
                mode = "gravity"
            else:
                mode = "free"
            out.append(
                JointRow(
                    self.names[k],
                    self.motor_ids.get(self.names[k]),
                    gain,
                    hold,
                    self.law.model_mA.get(i),
                    self.device.last_currents.get(i),
                    state.currents_mA[i] if state and state.currents_mA else None,
                    q,
                    state.velocities[i] if state and state.velocities else None,
                    mode,
                    self.hints[self.names[k]],
                )
            )
        return out

    # -- file -------------------------------------------------------------------

    def save(self) -> Path:
        """Write gain and hold per joint; the file's leading comment block is kept."""
        text = self.path.read_text() if self.path.exists() else ""
        header = "".join(
            line for line in text.splitlines(keepends=True)[: _comment_lines(text)]
        )
        joints = dict(self.data.get("joints") or {})
        for k, j in enumerate(self.names):
            entry = dict(joints.get(j) or {})
            entry["gain"] = round(float(self.gain[k]), 2)
            entry["hold_mA"] = round(float(self.law.hold[k]), 1)
            joints[j] = entry
        self.data = {**self.data, "hold_kp": self.law.hold_kp, "joints": joints}
        self.path.write_text(
            header
            + yaml.safe_dump(
                self.data,
                sort_keys=False,
                allow_unicode=True,
                default_flow_style=None,
                width=1000,
            )
        )
        self.dirty = False
        return self.path


def _comment_lines(text: str) -> int:
    count = 0
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        count += 1
    return count
