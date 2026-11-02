"""Follower contract: joint space, limits, and the bus the follower node owns exclusively."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any, ClassVar, get_args

import numpy as np

from ..control.device import (
    GroupSpec,
    JointDevice,
    build_laws,
    check_hardware,
    parse_groups,
)
from ..core.checks import finite, names, positive
from ..core.protocol import Envelope
from ..core.source import Features, Joined
from ..core.traits import WORST_CASE, SafetyTraits, Unattended
from ..drivers.base import JointBus

__all__ = ["Follower", "JointBus", "SafetyTraits", "check_limits"]


LIMIT_KEYS = ("min", "max", "max_speed", "max_jump")


def check_limits(joint_names: Sequence[str], limits: object, name: str) -> list[dict]:
    """Per-joint bounds: position range, soft speed clamp (units/s) and hard jump rejection (units)."""
    if not isinstance(limits, list) or len(limits) != len(joint_names):
        raise ValueError(f"{name}.limits needs {len(joint_names)} explicit bounds")
    for joint, limit in zip(joint_names, limits, strict=True):
        if (
            not isinstance(limit, dict)
            or limit.get("name") != joint
            or not all(finite(limit.get(k)) for k in LIMIT_KEYS)
        ):
            raise ValueError(
                f"invalid bounds for {joint}: needs name and {', '.join(LIMIT_KEYS)}"
            )
        if not (
            limit["min"] < limit["max"]
            and limit["max_speed"] > 0
            and limit["max_jump"] > 0
        ):
            raise ValueError(f"invalid bounds for {joint}")
    return limits


def check_health(cfg: object, dimension: int, name: str) -> dict:
    """Health limits: checked every `every_ticks`; FAULT before the motor firmware shuts down."""
    if cfg is None:
        return {}
    if not isinstance(cfg, dict):
        raise TypeError(f"{name}.health must be a mapping")
    out: dict[str, Any] = {
        "every_ticks": int(
            positive(cfg.get("every_ticks", 10), f"{name}.health.every_ticks")
        )
    }
    if "max_temperature_c" in cfg:
        out["max_temperature_c"] = positive(
            cfg["max_temperature_c"], f"{name}.health.max_temperature_c"
        )
    if "max_current_mA" in cfg:
        currents = cfg["max_current_mA"]
        if not isinstance(currents, list) or len(currents) != dimension:
            raise ValueError(f"{name}.health.max_current_mA needs one value per joint")
        out["max_current_mA"] = [
            positive(x, f"{name}.health.max_current_mA") for x in currents
        ]
        out["over_current_s"] = positive(
            cfg.get("over_current_s", 1.0), f"{name}.health.over_current_s"
        )
    return out


class Follower:
    """Joint-position follower. Used directly when the caller supplies the bus.

    Models subclass this with fixed joint names and unit and implement `open_bus`.
    """

    model = "external"
    # (follower_state field, unit) of the effort the robot measures, for effort estimators;
    # None when it measures none
    effort_signal: ClassVar[tuple[str, str] | None] = None
    # What it does when torque goes off and when roboloom stops commanding it
    # (core.traits). Every model declares it, as this attribute or, when it depends on
    # the configuration, as `declared_traits()`; a bus nobody described gets the worst case.
    safety_traits: ClassVar[SafetyTraits] = WORST_CASE

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if (
            "safety_traits" not in cls.__dict__
            and "declared_traits" not in cls.__dict__
        ):
            raise TypeError(
                f"{cls.__name__}: declare safety_traits (or declared_traits()): what the "
                "joints do when torque goes off and when roboloom stops commanding them "
                "(roboloom.core.traits); use 'unknown' for what is not established"
            )

    def __init__(
        self,
        name: str,
        cfg: dict,
        joint_names: Sequence[str] | None = None,
        unit: str | None = None,
    ):
        self.name, self.cfg = name, cfg
        self.joint_names = names(
            cfg.get("joints") if joint_names is None else joint_names, f"{name}.joints"
        )
        declared = unit or cfg.get("unit")
        if not isinstance(declared, str) or not declared:
            raise ValueError(
                f"{name}.unit: declare the unit of the joint positions (e.g. rad)"
            )
        self.unit = declared
        self.control_hz = positive(cfg.get("control_hz"), f"{name}.control_hz")
        self.limits = check_limits(self.joint_names, cfg.get("limits"), name)
        self.health = check_health(cfg.get("health"), len(self.joint_names), name)
        self.record_effort = bool(cfg.get("record_effort", False))
        if self.record_effort and self.effort_signal is None:
            raise ValueError(f"{name}.record_effort: {self.model} measures no effort")
        # false: never torque on; records state only (first hardware data-path check)
        self.torque = bool(cfg.get("torque", True))
        # control: per-joint law groups; without it the bus receives plain position goals
        self.control: list[GroupSpec] | None = (
            parse_groups(cfg["control"], self.joint_names, name)
            if "control" in cfg
            else None
        )
        if self.control:
            build_laws(
                self.control, self.joint_names, cfg.get("__dir__")
            )  # validate law parameters now

    def device_ids(self) -> tuple[str, ...]:
        return ()

    def declared_traits(self) -> SafetyTraits:
        """The model's safety traits for this configuration (override when they depend on it)."""
        return self.safety_traits

    def traits(self) -> SafetyTraits:
        """The declared traits, with an `unattended` the model leaves unknown filled in from
        the YAML (written by `roboloom check-hold` after measuring this unit)."""
        declared = self.declared_traits()
        measured = self.cfg.get("unattended")
        if measured is None:
            return declared
        known = [u for u in get_args(Unattended) if u != "unknown"]
        if measured not in known:
            raise ValueError(
                f"{self.name}.unattended must be one of {', '.join(known)}, not {measured!r}"
            )
        if declared.unattended != "unknown":
            raise ValueError(
                f"{self.name}.unattended: {self.model} declares "
                f"{declared.unattended!r} for this configuration; remove the key"
            )
        return replace(declared, unattended=measured)

    def open_bus(self, mock: bool) -> JointBus:
        raise RuntimeError(f"{self.name}: no bus driver; pass an opened bus instead")

    def open_device(self, mock: bool) -> JointBus:
        """The bus, wrapped in its control-law groups when `control` is configured."""
        bus = self.open_bus(mock)
        if self.control is None:
            return bus
        return JointDevice(
            bus,
            self.joint_names,
            build_laws(self.control, self.joint_names, self.cfg.get("__dir__")),
            self.name,
            self.cfg.get("bus_watchdog_ms"),
        )

    def current_limits_mA(self) -> dict[str, float]:
        """EEPROM Current Limit the node verifies, per joint (empty when the model does not declare it)."""
        return {}

    def check_hardware(self) -> None:
        if self.control:
            check_hardware(self.control, self.cfg, self.name, self.current_limits_mA())

    def safety_config(self) -> dict:
        return {
            "name": self.name,
            "limits": self.limits,
            "unit": self.unit,
            "control_hz": self.control_hz,
            "health": self.health,
            "torque": self.torque,
        }

    def features(self, dataset_fps: float) -> Features:
        return {}  # everything a follower records is joined with the other followers

    def frame(self, msg: Envelope | None, dataset_fps: float) -> dict[str, Any]:
        return {}

    def joined(self, dataset_fps: float) -> dict[str, Joined]:
        """Its part of `observation.state` (and of `observation.effort`)."""
        names = tuple(f"{self.name}.{j}" for j in self.joint_names)
        out = {"observation.state": Joined(names)}
        if self.record_effort and self.effort_signal is not None:
            out["observation.effort"] = Joined(names, unit=self.effort_signal[1])
        return out

    def joined_frame(
        self, msg: Envelope | None, dataset_fps: float
    ) -> dict[str, np.ndarray]:
        zeros = [0.0] * len(self.joint_names)
        out = {
            "observation.state": np.asarray(
                msg.payload["positions"] if msg else zeros, dtype=np.float32
            )
        }
        if self.record_effort and self.effort_signal is not None:
            effort = msg.payload.get(self.effort_signal[0]) if msg else None
            out["observation.effort"] = np.asarray(
                effort if effort is not None else zeros, dtype=np.float32
            )
        return out
