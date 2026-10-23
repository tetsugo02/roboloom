"""Render the dora dataflow from a validated experiment."""

from __future__ import annotations

import math
from pathlib import Path

import yaml

from ..config import ExperimentConfig
from ..recording import ACTION

STATUS_SUFFIX = "_status"  # session input ids; runtime.node reads the same suffix


def build_flow(cfg: ExperimentConfig) -> dict:
    script = str(Path(__file__).with_name("node.py").resolve())
    fps = cfg.dataset_fps

    def node(name, inputs, outputs, tick=None):
        if tick is not None:
            inputs = {**inputs, "tick": f"dora/timer/hz/{int(tick)}"}
        return {
            "id": name,
            "path": script,
            "args": f"{name} {cfg.path}",
            "inputs": inputs,
            "outputs": outputs,
            "restart_policy": "never",
        }

    control_hz = cfg.robot.control_hz
    session = {"session": "session/control"}  # every node ends on `quit`
    nodes = [node(name, session, ["sample", "status"], source.rate_hz(fps) or control_hz) for name, source in cfg.inputs.items()]
    nodes += [
        node(name, {"intent": f"{c.source.name}/sample", "robot": f"{c.robot.name}/state", **session}, ["command", "status"])
        for name, c in cfg.controllers.items()
    ]
    nodes += [
        node(
            name,
            {
                "command": {
                    "source": f"{cfg.controller_for(name).name}/command",
                    "queue_size": 1,
                    "queue_policy": "drop_oldest",
                },
                "session": "session/control",
            },
            ["state", ACTION, "status"],
            robot.control_hz,
        )
        for name, robot in cfg.robots.items()
    ]
    nodes += [node(name, session, ["sample", "status"], sensor.rate_hz(fps) or control_hz) for name, sensor in cfg.sensors.items()]
    # Bounded recorder queues: while `save` encodes video the recorder does not read, and dora
    # hands a node all queued events in one reply (64 MB limit). Keep about `queue_s` per stream.
    queue_s = float(cfg.recorder.get("queue_s", 0.5))

    def bounded(output: str, rate_hz: float) -> dict:
        return {"source": output, "queue_size": max(2, math.ceil(rate_hz * queue_s)), "queue_policy": "drop_oldest"}

    rates = {**{n: s.rate_hz(fps) or control_hz for n, s in {**cfg.inputs, **cfg.sensors}.items()}, **{n: r.control_hz for n, r in cfg.robots.items()}}
    recorded = {name: bounded(f"{name}/{'state' if name in cfg.robots else 'sample'}", rates[name]) for name in cfg.sources}
    recorded[ACTION] = bounded(f"{cfg.robot.name}/{ACTION}", cfg.robot.control_hz)
    nodes.append(node("recorder", {**recorded, **session}, ["report", "status"]))
    statuses = {f"{name}{STATUS_SUFFIX}": {"source": f"{name}/status", "queue_size": 2, "queue_policy": "drop_oldest"} for name in [n["id"] for n in nodes]}
    nodes.append(node("session", {"report": "recorder/report", **statuses}, ["control"]))
    return {"nodes": nodes}


def write_flow(cfg: ExperimentConfig, path: str | Path) -> Path:
    target = Path(path)
    target.write_text(yaml.safe_dump(build_flow(cfg), sort_keys=False))
    return target
