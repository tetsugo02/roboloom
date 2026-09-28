#!/usr/bin/env python3
"""Executable dora node for each device and service role."""

from __future__ import annotations

import json
import os
import sys
import time
from importlib import import_module

import numpy as np

from roboloom.config import load_experiment
from roboloom.control import FollowerSafety, JointController
from roboloom.devices import open_bus, read_camera, read_digit
from roboloom.protocol import Envelope, Publisher, pack_array
from roboloom.recording import SOURCES, EpisodeRecorder


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


def _leader(node, cfg, mock):
    bus = open_bus(cfg, mock)
    p = Publisher("leader")
    try:
        while True:
            event_id, _ = _event(node)
            if event_id == "tick":
                values = bus.read_positions()
                capture = time.monotonic_ns()
                _send(node, "leader", p.make("leader", {"positions": values, "unit": "dynamixel_count"}, capture))
    finally:
        bus.close()


def _robot(node, cfg, mock):
    bus = open_bus(cfg, mock)
    safety = FollowerSafety(cfg, bus)
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
                _send(node, "robot", state)
                _send(node, "action", action)
    finally:
        bus.close()


def _controller(node, cfg):
    controller = JointController(cfg)
    follower = None
    while True:
        event_id, msg = _event(node)
        if event_id == "robot" and msg is not None:
            follower = msg.payload["positions"]
            if msg.payload["mode"] in ("FAULT", "ESTOP"):
                controller.aligned = False
        elif event_id == "leader" and msg is not None and follower is not None:
            command = controller.update(msg, follower)
            if command:
                _send(node, "command", command)


def _image_node(node, name, cfg, mock):
    device = read_camera(cfg, mock) if name == "camera" else read_digit(cfg, mock)
    p = Publisher(name)
    try:
        while True:
            event_id, _ = _event(node)
            if event_id != "tick":
                continue
            if mock:
                image, capture = device[0].copy(), time.monotonic_ns()
            elif name == "camera":

                frames = device.wait_for_frames(timeout_ms=1000)
                frame = frames.get_color_frame()
                if not frame:
                    continue
                image, capture = np.asarray(frame.get_data()).copy(), time.monotonic_ns()
            else:
                image, capture = device.get_frame().copy(), time.monotonic_ns()
            _send(node, name, p.make(name, {"image": pack_array(image)}, capture))
    finally:
        if not mock:
            device.stop() if name == "camera" else device.disconnect()


def _audio(node, cfg, fps, mock):
    p = Publisher("audio")
    size = int(cfg["sample_rate"] / fps)
    while True:
        event_id, _ = _event(node)
        if event_id != "tick":
            continue
        if mock:
            samples = np.zeros(size, np.int16)
        else:
            sd = import_module("sounddevice")

            samples = sd.rec(size, samplerate=cfg["sample_rate"], channels=1, dtype="int16", device=cfg["device"], blocking=True).reshape(-1)
        capture = time.monotonic_ns()
        _send(node, "audio", p.make("audio", {"pcm": pack_array(samples)}, capture))


def _recorder(node, cfg):
    p = Publisher("recorder")
    writer = EpisodeRecorder(cfg)
    try:
        while True:
            event_id, msg = _event(node)
            if event_id in (*SOURCES, "action") and msg is not None:
                writer.ingest(msg)
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
    n = cfg["nodes"]
    mock = cfg["experiment"]["mode"] == "mock"
    node = Node()
    if name == "session":
        _session(node)
    elif name == "leader":
        _leader(node, n[name], mock)
    elif name == "robot":
        _robot(node, {**n[name], "robot_id": cfg["experiment"]["robot_id"]}, mock)
    elif name == "controller":
        _controller(node, {**n[name], "robot_id": cfg["experiment"]["robot_id"]})
    elif name in ("camera", "digit_left", "digit_right"):
        _image_node(node, name, n[name], mock)
    elif name == "audio":
        _audio(node, n[name], cfg["experiment"]["dataset_fps"], mock)
    elif name == "recorder":
        _recorder(node, cfg)


if __name__ == "__main__":
    main()
