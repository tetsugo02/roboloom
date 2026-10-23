#!/usr/bin/env python3
"""Executable dora node. The node id selects its role from the experiment config."""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from collections import deque

from roboloom.config import ExperimentConfig, load_experiment
from roboloom.controllers.base import Controller
from roboloom.core.protocol import Envelope, Publisher
from roboloom.core.source import Source
from roboloom.core.status import StatusReporter
from roboloom.recording import ACTION, EpisodeRecorder
from roboloom.robots.base import Robot
from roboloom.robots.safety import FollowerSafety

COMMANDS = ("start", "stop", "save", "discard", "estop", "release", "quit")
from roboloom.runtime.flow import STATUS_SUFFIX


def _send(node, output: str, msg: Envelope) -> None:
    node.send_output(output, msg.encode())


def _event(node):
    event = node.next(timeout=0.1)
    if event is None:
        return None, None
    if event.get("type") != "INPUT":
        return None, None
    return event["id"], None if event["id"] == "tick" else Envelope.decode(event["value"])


def _session(node, cfg: ExperimentConfig):
    """Forward terminal commands; collect reports and the latest status of every node for the CLI."""
    p = Publisher("session")
    fifo = os.environ["ROBOLOOM_SESSION_FIFO"]
    status_path = os.environ.get("ROBOLOOM_STATUS_PATH")
    fd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
    pending = b""
    latest: dict[str, dict] = {}
    written_ns = 0
    try:
        while True:
            try:
                pending += os.read(fd, 4096)
            except BlockingIOError:
                pass
            while b"\n" in pending:
                raw, pending = pending.split(b"\n", 1)
                cmd, _, task = raw.decode().strip().partition(" ")
                if cmd in COMMANDS:
                    _send(node, "control", p.make("session", {"command": cmd, "task": task}))
                    if cmd == "quit":
                        return
            event_id, msg = _event(node)
            if event_id == "report" and msg is not None:
                print(msg.payload, flush=True)
                with open(os.environ["ROBOLOOM_REPORT_PATH"], "a") as report:
                    report.write(json.dumps(msg.payload) + "\n")
            elif event_id is not None and event_id.endswith(STATUS_SUFFIX) and msg is not None:
                latest[event_id.removesuffix(STATUS_SUFFIX)] = {**msg.payload, "t_ns": msg.t_ready_ns}
            now = time.monotonic_ns()
            if status_path and latest and now - written_ns > 200_000_000:  # at most 5 Hz
                tmp = f"{status_path}.tmp"
                with open(tmp, "w") as out:
                    json.dump({"t_ns": now, "experiment": cfg.path, "mode": cfg.mode, "nodes": latest}, out)
                os.replace(tmp, status_path)
                written_ns = now
    finally:
        os.close(fd)


def _quit(event_id, msg) -> bool:
    return event_id == "session" and msg is not None and msg.payload["command"] == "quit"


def _source(node, source: Source, cfg: ExperimentConfig, role: str):
    """Inputs and sensors: read the device on every tick and publish its sample."""
    reader = source.open(cfg.mock, cfg.dataset_fps)
    p = Publisher(source.name)
    status = StatusReporter(Publisher(source.name), role)
    on_session = getattr(reader, "on_session", None)
    samples: deque[int] = deque(maxlen=60)
    misses = 0
    try:
        while True:
            event_id, msg = _event(node)
            if event_id == "session" and msg is not None:
                if on_session is not None:
                    on_session(msg.payload["command"], msg.payload.get("task", ""))
                if _quit(event_id, msg):
                    return
                continue
            if event_id == "tick":
                sample = reader.read()
                if sample is not None:
                    _send(node, "sample", p.make(source.kind, source.encode(sample), sample.capture_ns))
                    samples.append(time.monotonic_ns())
                else:
                    misses += 1
            now = time.monotonic_ns()
            if status.due(now):
                rate = (len(samples) - 1) / ((samples[-1] - samples[0]) / 1e9) if len(samples) > 1 and samples[-1] > samples[0] else 0.0
                age_ms = (now - samples[-1]) / 1e6 if samples else None
                level = "ok" if age_ms is not None and age_ms < 500 else "warn"
                fields = {"rate_hz": round(rate, 1), "age_ms": None if age_ms is None else round(age_ms), "misses": misses}
                _send(node, "status", status.make(fields, level, now))
    finally:
        reader.close()


def _robot(node, robot: Robot, cfg: ExperimentConfig):
    bus = robot.open_device(cfg.mock)
    safety = FollowerSafety(robot.safety_config(cfg.robot_id), bus)
    status = StatusReporter(Publisher(robot.name), "robot")
    intervals: deque[float] = deque(maxlen=int(robot.control_hz * 2))
    clamped: deque[bool] = deque(maxlen=int(robot.control_hz * 2))
    rejected: deque[bool] = deque(maxlen=int(robot.control_hz * 2))
    error = ""
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
                elif command == "release":
                    try:
                        safety.release()
                    except RuntimeError as exc:
                        error = str(exc)
                if command == "quit":
                    return
            elif event_id == "tick":
                state, action = safety.tick()
                _send(node, "state", state)
                _send(node, ACTION, action)
                intervals.append(state.payload["tick_interval_ms"])
                clamped.append(bool(action.payload["clamped"]))
                rejected.append(bool(state.payload["rejected"]))
            now = time.monotonic_ns()
            if status.due(now):
                fields = {
                    "mode": safety.mode, "reason": safety.reason, "armed": safety.armed,
                    "tick_ms": round(intervals[-1], 1) if intervals else None,
                    "tick_max_ms": round(max(intervals), 1) if intervals else None,
                    "clamped_2s": sum(clamped), "rejected_2s": sum(rejected),
                    "last_reject": safety.last_reject if any(rejected) else "", "error": error,
                }
                level = {"FAULT": "error", "ESTOP": "error", "RELEASED": "warn"}.get(safety.mode, "warn" if any(rejected) else "ok")
                _send(node, "status", status.make(fields, level, now))
    finally:
        bus.close()


def _controller(node, controller: Controller):
    follower = follower_target = None
    status = StatusReporter(Publisher(controller.name), "controller")
    last_intent_ns = 0
    commands: deque[int] = deque(maxlen=60)
    timeout_ns = int(controller.cfg.get("input_timeout_ms", 150) * 1e6)
    while True:
        event_id, msg = _event(node)
        if _quit(event_id, msg):
            return
        if event_id == "robot" and msg is not None:
            follower, follower_target = msg.payload["positions"], msg.payload.get("target")
            if msg.payload["mode"] in ("FAULT", "ESTOP"):
                controller.reset()
        elif event_id == "intent" and msg is not None and follower is not None:
            last_intent_ns = time.monotonic_ns()
            command = controller.update(msg, follower, follower_target=follower_target)
            if command:
                _send(node, "command", command)
                commands.append(time.monotonic_ns())
        now = time.monotonic_ns()
        if status.due(now):
            fields = controller.status()
            if now - last_intent_ns > timeout_ns:
                fields["state"] = "input_stale" if last_intent_ns else "waiting_input"
            recent = [t for t in commands if now - t < 1e9]
            fields["command_hz"] = len(recent)
            level = "ok" if fields.get("state") == "following" else "warn"
            _send(node, "status", status.make(fields, level, now))


def _recorder(node, cfg: ExperimentConfig):
    """Records episodes. `save` (video encoding) runs on a worker thread so this loop keeps
    draining dora events; otherwise queued frames exceed dora's per-reply size limit and are lost."""
    p = Publisher("recorder")
    writer = EpisodeRecorder(cfg, **cfg.recorder)
    writer.open_dataset()  # creating/resuming takes ~1 s; never inside an episode
    robot_mode = None
    saving: threading.Thread | None = None
    done: queue.Queue[dict] = queue.Queue()
    status = StatusReporter(Publisher("recorder"), "recorder")

    def save(metrics: dict) -> None:
        try:
            done.put({"saved_frames": writer.save(), "episodes": writer.dataset.num_episodes, "metrics": metrics})
        except Exception as exc:  # noqa: BLE001 - report session failure to operator
            done.put({"command": "save", "error": str(exc)})

    try:
        while True:
            event_id, msg = _event(node)
            while not done.empty():
                _send(node, "report", p.make("report", done.get()))
            if saving is not None and not saving.is_alive():
                saving = None
            writer.poll()
            now = time.monotonic_ns()
            if status.due(now):
                state = "saving" if saving is not None else "recording" if writer.active else "stopped" if writer.stopped else "idle"
                fields = {
                    "state": state, "task": writer.task if state != "idle" else "", "rows": writer.written,
                    "elapsed_s": round((now - writer.t0_ns) / 1e9, 1) if writer.active else None,
                    "missing": {k: v for k, v in writer.missing.items() if v}, "episodes": writer.dataset.num_episodes,
                }
                level = "warn" if any(writer.missing.values()) and writer.active else "ok"
                _send(node, "status", status.make(fields, level, now))
            if event_id in writer.samples and msg is not None:
                writer.ingest(event_id, msg)
                if event_id == cfg.robot.name and msg.payload.get("mode") != robot_mode:
                    robot_mode = msg.payload.get("mode")
                    _send(node, "report", p.make("report", {"robot_mode": robot_mode, "reason": msg.payload.get("reason", "")}))
            elif event_id == "session" and msg is not None:
                command = msg.payload["command"]
                try:
                    if saving is not None and command in ("start", "save", "discard"):
                        raise RuntimeError("the previous episode is still being saved; retry shortly")
                    if command == "start":
                        writer.start(msg.payload["task"])
                    elif command == "stop":
                        writer.stop()
                    elif command == "save":
                        if not writer.stopped:
                            raise RuntimeError("stop the episode first")
                        saving = threading.Thread(target=save, args=(writer.metrics(),), name="save-episode")
                        saving.start()
                    elif command == "discard":
                        writer.discard()
                    elif command == "quit":
                        if saving is not None:
                            saving.join()
                        while not done.empty():
                            _send(node, "report", p.make("report", done.get()))
                        return
                except Exception as exc:  # noqa: BLE001 - report session failure to operator
                    _send(node, "report", p.make("report", {"command": command, "error": str(exc)}))
    finally:
        if saving is not None:
            saving.join()
        writer.close()


def main() -> None:
    from dora import Node

    name, path = sys.argv[1:3]
    cfg = load_experiment(path)
    node = Node()
    if name == "session":
        _session(node, cfg)
    elif name == "recorder":
        _recorder(node, cfg)
    elif name in cfg.robots:
        _robot(node, cfg.robots[name], cfg)
    elif name in cfg.controllers:
        _controller(node, cfg.controllers[name])
    elif name in cfg.inputs:
        _source(node, cfg.inputs[name], cfg, "input")
    elif name in cfg.sensors:
        _source(node, cfg.sensors[name], cfg, "sensor")
    else:
        raise SystemExit(f"unknown node {name!r}")


if __name__ == "__main__":
    main()
