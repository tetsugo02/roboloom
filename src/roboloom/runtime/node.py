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
from pathlib import Path

from roboloom.config import ExperimentConfig, load_experiment
from roboloom.controllers.base import Controller
from roboloom.controllers.policy import PolicyController
from roboloom.core.protocol import Envelope, Publisher
from roboloom.core.source import Source
from roboloom.core.status import GcPauses, StatusReporter
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
    return event["id"], None if event["id"] == "tick" else Envelope.decode(
        event["value"]
    )


READY = ("following", "ready", "running")  # controller states that may start an episode


def start_warning(
    cfg: ExperimentConfig, latest: dict[str, dict], now_ns: int
) -> str | None:
    """Why an episode may not start yet (checked before start reaches the robot and
    recorder), or None. `latest` maps node names to their last status."""
    for name in cfg.controllers:
        status = latest.get(name)
        # Reports arrive at 4 Hz; never start from missing or outdated readiness.
        if status is None or not 0 <= now_ns - status["t_ns"] <= 1_000_000_000:
            return f"{name}: no recent controller status; wait and retry start"
        fields = status["fields"]
        state = fields.get("state")
        if state == "aligning":
            return (
                f"{name}: move the leader: {fields.get('worst_joint')} differs by "
                f"{fields.get('worst_diff')} (tolerance {fields.get('tolerance')}); "
                "align the leader with the follower, then retry start"
            )
        if state not in READY:
            return f"{name}: controller is {state}; wait until ready, then retry start"
        # Checked before every start: following can leave the follower behind the leader
        # (speed and range limits), and the first alignment says nothing about later ones.
        diff, tolerance = fields.get("worst_diff"), fields.get("tolerance")
        if diff is not None and tolerance is not None and diff > tolerance:
            return (
                f"{name}: the follower is not at the leader: {fields.get('worst_joint')} "
                f"differs by {diff} (tolerance {tolerance}); hold the leader still near "
                "the follower, then retry start"
            )
    return None


def parse_command(line: str) -> dict:
    """A command line from the FIFO: JSON {"id", "command", "task"} from a Session, or
    plain `start <task>` typed by an operator (no id)."""
    line = line.strip()
    if line.startswith("{"):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return {"command": line, "task": ""}
        return {
            "id": data.get("id"),
            "command": str(data.get("command", "")),
            "task": str(data.get("task", "")),
        }
    command, _, task = line.partition(" ")
    return {"command": command, "task": task.strip()}


def _session(node, cfg: ExperimentConfig):
    """Forward terminal commands; collect reports and the latest status of every node for the CLI."""
    p = Publisher("session")
    fifo = os.environ["ROBOLOOM_SESSION_FIFO"]
    status_path = os.environ.get("ROBOLOOM_STATUS_PATH")
    fd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
    pending = b""
    latest: dict[str, dict] = {}
    written_ns = 0

    def report(payload: dict) -> None:
        print(payload, flush=True)
        with open(os.environ["ROBOLOOM_REPORT_PATH"], "a") as out:
            out.write(json.dumps(payload) + "\n")

    try:
        while True:
            try:
                pending += os.read(fd, 4096)
            except BlockingIOError:
                pass
            while b"\n" in pending:
                raw, pending = pending.split(b"\n", 1)
                request = parse_command(raw.decode())
                cmd = request["command"]
                if cmd not in COMMANDS:
                    report({**request, "error": f"unknown command {cmd!r}"})
                    continue
                if cmd == "start":
                    warning = start_warning(cfg, latest, time.monotonic_ns())
                    if warning is not None:
                        report({**request, "warning": warning})
                        continue
                _send(node, "control", p.make("session", request))
                if cmd == "quit":
                    return
            event_id, msg = _event(node)
            if event_id == "report" and msg is not None:
                report(msg.payload)
            elif (
                event_id is not None
                and event_id.endswith(STATUS_SUFFIX)
                and msg is not None
            ):
                latest[event_id.removesuffix(STATUS_SUFFIX)] = {
                    **msg.payload,
                    "t_ns": msg.t_ready_ns,
                }
            now = time.monotonic_ns()
            if (
                status_path and latest and now - written_ns > 200_000_000
            ):  # at most 5 Hz
                tmp = f"{status_path}.tmp"
                with open(tmp, "w") as out:
                    json.dump(
                        {
                            "t_ns": now,
                            "experiment": cfg.path,
                            "mode": cfg.mode,
                            "nodes": latest,
                        },
                        out,
                    )
                os.replace(tmp, status_path)
                written_ns = now
    finally:
        os.close(fd)


def _quit(event_id, msg) -> bool:
    return (
        event_id == "session" and msg is not None and msg.payload["command"] == "quit"
    )


def _source(node, source: Source, cfg: ExperimentConfig, role: str):
    """Inputs and sensors: read the device on every tick and publish its sample."""
    reader = source.open(cfg.mock, cfg.dataset_fps)
    log_dir = os.environ.get("ROBOLOOM_LOG_DIR")
    start_trace = getattr(reader, "start_trace", None)
    if log_dir and start_trace is not None:
        start_trace(Path(log_dir) / f"{source.name}_trace.npz")
    extra = getattr(reader, "status", None)
    p = Publisher(source.name)
    status = StatusReporter(Publisher(source.name), role)
    on_session = getattr(reader, "on_session", None)
    gc_pauses = GcPauses()
    samples: deque[int] = deque(maxlen=60)
    work: deque[float] = deque(maxlen=60)  # ms in read()
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
                began = time.perf_counter()
                sample = reader.read()
                work.append((time.perf_counter() - began) * 1e3)
                if sample is not None:
                    _send(
                        node,
                        "sample",
                        p.make(source.kind, source.encode(sample), sample.capture_ns),
                    )
                    samples.append(time.monotonic_ns())
                else:
                    misses += 1
            now = time.monotonic_ns()
            if status.due(now):
                rate = (
                    (len(samples) - 1) / ((samples[-1] - samples[0]) / 1e9)
                    if len(samples) > 1 and samples[-1] > samples[0]
                    else 0.0
                )
                age_ms = (now - samples[-1]) / 1e6 if samples else None
                level = "ok" if age_ms is not None and age_ms < 500 else "warn"
                fields = {
                    "rate_hz": round(rate, 1),
                    "age_ms": None if age_ms is None else round(age_ms),
                    "misses": misses,
                    **_work_fields(work),
                    "gc_max_ms": gc_pauses.take(),
                    **(extra() if extra is not None else {}),
                }
                _send(node, "status", status.make(fields, level, now))
    finally:
        reader.close()


def _work_fields(work: deque[float]) -> dict:
    """Time one tick spends in the device (bus I/O and control laws): the headroom left
    under the period tells how far `control_hz` / `poll_hz` can go."""
    if not work:
        return {"work_ms": None, "work_max_ms": None}
    return {"work_ms": round(work[-1], 1), "work_max_ms": round(max(work), 1)}


def _robot(node, robot: Robot, cfg: ExperimentConfig):
    bus = robot.open_device(cfg.mock)
    safety = FollowerSafety(robot.safety_config(cfg.robot_id), bus)
    status = StatusReporter(Publisher(robot.name), "robot")
    intervals: deque[float] = deque(maxlen=int(robot.control_hz * 2))
    clamped: deque[bool] = deque(maxlen=int(robot.control_hz * 2))
    rejected: deque[bool] = deque(maxlen=int(robot.control_hz * 2))
    work: deque[float] = deque(maxlen=int(robot.control_hz * 2))  # ms in tick()
    gc_pauses = GcPauses()
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
                    safety.stop()  # the operator confirmed: stop following, then let go
                    try:
                        safety.release()
                    except RuntimeError as exc:
                        error = str(exc)
                if command == "quit":
                    return
            elif event_id == "tick":
                began = time.perf_counter()
                state, action = safety.tick()
                work.append((time.perf_counter() - began) * 1e3)
                _send(node, "state", state)
                _send(node, ACTION, action)
                intervals.append(state.payload["tick_interval_ms"])
                clamped.append(bool(action.payload["clamped"]))
                rejected.append(bool(state.payload["rejected"]))
            now = time.monotonic_ns()
            if status.due(now):
                fields = {
                    "mode": safety.mode,
                    "reason": safety.reason,
                    "armed": safety.armed,
                    "tick_ms": round(intervals[-1], 1) if intervals else None,
                    "tick_max_ms": round(max(intervals), 1) if intervals else None,
                    **_work_fields(work),
                    "clamped_2s": sum(clamped),
                    "rejected_2s": sum(rejected),
                    "last_reject": safety.last_reject if any(rejected) else "",
                    "gc_max_ms": gc_pauses.take(),
                    "error": error,
                }
                level = {"FAULT": "error", "ESTOP": "error", "RELEASED": "warn"}.get(
                    safety.mode, "warn" if any(rejected) else "ok"
                )
                _send(node, "status", status.make(fields, level, now))
    finally:
        bus.close()


def _controller(node, controller: Controller):
    follower = follower_target = None
    status = StatusReporter(Publisher(controller.name), "controller")
    last_intent_ns = 0
    commands: deque[int] = deque(
        maxlen=1000
    )  # send times; command_hz counts the last second
    timeout_ns = int(controller.cfg.get("input_timeout_ms", 150) * 1e6)
    while True:
        event_id, msg = _event(node)
        if _quit(event_id, msg):
            return
        if event_id == "robot" and msg is not None:
            follower, follower_target = (
                msg.payload["positions"],
                msg.payload.get("target"),
            )
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


def _policy(node, controller: PolicyController):
    """Infer and send commands on the node's timer while an episode runs.

    `ROBOLOOM_POLICY` ("module:callable") and `ROBOLOOM_POLICY_KWARGS` (JSON) override the
    configured policy, so `roboloom infer --policy` needs no edited YAML."""
    status = StatusReporter(Publisher(controller.name), "controller")
    kwargs = os.environ.get("ROBOLOOM_POLICY_KWARGS")
    try:
        controller.load(
            os.environ.get("ROBOLOOM_POLICY") or None,
            json.loads(kwargs) if kwargs else None,
        )
    except Exception as exc:  # noqa: BLE001 - shown on the operator screen; start refused
        controller.state, controller.error = "failed", f"loading the policy: {exc}"
    commands: deque[int] = deque(
        maxlen=1000
    )  # send times; command_hz counts the last second
    warmed = False
    while True:
        event_id, msg = _event(node)
        if _quit(event_id, msg):
            return
        if event_id == "robot" and msg is not None:
            controller.observe(controller.robot.name, msg)
            if not warmed:
                # The first message on a dora connection stalls the receiving robot loop
                # about 130 ms (measured in mock). Send it now, while the robot is not
                # armed and ignores commands, instead of at the start of the first episode.
                _send(
                    node,
                    "command",
                    controller.command(
                        list(msg.payload["positions"]), time.monotonic_ns()
                    ),
                )
                warmed = True
        elif (
            event_id is not None and event_id.startswith("observe_") and msg is not None
        ):
            controller.observe(event_id.removeprefix("observe_"), msg)
        elif event_id == "session" and msg is not None and controller.state != "failed":
            command = msg.payload["command"]
            if command == "start":
                controller.start(msg.payload.get("task", ""))
            elif command in ("stop", "discard", "estop", "release"):
                controller.stop()
        elif event_id == "tick":
            try:
                command = controller.tick()
            except Exception as exc:  # noqa: BLE001 - a bad policy output stops the episode
                controller.stop()
                controller.state, controller.error = "failed", str(exc)
                command = None
            if command is not None:
                _send(node, "command", command)
                commands.append(time.monotonic_ns())
        now = time.monotonic_ns()
        if status.due(now):
            fields = controller.status()
            fields["command_hz"] = len([t for t in commands if now - t < 1e9])
            level = (
                "error"
                if controller.state == "failed"
                else "ok"
                if controller.state in ("ready", "running")
                else "warn"
            )
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

    def save(metrics: dict, ident: object) -> None:
        try:
            done.put(
                {
                    "command": "save",
                    "id": ident,
                    "saved_frames": writer.save(),
                    "episodes": writer.dataset.num_episodes,
                    "metrics": metrics,
                }
            )
        except Exception as exc:  # noqa: BLE001 - report session failure to operator
            done.put({"command": "save", "id": ident, "error": str(exc)})

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
                state = (
                    "saving"
                    if saving is not None
                    else "recording"
                    if writer.active
                    else "stopped"
                    if writer.stopped
                    else "idle"
                )
                fields = {
                    "state": state,
                    "task": writer.task if state != "idle" else "",
                    "rows": writer.written,
                    "elapsed_s": round((now - writer.t0_ns) / 1e9, 1)
                    if writer.active
                    else None,
                    "missing": {k: v for k, v in writer.missing.items() if v},
                    "episodes": writer.dataset.num_episodes,
                }
                level = (
                    "warn" if any(writer.missing.values()) and writer.active else "ok"
                )
                _send(node, "status", status.make(fields, level, now))
            if event_id in writer.samples and msg is not None:
                writer.ingest(event_id, msg)
                if event_id == cfg.robot.name and msg.payload.get("mode") != robot_mode:
                    robot_mode = msg.payload.get("mode")
                    _send(
                        node,
                        "report",
                        p.make(
                            "report",
                            {
                                "robot_mode": robot_mode,
                                "reason": msg.payload.get("reason", ""),
                            },
                        ),
                    )
            elif event_id == "session" and msg is not None:
                command = msg.payload["command"]
                ident = msg.payload.get("id")
                ack: dict | None = None  # answers a Session waiting on this command
                try:
                    if saving is not None and command in ("start", "save", "discard"):
                        raise RuntimeError(
                            "the previous episode is still being saved; retry shortly"
                        )
                    if command == "start":
                        writer.start(msg.payload["task"])
                        ack = {"task": writer.task}
                    elif command == "stop":
                        writer.stop()
                        ack = {"metrics": writer.metrics()}
                    elif command == "save":
                        if not writer.stopped:
                            raise RuntimeError("stop the episode first")
                        saving = threading.Thread(
                            target=save,
                            args=(writer.metrics(), ident),
                            name="save-episode",
                        )
                        saving.start()
                    elif command == "discard":
                        writer.discard()
                        ack = {}
                    elif command == "quit":
                        if saving is not None:
                            saving.join()
                        while not done.empty():
                            _send(node, "report", p.make("report", done.get()))
                        return
                except Exception as exc:  # noqa: BLE001 - report session failure to operator
                    _send(
                        node,
                        "report",
                        p.make(
                            "report",
                            {"command": command, "id": ident, "error": str(exc)},
                        ),
                    )
                else:
                    if ack is not None:
                        _send(
                            node,
                            "report",
                            p.make(
                                "report",
                                {"command": command, "id": ident, "ok": True, **ack},
                            ),
                        )
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
        controller = cfg.controllers[name]
        if isinstance(controller, PolicyController):
            _policy(node, controller)
        else:
            _controller(node, controller)
    elif name in cfg.inputs:
        _source(node, cfg.inputs[name], cfg, "input")
    elif name in cfg.sensors:
        _source(node, cfg.sensors[name], cfg, "sensor")
    else:
        raise SystemExit(f"unknown node {name!r}")


if __name__ == "__main__":
    main()
