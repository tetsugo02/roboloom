"""Python interface for collection and one-step policy inference.

Device buses and sensors are injected; importing this module never opens hardware.
The dora runner uses the same controller, safety and recorder components.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Self

from .config import ExperimentConfig, load_experiment
from .core.checks import positions
from .core.protocol import Publisher
from .core.source import Reader, Sample, Source
from .inputs.base import InputDevice, JointInput
from .recording import ACTION, EpisodeRecorder
from .robots.base import Robot, RobotBus
from .robots.safety import FollowerSafety, make_command
from .sensors.audio.base import PcmAudio
from .sensors.vision.base import ImageSensor


class Experiment:
    """Collect with a controller or run a policy using the same checked robot bus.

    `controller` takes the current observation dict and returns a target vector or
    None. `sensors` maps source names to callables returning Sample or None.
    For YAML experiments, `from_yaml` supplies the configured controller by default.
    """

    def __init__(self, cfg: ExperimentConfig, robot: RobotBus, controller: Callable[[dict], list[float] | None] | None = None, sensors: dict[str, Callable[[], Sample | None]] | None = None, dataset=None):
        self.cfg = cfg
        self.spec = cfg.robot
        self.robot = FollowerSafety(self.spec.safety_config(cfg.robot_id), robot)
        self.robot.start()
        self.controller = controller
        self.sensors = sensors or {}
        self.recorder = EpisodeRecorder(cfg, dataset)
        self.publisher = Publisher("python-controller")
        self.specs: dict[str, InputDevice | Source] = {**cfg.inputs, **cfg.sensors}
        self.publishers = {name: Publisher(name) for name in cfg.sources}
        self.period_s = 1 / self.spec.control_hz
        self.deadline_ms = cfg.controller_for(self.spec.name).deadline_ms if cfg.controllers else 100
        self.last_metrics: dict | None = None
        self._extra_closers: list[Callable[[], None]] = []

    @classmethod
    def from_yaml(cls, path: str | Path, *, hardware: bool = False, sensors: dict[str, Callable[[], Sample | None]] | None = None, dataset=None) -> Experiment:
        cfg = load_experiment(path)
        if not cfg.mock and not hardware:
            raise ValueError("hardware=True is required to open real devices")
        mapper = cfg.controller_for(cfg.robot.name)
        source = mapper.source
        bus = cfg.robot.open_bus(cfg.mock)
        readers: dict[str, Reader] = {}
        try:
            readers[source.name] = source.open(cfg.mock, cfg.dataset_fps)
            if cfg.mock:
                for name, sensor in cfg.sensors.items():
                    readers[name] = sensor.open(True, cfg.dataset_fps)
            defaults = {name: reader.read for name, reader in readers.items()}
            instance = cls(cfg, bus, sensors={**defaults, **(sensors or {})}, dataset=dataset)
        except Exception:
            for reader in readers.values():
                reader.close()
            bus.close()
            raise
        instance._extra_closers.extend(reader.close for reader in readers.values())
        publisher = Publisher(source.name)

        def controller(obs: dict) -> list[float] | None:
            sample = obs.get(source.name)
            if sample is None:
                return None
            msg = publisher.make(source.kind, source.encode(sample), sample.capture_ns)
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
        if control_hz < fps:
            raise ValueError("control_hz must be >= fps")
        spec = Robot("robot", {"limits": limits, "control_hz": control_hz}, joint_names, unit)
        inputs: dict[str, InputDevice] = {}
        if "leader" in (sensors or {}):
            inputs["leader"] = JointInput("leader", {}, joint_names, unit)
        streams: dict[str, Source] = {}
        for name, shape in (image_shapes or {}).items():
            if name in ("robot", "leader", ACTION, "audio") or len(shape) != 3 or shape[2] != 3:
                raise ValueError("image sensor requires HWC RGB shape")
            streams[name] = ImageSensor(name, {"height": shape[0], "width": shape[1]})
        if audio_sample_rate is not None:
            streams["audio"] = PcmAudio("audio", {"sample_rate": audio_sample_rate})
        cfg = ExperimentConfig(
            robot_id=robot_id, repo_id=repo_id, output=str(output), dataset_fps=fps,
            robots={"robot": spec}, inputs=inputs, sensors=streams,
            max_age_ms={name: 300 for name in (*inputs, "robot", *streams)},
        )
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
            state = positions(self.robot.bus.read_positions(), len(self.spec.joint_names))
        except Exception:
            self.robot.stop()
            raise
        obs: dict[str, Any] = {"state": state}
        robot = self.spec.name
        self.recorder.ingest(robot, self.publishers[robot].make("robot_state", {"positions": state, "mode": self.robot.mode}, now))
        for name, reader in self.sensors.items():
            try:
                sample = reader()
            except Exception:
                self.robot.stop()
                raise
            obs[name] = sample
            spec = self.specs.get(name)
            if sample is None or spec is None:
                continue
            self.recorder.ingest(name, self.publishers[name].make(spec.kind, spec.encode(sample), sample.capture_ns))
        callback = policy if policy is not None else self.controller
        try:
            target = callback(obs) if callback else None
        except Exception:
            self.robot.stop()
            raise
        if target is not None:
            target = positions(target, len(state))
            command = make_command(self.publisher, robot_id=self.cfg.robot_id, unit=self.spec.unit, target=target, now_ns=now, deadline_ms=self.deadline_ms)
            self.robot.accept(command)
        state_msg, action_msg = self.robot.tick()
        self.recorder.ingest(robot, state_msg)
        self.recorder.ingest(ACTION, action_msg)
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
