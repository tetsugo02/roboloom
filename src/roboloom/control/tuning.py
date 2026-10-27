"""Interactive gravity-compensation tuning, independent of the terminal (see `ui/tune.py`).

One gravity_comp group runs live while the operator changes, joint by joint, how much
of the weight is removed (`gain`, a multiple of the identified g(q)) and how hard a push
must be before the joint moves (`hold_mA`). Values apply at once and are saved to the
group's tuning file (`tuning:` in the node YAML).
"""

from __future__ import annotations

import time
from copy import deepcopy
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


@dataclass(frozen=True)
class TuningSave:
    """Detached values for file I/O on a separate thread."""

    path: Path
    header: str
    data: dict
    revision: int

    def write(self) -> Path:
        text = self.header + yaml.safe_dump(
            self.data,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=None,
            width=1000,
        )
        # Replace atomically so a failed write cannot truncate the tuning file.
        import os
        import tempfile

        fd, name = tempfile.mkstemp(prefix=self.path.name, dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(text)
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)
        return self.path


class TuningSession:
    def __init__(
        self,
        device: JointDevice,
        law: GravityComp,
        path: str | Path,
        motor_ids: dict[str, int] | None = None,
        period_s: float = 1 / 60,
    ):
        self.device, self.law, self.path = device, law, Path(path).resolve()
        self.period_s = period_s  # the leader's control period (its poll_hz)
        self.names = [device.joint_names[i] for i in law.joints]
        text = self.path.read_text()
        self._header = "".join(text.splitlines(keepends=True)[: _comment_lines(text)])
        data = yaml.safe_load(text) or {}
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
        self.revision = 0
        self.estopped = False
        self.stopped: str | None = None

    # -- running ----------------------------------------------------------------

    def start(self) -> None:
        if self.estopped:
            raise RuntimeError("ESTOP: restart tune-gravity to re-enable torque")
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

    def close(self) -> None:
        """Torque off and close the bus (unsaved changes are dropped)."""
        try:
            self.device.disable_torque()
        finally:
            self.device.close()

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
            self.revision += 1
            self._apply()
            return f"{name}: gain {self.gain[k]:.1f}"
        elif key in ("=", "-"):
            step = HOLD_STEP if key == "=" else -HOLD_STEP
            self.law.hold[k] = min(MAX_HOLD, max(0.0, self.law.hold[k] + step))
            self.dirty = True
            self.revision += 1
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

    def emergency(self) -> None:
        """Permanent latch, distinct from a recoverable safety STOPPED state."""
        self.estopped = True
        self.stopped = "ESTOP: restart required"
        self.device.disable_torque()

    def save_snapshot(self) -> TuningSave:
        data = deepcopy(self.data)
        joints = dict(data.get("joints") or {})
        for k, joint in enumerate(self.names):
            entry = dict(joints.get(joint) or {})
            entry["gain"] = round(float(self.gain[k]), 2)
            entry["hold_mA"] = round(float(self.law.hold[k]), 1)
            joints[joint] = entry
        data.update(hold_kp=self.law.hold_kp, joints=joints)
        return TuningSave(self.path, self._header, data, self.revision)

    def mark_saved(self, saved: TuningSave) -> None:
        """Changes made during a write must remain dirty."""
        self.data = deepcopy(saved.data)
        self.dirty = self.revision != saved.revision

    def save(self) -> Path:
        """Synchronous API; the operator backend uses detached snapshots instead."""
        saved = self.save_snapshot()
        path = saved.write()
        self.mark_saved(saved)
        return path


def _comment_lines(text: str) -> int:
    count = 0
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        count += 1
    return count
