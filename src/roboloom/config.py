"""Experiment configuration and offline validation."""

from __future__ import annotations

import math
import re
from pathlib import Path

import yaml

JOINTS = (
    "torso_yaw", "head_yaw", "head_pitch",
    "r_arm_sh_pitch1", "r_arm_sh_roll", "r_arm_sh_pitch2", "r_arm_el_yaw",
    "r_arm_wr_roll", "r_arm_wr_yaw", "r_arm_grip",
    "l_arm_sh_pitch1", "l_arm_sh_roll", "l_arm_sh_pitch2", "l_arm_el_yaw",
    "l_arm_wr_roll", "l_arm_wr_yaw", "l_arm_grip",
)
MOTOR_IDS = (27, 28, 29, 1, 3, 5, 7, 9, 11, 31, 2, 4, 6, 8, 10, 12, 30)


def _read(path: Path) -> dict:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise TypeError(f"{path}: expected YAML mapping")
    return data


def _positive(value: object, name: str) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name}: expected positive finite number")
    return float(value)


def _identity(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("SET_"):
        raise ValueError(f"{name}: explicit device identity required")
    return value


def load_experiment(path: str | Path) -> dict:
    """Resolve referenced node YAML files, then validate without opening devices."""
    path = Path(path).resolve()
    raw = _read(path)
    if isinstance(raw.get("output"), str) and raw["output"]:
        raw["output"] = str((path.parent / raw["output"]).resolve())
    if set(raw.get("nodes", {})) != {"leader", "controller", "robot", "camera", "digit_left", "digit_right", "audio", "recorder", "session"}:
        raise ValueError("nodes must reference leader, controller, robot, camera, both DIGIT, audio, recorder and session")
    nodes = {}
    for name, relative in raw["nodes"].items():
        if not isinstance(relative, str):
            raise TypeError(f"nodes.{name}: expected YAML path")
        nodes[name] = _read((path.parent / relative).resolve())
    raw.setdefault("robot_type", "rakuda")
    cfg = {"experiment": raw, "nodes": nodes, "path": str(path)}
    validate(cfg)
    return cfg


def validate(cfg: dict) -> None:
    e, n = cfg["experiment"], cfg["nodes"]
    _identity(e.get("robot_id"), "robot_id")
    _identity(e.get("repo_id"), "repo_id")
    _identity(e.get("output"), "output")
    if e.get("mode") not in ("mock", "hardware"):
        raise ValueError("mode must be mock or hardware")
    fps = _positive(e.get("dataset_fps"), "dataset_fps")
    hz = _positive(n["robot"].get("control_hz"), "control_hz")
    if hz < fps:
        raise ValueError("control_hz must be >= dataset_fps")
    if n["leader"].get("type") != "rakuda_leader" or n["robot"].get("type") != "rakuda_follower":
        raise ValueError("initial release supports Rakuda leader -> Rakuda follower only")
    c = n["controller"]
    if c.get("type") != "joint" or c.get("input") != "leader" or c.get("robot") != "robot" or c.get("unit") != "dynamixel_count":
        raise ValueError("controller must map leader to robot in raw Dynamixel counts")
    mapping = c.get("joints")
    if not isinstance(mapping, list) or len(mapping) != 17 or [j.get("follower") for j in mapping] != list(JOINTS) or {j.get("leader") for j in mapping} != set(JOINTS):
        raise ValueError("controller needs a complete, ordered, one-to-one 17 joint mapping")
    for j in mapping:
        if j.get("sign") not in (-1, 1) or not isinstance(j.get("offset"), (int, float)) or not math.isfinite(j["offset"]):
            raise ValueError("joint sign must be +/-1 and offset finite")
    for field in ("alignment_tolerance", "max_speed_counts_per_s", "command_deadline_ms", "input_timeout_ms"):
        _positive(c.get(field), field)
    limits = n["robot"].get("limits")
    if not isinstance(limits, list) or len(limits) != 17:
        raise ValueError("robot.limits needs 17 explicit bounds")
    for joint, limit in zip(JOINTS, limits, strict=True):
        if limit.get("name") != joint or not all(isinstance(limit.get(k), (int, float)) and math.isfinite(limit[k]) for k in ("min", "max", "max_step")) or not (limit["min"] < limit["max"] and limit["max_step"] > 0):
            raise ValueError(f"invalid bounds for {joint}")
    if n["leader"].get("motor_ids") != list(MOTOR_IDS) or n["robot"].get("motor_ids") != list(MOTOR_IDS):
        raise ValueError("Rakuda motor IDs/order must match explicit canonical mapping")
    ports = [_identity(n[x].get("port"), f"{x}.port") for x in ("leader", "robot")]
    ids = [_identity(n[x].get("serial"), f"{x}.serial") for x in ("camera", "digit_left", "digit_right")]
    if len(set(ports)) != 2 or len(set(ids)) != 3:
        raise ValueError("duplicate port or sensor ID")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", e["repo_id"]):
        raise ValueError("repo_id must be namespace/name")
    for sensor in ("camera", "digit_left", "digit_right"):
        if n[sensor].get("type") != ("realsense_rgb" if sensor == "camera" else "digit"):
            raise ValueError(f"unsupported {sensor} sensor")
        for field in ("width", "height", "fps"):
            _positive(n[sensor].get(field), f"{sensor}.{field}")
    if n["audio"].get("type") != "pcm_mono":
        raise ValueError("audio must be mono PCM")
    _identity(n["audio"].get("device"), "audio.device")
    _positive(n["audio"].get("sample_rate"), "audio.sample_rate")
    if n["audio"].get("channels") != 1:
        raise ValueError("audio must have one channel")
    for sensor in ("leader", "robot", "camera", "digit_left", "digit_right", "audio"):
        _positive(n["recorder"].get("max_age_ms", {}).get(sensor), f"max_age_ms.{sensor}")
    if n["session"].get("type") != "terminal":
        raise ValueError("session must be terminal")
