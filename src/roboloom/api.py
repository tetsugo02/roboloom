"""In-process collection and one-step policy inference, for tests and simple robots.

Everything runs in the caller's process and thread, so a slow policy or sensor delays the
control loop. For a real robot use `roboloom.Session`, which runs the robot's dora
dataflow (control loops, sensors and recorder in their own processes).
Device buses and sensors are injected; importing this module never opens hardware.
The dora runner uses the same controller, safety and recorder components.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Self

from .config import RobotConfig, load_config
from .controllers.base import FollowerView
from .core.checks import positions
from .core.protocol import Publisher
from .core.source import Reader, Sample, Source
from .errors import ConfigError
from .inputs.base import InputDevice, JointInput
from .recording import ACTION, EpisodeRecorder, action_stream
from .robots.base import Follower, JointBus
from .robots.safety import FollowerSafety, make_command
from .sensors.audio.base import PcmAudio
from .sensors.vision.base import ImageSensor


class InProcessSession:
    """Collect with a controller or run a policy using the same checked robot bus.

    `controller` takes the current observation dict and returns a target vector or
    None. `sensors` maps source names to callables returning Sample or None.
    For YAML configurations, `from_yaml` supplies the configured controller by default.
    """

    def __init__(
        self,
        cfg: RobotConfig,
        bus: JointBus,
        controller: Callable[[dict], list[float] | None] | None = None,
        sensors: dict[str, Callable[[], Sample | None]] | None = None,
        dataset=None,
    ):
        if len(cfg.followers) != 1:
            raise ConfigError(
                f"{cfg.path}: InProcessSession drives one follower; this configuration "
                f"has {len(cfg.followers)} ({', '.join(cfg.followers)}). Use "
                "roboloom.Session, which runs the dataflow"
            )
        self.cfg = cfg
        (self.spec,) = cfg.followers.values()
        self.safety = FollowerSafety(self.spec.safety_config(), bus)
        self.safety.start()
        self.controller = controller
        self.sensors = sensors or {}
        self.recorder = EpisodeRecorder(cfg, dataset, **cfg.recorder)
        self.publisher = Publisher("python-controller")
        self.specs: dict[str, InputDevice | Source] = {**cfg.inputs, **cfg.sensors}
        self.publishers = {name: Publisher(name) for name in cfg.sources}
        self.period_s = 1 / self.spec.control_hz
        self.deadline_ms = (
            cfg.controller_for(self.spec.name).deadline_ms if cfg.controllers else 100
        )
        self.last_metrics: dict | None = None
        self._extra_closers: list[Callable[[], None]] = []

    @classmethod
    def from_yaml(
        cls,
        path: str | Path,
        *,
        options: Iterable[str] | None = None,
        mock: bool | None = None,
        sensors: dict[str, Callable[[], Sample | None]] | None = None,
        dataset=None,
    ) -> InProcessSession:
        """`options`: launch options to enable (None: their defaults); `mock`: override
        the YAML's `mode` (None: as written, default hardware)."""
        cfg = load_config(path, options=options, mock=mock)
        if len(cfg.followers) != 1:
            raise ConfigError(
                f"{path}: InProcessSession drives one follower; use roboloom.Session"
            )
        (follower,) = cfg.followers.values()
        mapper = cfg.controller_for(follower.name)
        source = mapper.source
        if source is None:
            raise ConfigError(
                f"{mapper.name}: policy controllers run in the dora dataflow; "
                "use roboloom.Session (or pass a policy to step())"
            )
        if getattr(source, "actuated", False):
            raise ConfigError(
                f"{source.name}: a leader whose motors run control laws needs its own "
                "process; use roboloom.Session, which runs the dataflow"
            )
        bus = follower.open_device(cfg.mock)
        readers: dict[str, Reader] = {}
        try:
            readers[source.name] = source.open(cfg.mock, cfg.dataset_fps)
            if cfg.mock:
                for name, sensor in cfg.sensors.items():
                    readers[name] = sensor.open(True, cfg.dataset_fps)
            defaults = {name: reader.read for name, reader in readers.items()}
            instance = cls(
                cfg, bus, sensors={**defaults, **(sensors or {})}, dataset=dataset
            )
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
            view = FollowerView(list(obs["state"]), None, None, "", msg.t_ready_ns)
            command = mapper.update(msg, {follower.name: view}).get(follower.name)
            return command.payload["positions"] if command else None

        instance.controller = controller
        return instance

    @classmethod
    def from_components(
        cls,
        *,
        robot: str,
        bus: JointBus,
        joint_names: list[str],
        limits: list[dict],
        controller: Callable[[dict], list[float] | None] | None = None,
        sensors: dict[str, Callable[[], Sample | None]] | None = None,
        image_shapes: dict[str, tuple[int, int, int]] | None = None,
        audio_sample_rate: int | None = None,
        fps: int = 10,
        control_hz: int = 30,
        output: str | Path = "dataset",
        repo_id: str = "local/in-process",
        unit: str,
        dataset=None,
    ) -> InProcessSession:
        if (
            len(joint_names) != len(limits)
            or len(set(joint_names)) != len(joint_names)
            or not joint_names
        ):
            raise ValueError("joint_names and limits must match")
        if control_hz < fps:
            raise ValueError("control_hz must be >= fps")
        spec = Follower(
            "follower", {"limits": limits, "control_hz": control_hz}, joint_names, unit
        )
        inputs: dict[str, InputDevice] = {}
        if "leader" in (sensors or {}):
            inputs["leader"] = JointInput("leader", {}, joint_names, unit)
        streams: dict[str, Source] = {}
        for name, shape in (image_shapes or {}).items():
            if (
                name in ("follower", "leader", ACTION, "audio")
                or len(shape) != 3
                or shape[2] != 3
            ):
                raise ValueError("image sensor requires HWC RGB shape")
            streams[name] = ImageSensor(name, {"height": shape[0], "width": shape[1]})
        if audio_sample_rate is not None:
            streams["audio"] = PcmAudio("audio", {"sample_rate": audio_sample_rate})
        cfg = RobotConfig(
            robot=robot,
            repo_id=repo_id,
            output=str(output),
            dataset_fps=fps,
            followers={"follower": spec},
            inputs=inputs,
            sensors=streams,
            max_age_ms={name: 300 for name in (*inputs, "follower", *streams)},
        )
        return cls(cfg, bus, controller=controller, sensors=sensors, dataset=dataset)

    def start_episode(self, task: str) -> None:
        self.recorder.start(task)
        self.safety.arm()

    def start_inference(self) -> None:
        """Arm checked one-step control without creating an episode."""
        self.safety.arm()

    def stop_inference(self) -> None:
        self.safety.stop()

    def step(
        self, *, policy: Callable[[dict], list[float] | None] | None = None
    ) -> dict:
        """One checked control tick; policy overrides the configured controller."""
        now = time.monotonic_ns()
        try:
            state = positions(
                self.safety.bus.read_positions(), len(self.spec.joint_names)
            )
        except Exception:
            self.safety.stop()
            raise
        obs: dict[str, Any] = {"state": state}
        robot = self.spec.name
        for name, reader in self.sensors.items():
            try:
                sample = reader()
            except Exception:
                self.safety.stop()
                raise
            obs[name] = sample
            spec = self.specs.get(name)
            if sample is None or spec is None:
                continue
            self.recorder.ingest(
                name,
                self.publishers[name].make(
                    spec.kind, spec.encode(sample), sample.capture_ns
                ),
            )
        callback = policy if policy is not None else self.controller
        try:
            target = callback(obs) if callback else None
        except Exception:
            self.safety.stop()
            raise
        if target is not None:
            target = positions(target, len(state))
            command = make_command(
                self.publisher,
                follower=self.spec.name,
                unit=self.spec.unit,
                target=target,
                now_ns=now,
                deadline_ms=self.deadline_ms,
            )
            self.safety.accept(command)
        state_msg, action_msg = self.safety.tick()
        self.recorder.ingest(robot, state_msg)
        self.recorder.ingest(action_stream(robot), action_msg)
        self.recorder.poll()
        return {
            "observation": obs,
            "action": action_msg.payload,
            "mode": state_msg.payload["mode"],
        }

    def run(
        self,
        seconds: float,
        *,
        policy: Callable[[dict], list[float] | None] | None = None,
    ) -> list[dict]:
        results = []
        end = time.monotonic() + seconds
        next_tick = time.monotonic()
        while time.monotonic() < end:
            results.append(self.step(policy=policy))
            next_tick += self.period_s
            time.sleep(max(0, next_tick - time.monotonic()))
        return results

    def stop_episode(self) -> None:
        self.safety.stop()
        self.recorder.stop()

    def save_episode(self) -> int:
        self.last_metrics = self.recorder.metrics()
        return self.recorder.save()

    def discard_episode(self) -> None:
        self.safety.stop()
        self.recorder.discard()

    def estop(self) -> None:
        self.safety.stop(estop=True)

    def release(self) -> None:
        """Torque off after stop; support the arm first. Latched until the robot is reopened."""
        self.safety.release()

    def close(self) -> None:
        """Close the recorder and the bus without releasing torque: what the follower does
        next is its `traits().unattended` (holds, goes limp, or not known)."""
        try:
            self.recorder.close()
        finally:
            self.safety.bus.close()
            for closer in self._extra_closers:
                closer()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_):
        self.close()
