"""Render and inspect the single-Rakuda dora dataflow."""

from __future__ import annotations

from pathlib import Path

import yaml


def build_flow(cfg: dict) -> dict:
    e, n = cfg["experiment"], cfg["nodes"]
    script = str(Path(__file__).with_name("node.py").resolve())

    def node(name, inputs, outputs, tick=None):
        if tick is not None:
            inputs = {**inputs, "tick": f"dora/timer/hz/{int(tick)}"}
        return {
            "id": name,
            "path": script,
            "args": f"{name} {cfg['path']}",
            "inputs": inputs,
            "outputs": outputs,
            "restart_policy": "never",
        }

    return {
        "nodes": [
            node(
                "leader",
                {},
                ["leader"],
                n["leader"].get("poll_hz", n["robot"]["control_hz"]),
            ),
            node(
                "controller",
                {"leader": "leader/leader", "robot": "robot/robot"},
                ["command"],
            ),
            node(
                "robot",
                {
                    "command": {
                        "source": "controller/command",
                        "queue_size": 1,
                        "queue_policy": "drop_oldest",
                    },
                    "session": "session/control",
                },
                ["robot", "action"],
                n["robot"]["control_hz"],
            ),
            node("camera", {}, ["camera"], n["camera"]["fps"]),
            node("digit_left", {}, ["digit_left"], n["digit_left"]["fps"]),
            node("digit_right", {}, ["digit_right"], n["digit_right"]["fps"]),
            node("audio", {}, ["audio"], e["dataset_fps"]),
            node(
                "recorder",
                {
                    **{
                        s: f"{s}/{s}"
                        for s in (
                            "leader",
                            "robot",
                            "camera",
                            "digit_left",
                            "digit_right",
                            "audio",
                        )
                    },
                    "action": "robot/action",
                    "session": "session/control",
                },
                ["report"],
            ),
            node("session", {"report": "recorder/report"}, ["control"]),
        ]
    }


def write_flow(cfg: dict, path: str | Path) -> Path:
    target = Path(path)
    target.write_text(yaml.safe_dump(build_flow(cfg), sort_keys=False))
    return target
