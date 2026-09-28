"""Render the dora dataflow from a validated experiment."""

from __future__ import annotations

from pathlib import Path

import yaml

from ..config import ExperimentConfig
from ..recording import ACTION


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
    nodes = [node(name, {}, ["sample"], source.rate_hz(fps) or control_hz) for name, source in cfg.inputs.items()]
    nodes += [
        node(name, {"intent": f"{c.source.name}/sample", "robot": f"{c.robot.name}/state"}, ["command"])
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
            ["state", ACTION],
            robot.control_hz,
        )
        for name, robot in cfg.robots.items()
    ]
    nodes += [node(name, {}, ["sample"], sensor.rate_hz(fps) or control_hz) for name, sensor in cfg.sensors.items()]
    recorded = {name: f"{name}/{'state' if name in cfg.robots else 'sample'}" for name in cfg.sources}
    nodes.append(node("recorder", {**recorded, ACTION: f"{cfg.robot.name}/{ACTION}", "session": "session/control"}, ["report"]))
    nodes.append(node("session", {"report": "recorder/report"}, ["control"]))
    return {"nodes": nodes}


def write_flow(cfg: ExperimentConfig, path: str | Path) -> Path:
    target = Path(path)
    target.write_text(yaml.safe_dump(build_flow(cfg), sort_keys=False))
    return target
