"""Operator input contracts. Inputs never talk to the follower; a controller converts them."""

from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from ..control.device import (
    GroupSpec,
    JointDevice,
    build_laws,
    check_hardware,
    parse_groups,
)
from ..control.homing import HomeSpec
from ..control.trace import Trace
from ..core.checks import names, positions, positive
from ..core.protocol import Envelope
from ..core.source import Features, Reader, Sample, Source
from ..robots.base import RobotBus


class InputDevice(Source):
    """A source that drives a controller rather than only being recorded."""

    def rate_hz(self, dataset_fps: float) -> float | None:
        poll = self.cfg.get("poll_hz")
        return None if poll is None else positive(poll, f"{self.name}.poll_hz")


class BusReader:
    """Reads a position bus as timestamped joint samples."""

    def __init__(self, bus: RobotBus):
        self.bus = bus

    def read(self) -> Sample:
        values = self.bus.read_positions()
        return Sample(np.asarray(values, dtype=np.float64), time.monotonic_ns())

    def close(self) -> None:
        self.bus.close()


class ActuatedReader:
    """Leader whose motors run control laws (e.g. gravity compensation) while it is read.

    Each read runs one control step. After `estop` or `release` the leader stays limp
    (no re-enable until the dataflow restarts) and reads keep publishing its positions.
    Any failure leaves its current-mode joints limp
    (JointDevice) and propagates; closing the reader releases every joint, so the node stops publishing and the follower's command deadline
    expires into HOLD.
    """

    def __init__(self, device: JointDevice):
        self.device = device
        self.home_goal: dict[str, float] | None = None  # leader pose of the pair's home
        self.home_spec: HomeSpec | None = None
        self.home_error = ""
        device.read_state()
        device.enable_torque()

    def set_home(self, goal: dict[str, float], spec: HomeSpec) -> None:
        """The leader pose `home` moves to (the controller maps the saved follower pose)."""
        self.home_goal, self.home_spec = goal, spec

    def read(self) -> Sample:
        state = self.device.read_state()
        if self.device.enabled:
            self.device.command(None)
        return Sample(
            np.asarray(state.positions, dtype=np.float64), time.monotonic_ns()
        )

    def on_session(self, command: str, argument: str = "") -> None:
        if command in ("estop", "release", "quit"):
            self.device.disable_torque()
        elif command == "start":
            self.device.end_home()  # the operator takes over from the held pose
        elif command == "home":
            self.home_error = ""
            if self.home_goal is None or self.home_spec is None:
                self.home_error = "no home pose configured for this leader's controller"
            elif not self.device.enabled:
                self.home_error = "leader is limp (estop or release); restart to home"
            else:
                spec = self.home_spec
                try:
                    self.device.begin_home(
                        self.home_goal, spec.max_speed, spec.tolerance, spec.pose.name
                    )
                except (RuntimeError, ValueError, ConnectionError) as exc:
                    self.home_error = str(exc)

    def start_trace(self, path: str | Path) -> None:
        """Record every control tick; written on close (see `roboloom.control.trace`)."""
        self.device.trace = Trace(path, self.device.joint_names)

    def status(self) -> dict:
        """Sent and measured current (mA) of the joints a law is pushing, for the screen."""
        state = self.device.state
        measured = (state.currents_mA if state else None) or []
        return {
            **self.device.home_status(),
            **({"home_error": self.home_error} if self.home_error else {}),
            "current_mA": {
                self.device.joint_names[i]: [
                    round(v),
                    round(measured[i]) if i < len(measured) else None,
                ]
                for i, v in sorted(self.device.last_currents.items())
                if abs(v) >= 0.5
            },
        }

    def close(self) -> None:
        try:
            self.device.disable_torque()
        finally:
            try:
                if self.device.trace is not None:
                    self.device.trace.save()
            finally:
                self.device.close()


class JointInput(InputDevice):
    """Joint-space intent, e.g. a physical leader arm. Used directly when the caller supplies readings.

    With a `control` section the leader's motors run control laws (actuated leader).
    """

    kind = "joint_intent"

    def __init__(
        self,
        name: str,
        cfg: dict,
        joint_names: Sequence[str] | None = None,
        unit: str | None = None,
    ):
        super().__init__(name, cfg)
        self.joint_names = names(
            cfg.get("joints") if joint_names is None else joint_names, f"{name}.joints"
        )
        self.unit = unit or cfg.get("unit", "dynamixel_count")
        self.rate_hz(0)
        self.control: list[GroupSpec] | None = (
            parse_groups(cfg["control"], self.joint_names, name)
            if "control" in cfg
            else None
        )
        if self.control:
            build_laws(self.control, self.joint_names, cfg.get("__dir__"))

    @property
    def actuated(self) -> bool:
        return bool(self.control) and any(g.law != "free" for g in self.control or [])

    def open_bus(self, mock: bool) -> RobotBus:
        raise RuntimeError(f"{self.name}: no bus driver; pass a reader instead")

    def current_limits_mA(self) -> dict[str, float]:
        return {}

    def check_hardware(self) -> None:
        if self.control:
            check_hardware(self.control, self.cfg, self.name, self.current_limits_mA())

    def open(self, mock: bool, dataset_fps: float) -> Reader:
        bus = self.open_bus(mock)
        if not self.actuated or self.control is None:
            return BusReader(bus)
        try:
            device = JointDevice(
                bus,
                self.joint_names,
                build_laws(self.control, self.joint_names, self.cfg.get("__dir__")),
                self.name,
                self.cfg.get("bus_watchdog_ms"),
            )
            return ActuatedReader(device)
        except BaseException:
            bus.close()
            raise

    def encode(self, sample: Sample) -> dict:
        return {
            "positions": positions(
                np.asarray(sample.value).tolist(), len(self.joint_names)
            ),
            "unit": self.unit,
        }

    def features(self, dataset_fps: float) -> Features:
        return {
            f"observation.{self.name}": {
                "dtype": "float32",
                "shape": (len(self.joint_names),),
                "names": None,
            }
        }

    def frame(self, msg: Envelope | None, dataset_fps: float) -> dict[str, Any]:
        values = msg.payload["positions"] if msg else [0] * len(self.joint_names)
        return {f"observation.{self.name}": np.asarray(values, dtype=np.float32)}
