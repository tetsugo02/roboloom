"""Python interface for collection and one-step policy inference.

Device buses and sensors are injected; importing this module never opens hardware.
The dora runner uses the same controller, safety and recorder components.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Self

import numpy as np

from .config import load_experiment
from .control import FollowerSafety, JointController, positions
from .devices import open_bus
from .protocol import Publisher, pack_array
from .recording import EpisodeRecorder


class RobotBus(Protocol):
    def read_positions(self) -> list[float]: ...
    def write_positions(self, values: list[float]) -> None: ...
    def enable_torque(self) -> None: ...
    def close(self) -> None: ...


@dataclass
class Sample:
    value: np.ndarray
    capture_ns: int


class Experiment:
    """Collect with a controller or run a policy using the same checked robot bus.

    `controller` takes the current observation dict and returns a target vector or
    None. `sensors` maps source names to callables returning Sample or None.
    For Rakuda YAML, `from_yaml` supplies the leader mapping by default.
    """

    def __init__(self, cfg: dict, robot: RobotBus, controller: Callable[[dict], list[float] | None] | None = None, sensors: dict[str, Callable[[], Sample | None]] | None = None, dataset=None):
        self.cfg = cfg
        self.robot = FollowerSafety({**cfg["nodes"]["robot"], "robot_id": cfg["experiment"]["robot_id"]}, robot)
        self.robot.start()
        self.controller = controller
        self.sensors = sensors or {}
        self.recorder = EpisodeRecorder(cfg, dataset)
        self.publisher = Publisher("python-controller")
        self.sources = {name: Publisher(name) for name in self.recorder.sources}
        self.period_s = 1 / cfg["nodes"]["robot"]["control_hz"]
        self.deadline_ms = cfg["nodes"].get("controller", {}).get("command_deadline_ms", 100)
        self.seq = 0
        self.last_metrics: dict | None = None
        self._extra_closers: list[Callable[[], None]] = []

    @classmethod
    def from_yaml(cls, path: str | Path, *, hardware: bool = False, sensors: dict[str, Callable[[], Sample | None]] | None = None, dataset=None) -> Experiment:
        cfg = load_experiment(path)
        mock = cfg["experiment"]["mode"] == "mock"
        if not mock and not hardware:
            raise ValueError("hardware=True is required to open real devices")
        bus = open_bus(cfg["nodes"]["robot"], mock)
        leader = open_bus(cfg["nodes"]["leader"], mock)
        mapper = JointController({**cfg["nodes"]["controller"], "robot_id": cfg["experiment"]["robot_id"]})
        source = Publisher("leader")

        def leader_sensor() -> Sample:
            data = leader.read_positions()
            return Sample(np.asarray(data, dtype=np.float32), time.monotonic_ns())

        defaults: dict[str, Callable[[], Sample | None]] = {}
        if mock:
            def mock_image(shape: tuple[int, int, int]) -> Callable[[], Sample]:
                def read() -> Sample:
                    return Sample(np.zeros(shape, np.uint8), time.monotonic_ns())

                return read

            for name in ("camera", "digit_left", "digit_right"):
                shape = (cfg["nodes"][name]["height"], cfg["nodes"][name]["width"], 3)
                defaults[name] = mock_image(shape)
            size = int(cfg["nodes"]["audio"]["sample_rate"] / cfg["experiment"]["dataset_fps"])
            def mock_audio() -> Sample:
                return Sample(np.zeros(size, np.int16), time.monotonic_ns())

            defaults["audio"] = mock_audio

        try:
            instance = cls(cfg, bus, sensors={"leader": leader_sensor, **defaults, **(sensors or {})}, dataset=dataset)
        except Exception:
            leader.close()
            bus.close()
            raise
        instance._extra_closers.append(leader.close)

        def controller(obs: dict) -> list[float] | None:
            sample = obs.get("leader")
            if sample is None:
                return None
            msg = source.make("leader", {"positions": sample.value.tolist()}, sample.capture_ns)
            command = mapper.update(msg, obs["state"])
            return command.payload["positions"] if command else None

        instance.controller = controller
        return instance

    @classmethod
    def from_components(
        cls, *, robot_id: str, robot: RobotBus, joint_names: list[str], limits: list[dict],
        controller: Callable[[dict], list[float] | None] | None = None,
        sensors: dict[str, Callable[[], Sample | None]] | None = None,
        image_shapes: dict[str, tuple[int, int, int]] | None = None,
        audio_sample_rate: int | None = None, fps: int = 10, control_hz: int = 30,
        output: str | Path = "dataset", repo_id: str = "local/experiment", unit: str = "dynamixel_count",
        dataset=None,
    ) -> Experiment:
        if len(joint_names) != len(limits) or len(set(joint_names)) != len(joint_names) or not joint_names:
            raise ValueError("joint_names and limits must match")
        for name, bound in zip(joint_names, limits, strict=True):
            if bound.get("name") != name or not all(isinstance(bound.get(k), (int, float)) and math.isfinite(bound[k]) for k in ("min", "max", "max_step")) or not bound["min"] < bound["max"] or bound["max_step"] <= 0:
                raise ValueError(f"invalid limits for {name}")
        if control_hz < fps:
            raise ValueError("control_hz must be >= fps")
        nodes: dict[str, dict[str, Any]] = {"robot": {"limits": limits, "control_hz": control_hz, "unit": unit}, "controller": {"command_deadline_ms": 100}}
        for name, shape in (image_shapes or {}).items():
            if name in ("robot", "action", "audio") or len(shape) != 3 or shape[2] != 3:
                raise ValueError("image sensor requires HWC RGB shape")
            nodes[name] = {"type": "image", "height": shape[0], "width": shape[1]}
        if audio_sample_rate is not None:
            nodes["audio"] = {"type": "pcm_mono", "sample_rate": audio_sample_rate}
        if "leader" in (sensors or {}):
            nodes["leader"] = {"type": "joint"}
        nodes["recorder"] = {"max_age_ms": {name: 300 for name in nodes if name == "robot" or name == "leader" or nodes[name].get("type") in ("image", "pcm_mono")}}
        cfg = {"experiment": {"robot_id": robot_id, "repo_id": repo_id, "output": str(output), "dataset_fps": fps}, "nodes": nodes}
        return cls(cfg, robot, controller=controller, sensors=sensors, dataset=dataset)

    def start_episode(self, task: str) -> None:
        self.recorder.start(task)
        self.robot.arm()

    def start_inference(self) -> None:
        """Arm checked one-step control without creating an episode."""
        self.robot.arm()

    def stop_inference(self) -> None:
        self.robot.stop()

    def step(self, *, policy: Callable[[dict], list[float] | None] | None = None) -> dict:
        """One checked control tick; policy overrides the configured controller."""
        now = time.monotonic_ns()
        try:
            state = positions(self.robot.bus.read_positions(), len(self.robot.cfg["limits"]))
        except Exception:
            self.robot.stop()
            raise
        obs: dict[str, Any] = {"state": state}
        self.recorder.ingest(self.sources["robot"].make("robot", {"positions": state, "mode": self.robot.mode}, now))
        for name, reader in self.sensors.items():
            try:
                sample = reader()
            except Exception:
                self.robot.stop()
                raise
            obs[name] = sample
            if sample is None or name not in self.sources:
                continue
            value = np.asarray(sample.value)
            if name == "leader":
                payload: dict[str, Any] = {"positions": positions(value.tolist(), len(state))}
            elif name == "audio":
                payload = {"pcm": pack_array(value)}
            else:
                payload = {"image": pack_array(value)}
            self.recorder.ingest(self.sources[name].make(name, payload, sample.capture_ns))
        callback = policy if policy is not None else self.controller
        try:
            target = callback(obs) if callback else None
        except Exception:
            self.robot.stop()
            raise
        if target is not None:
            target = positions(target, len(state))
            command = self.publisher.make("command", {"robot_id": self.cfg["experiment"]["robot_id"], "unit": self.robot.cfg.get("unit", "dynamixel_count"), "positions": target, "deadline_ns": now + int(self.deadline_ms * 1e6)}, now)
            self.robot.accept(command)
        state_msg, action_msg = self.robot.tick()
        self.recorder.ingest(state_msg)
        self.recorder.ingest(action_msg)
        return {"observation": obs, "action": action_msg.payload, "mode": state_msg.payload["mode"]}

    def run(self, seconds: float, *, policy: Callable[[dict], list[float] | None] | None = None) -> list[dict]:
        results = []
        end = time.monotonic() + seconds
        next_tick = time.monotonic()
        while time.monotonic() < end:
            results.append(self.step(policy=policy))
            next_tick += self.period_s
            time.sleep(max(0, next_tick - time.monotonic()))
        return results

    def stop_episode(self) -> None:
        self.robot.stop()
        self.recorder.stop()

    def save_episode(self) -> int:
        self.last_metrics = self.recorder.metrics()
        return self.recorder.save()

    def discard_episode(self) -> None:
        self.robot.stop()
        self.recorder.discard()

    def estop(self) -> None:
        self.robot.stop(estop=True)

    def close(self) -> None:
        try:
            self.recorder.close()
        finally:
            self.robot.bus.close()
            for closer in self._extra_closers:
                closer()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_):
        self.close()
