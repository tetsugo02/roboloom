#!/usr/bin/env python3
"""Executable dora node. The node id selects its role from the experiment config."""

from __future__ import annotations

import json
import os
import sys

from roboloom.config import ExperimentConfig, load_experiment
from roboloom.controllers.base import Controller
from roboloom.core.protocol import Envelope, Publisher
from roboloom.core.source import Source
from roboloom.recording import ACTION, EpisodeRecorder
from roboloom.robots.base import Robot
from roboloom.robots.safety import FollowerSafety


def _send(node, output: str, msg: Envelope) -> None:
    node.send_output(output, msg.encode())


def _event(node):
    event = node.next(timeout=0.1)
    if event is None:
        return None, None
    if event.get("type") != "INPUT":
        return None, None
    return event["id"], None if event["id"] == "tick" else Envelope.decode(event["value"])


def _session(node):
    p = Publisher("session")
    fifo = os.environ["ROBOLOOM_SESSION_FIFO"]
    fd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
    pending = b""
    try:
        while True:
            try:
                pending += os.read(fd, 4096)
            except BlockingIOError:
                pass
            while b"\n" in pending:
                raw, pending = pending.split(b"\n", 1)
                cmd, _, task = raw.decode().strip().partition(" ")
                if cmd in ("start", "stop", "save", "discard", "estop", "quit"):
                    _send(node, "control", p.make("session", {"command": cmd, "task": task}))
                    if cmd == "quit":
                        return
            event_id, msg = _event(node)
            if event_id == "report" and msg is not None:
                print(msg.payload, flush=True)
                with open(os.environ["ROBOLOOM_REPORT_PATH"], "a") as report:
                    report.write(json.dumps(msg.payload) + "\n")
    finally:
        os.close(fd)


def _source(node, source: Source, cfg: ExperimentConfig):
    """Inputs and sensors: read the device on every tick and publish its sample."""
    reader = source.open(cfg.mock, cfg.dataset_fps)
    p = Publisher(source.name)
    try:
        while True:
            event_id, _ = _event(node)
            if event_id != "tick":
                continue
            sample = reader.read()
            if sample is not None:
                _send(node, "sample", p.make(source.kind, source.encode(sample), sample.capture_ns))
    finally:
        reader.close()


def _robot(node, robot: Robot, cfg: ExperimentConfig):
    bus = robot.open_bus(cfg.mock)
    safety = FollowerSafety(robot.safety_config(cfg.robot_id), bus)
    try:
        safety.start()
        while True:
            event_id, msg = _event(node)
            if event_id == "command" and msg is not None:
                safety.accept(msg)
            elif event_id == "session" and msg is not None:
                command = msg.payload["command"]
                if command == "start":
                    safety.arm()
                elif command in ("stop", "discard"):
                    safety.stop()
                elif command in ("estop", "quit"):
                    safety.stop(estop=True)
            elif event_id == "tick":
                state, action = safety.tick()
                _send(node, "state", state)
                _send(node, ACTION, action)
    finally:
        bus.close()


def _controller(node, controller: Controller):
    follower = None
    while True:
        event_id, msg = _event(node)
        if event_id == "robot" and msg is not None:
            follower = msg.payload["positions"]
            if msg.payload["mode"] in ("FAULT", "ESTOP"):
                controller.reset()
        elif event_id == "intent" and msg is not None and follower is not None:
            command = controller.update(msg, follower)
            if command:
                _send(node, "command", command)


def _recorder(node, cfg: ExperimentConfig):
    p = Publisher("recorder")
    writer = EpisodeRecorder(cfg)
    try:
        while True:
            event_id, msg = _event(node)
            if event_id in writer.samples and msg is not None:
                writer.ingest(event_id, msg)
            elif event_id == "session" and msg is not None:
                command = msg.payload["command"]
                try:
                    if command == "start":
                        writer.start(msg.payload["task"])
                    elif command == "stop":
                        writer.stop()
                    elif command == "save":
                        metrics = writer.metrics()
                        count = writer.save()
                        _send(node, "report", p.make("report", {"saved_frames": count, "episodes": writer.dataset.num_episodes, "metrics": metrics}))
                    elif command == "discard":
                        writer.discard()
                    elif command == "quit":
                        return
                except Exception as exc:  # noqa: BLE001 - report session failure to operator
                    _send(node, "report", p.make("report", {"error": str(exc)}))
    finally:
        writer.close()


def main() -> None:
    from dora import Node

    name, path = sys.argv[1:3]
    cfg = load_experiment(path)
    node = Node()
    if name == "session":
        _session(node)
    elif name == "recorder":
        _recorder(node, cfg)
    elif name in cfg.robots:
        _robot(node, cfg.robots[name], cfg)
    elif name in cfg.controllers:
        _controller(node, cfg.controllers[name])
    elif name in cfg.inputs:
        _source(node, cfg.inputs[name], cfg)
    elif name in cfg.sensors:
        _source(node, cfg.sensors[name], cfg)
    else:
        raise SystemExit(f"unknown node {name!r}")


if __name__ == "__main__":
    main()
