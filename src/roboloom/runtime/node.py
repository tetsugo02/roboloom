#!/usr/bin/env python3
"""Executable dora node. The node id selects its role from the robot's configuration."""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from collections import deque
from collections.abc import Mapping
from pathlib import Path

from roboloom.config import RobotConfig, env_options, parse_config, read_config
from roboloom.control.trace import FollowerTrace
from roboloom.controllers.base import Controller, FollowerView
from roboloom.controllers.policy import PolicyController
from roboloom.core.protocol import Envelope, Publisher
from roboloom.core.source import Source
from roboloom.core.status import GcPauses, StatusReporter
from roboloom.estimators.base import Estimate, Estimator
from roboloom.recording import ACTION, EpisodeRecorder
from roboloom.robots.base import Follower
from roboloom.robots.safety import FollowerSafety

COMMANDS = ("start", "stop", "save", "discard", "estop", "release", "home", "quit")
from roboloom.runtime.flow import STATE_PREFIX, STATUS_SUFFIX, command_output
from roboloom.trackers.base import Tracker


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


def start_warning(cfg: RobotConfig, latest: dict[str, dict], now_ns: int) -> str | None:
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
        if state == "failed":  # e.g. the policy did not load: waiting does not help
            return f"{name}: controller failed: {fields.get('error') or 'see its log'}"
        if state not in READY:
            return f"{name}: controller is {state}; wait until ready, then retry start"
        controller = cfg.controllers[name]
        pair = [
            *controller.followers,
            *([controller.source.name] if controller.source else []),
        ]
        for node in pair:
            moving = latest.get(node, {}).get("fields", {})
            if moving.get("home_state") in ("moving", "settling"):
                return (
                    f"{node} is still moving home ({moving.get('home')}); "
                    "wait, then retry start"
                )
            if node in cfg.followers and moving.get("home_state") == "short":
                return f"{node}: {home_short(moving)}"

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


def home_short(fields: dict) -> str:
    """Why a follower's home move ended out of tolerance, and what to do."""
    return (
        f"did not reach home {fields.get('home')}: {fields.get('home_joint')} is "
        f"{fields.get('home_diff')} from the pose (tolerance "
        f"{fields.get('home_tolerance')}); move home again, or support the arm / "
        "raise home.tolerance"
    )


def home_warning(cfg: RobotConfig, latest: dict[str, dict], now_ns: int) -> str | None:
    """Why `home` may not run now (the robot would move during an episode), or None."""
    if not any(c.homes for c in cfg.controllers.values()):
        return "no controller has a home pose (home: in the controller YAML)"
    recorder = latest.get("recorder", {}).get("fields", {})
    if recorder.get("state") == "recording":
        return "stop the episode before moving home"
    for name in cfg.followers:
        fields = latest.get(name, {}).get("fields", {})
        if fields.get("armed"):
            return f"{name} is following; stop it before moving home"
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


def _session(node, cfg: RobotConfig):
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
                if cmd in ("start", "home"):
                    check = start_warning if cmd == "start" else home_warning
                    warning = check(cfg, latest, time.monotonic_ns())
                    if warning is not None:
                        report({**request, "warning": warning})
                        continue
                _send(node, "control", p.make("session", request))
                if cmd == "home":  # progress shows in the robot and leader status
                    report({**request, "ok": True})
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
                            "config": cfg.path,
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


def _source(node, source: Source, cfg: RobotConfig, role: str):
    """Inputs and sensors: read the device on every tick and publish its sample."""
    reader = source.open(cfg.mock, cfg.dataset_fps)
    set_home = getattr(reader, "set_home", None)
    for pair in cfg.controllers.values():  # the pair this input leads, if it has a home
        home = getattr(pair, "home", None)  # a leader moves home with its follower
        leader_pose = getattr(pair, "leader_pose", None)
        if set_home is not None and pair.source is source and home and leader_pose:
            set_home(leader_pose(home.target(pair.follower.joint_names)), home)
    log_dir = os.environ.get("ROBOLOOM_LOG_DIR")
    start_trace = getattr(reader, "start_trace", None)
    if log_dir and start_trace is not None:
        start_trace(Path(log_dir) / f"{source.name}_trace.npz")
    extra = getattr(reader, "status", None)
    p = Publisher(source.name)
    status = StatusReporter(Publisher(source.name), role)
    on_session = getattr(reader, "on_session", None)
    on_feedback = getattr(reader, "on_feedback", None)
    on_tracker = getattr(reader, "on_tracker", None)
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
            if event_id == "feedback" and msg is not None:
                if on_feedback is not None:
                    on_feedback(msg)
                continue
            if event_id == "tracker" and msg is not None:
                if on_tracker is not None:
                    on_tracker(msg)
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


def _tracker(node, tracker: Tracker, cfg: RobotConfig):
    """A tracking system: publish every tracked pose on each tick for the inputs that
    hold its objects (`roboloom.trackers`)."""
    reader = tracker.open(cfg.mock)
    p = Publisher(tracker.name)
    status = StatusReporter(Publisher(tracker.name), "tracker")
    gc_pauses = GcPauses()
    sent: deque[int] = deque(maxlen=60)
    work: deque[float] = deque(maxlen=60)  # ms in read()
    try:
        while True:
            event_id, msg = _event(node)
            if _quit(event_id, msg):
                return
            if event_id == "tick":
                began = time.perf_counter()
                poses = reader.read()
                work.append((time.perf_counter() - began) * 1e3)
                _send(node, "poses", p.make(tracker.kind, tracker.encode(poses)))
                sent.append(time.monotonic_ns())
            now = time.monotonic_ns()
            if status.due(now):
                rate = (
                    (len(sent) - 1) / ((sent[-1] - sent[0]) / 1e9)
                    if len(sent) > 1 and sent[-1] > sent[0]
                    else 0.0
                )
                fields = {
                    "rate_hz": round(rate, 1),
                    **_work_fields(work),
                    "gc_max_ms": gc_pauses.take(),
                    **reader.status(),
                }
                level = "error" if fields.get("error") else "ok"
                _send(node, "status", status.make(fields, level, now))
    finally:
        reader.close()


def _work_fields(work: deque[float]) -> dict:
    """Time one tick spends in the device (bus I/O and control laws): the headroom left
    under the period tells how far `control_hz` / `poll_hz` can go."""
    if not work:
        return {"work_ms": None, "work_max_ms": None}
    return {"work_ms": round(work[-1], 1), "work_max_ms": round(max(work), 1)}


def _home_follower(safety: FollowerSafety, robot: Follower, cfg: RobotConfig) -> str:
    """Start the move to the controller's saved pose; the error text, or ""."""
    spec = cfg.controller_for(robot.name).homes.get(robot.name)
    if spec is None:
        return ""  # this follower has no home pose; it stays where it is
    try:
        safety.home(
            spec.target(robot.joint_names),
            spec.max_speed,
            spec.pose.name,
            tolerance=spec.tolerance,
        )
    except (RuntimeError, ValueError) as exc:
        return str(exc)
    return ""


def _home_fields(safety: FollowerSafety) -> dict:
    if safety.homing is not None:
        elapsed = (time.monotonic_ns() - safety.homing_since_ns) / 1e9
        return {
            "home": safety.home_name,
            "home_state": "moving",
            "home_progress": round(safety.homing.progress(elapsed), 2),
            "home_since_ns": safety.homing_since_ns,
        }
    state = (
        "reached"
        if safety.home_reached
        else "short"
        if safety.home_short
        else "settling"
        if safety.home_settling_ns is not None
        else ""
    )
    if not state:
        return {}
    out = {
        "home": safety.home_name,
        "home_state": state,
        "home_since_ns": safety.homing_since_ns,
    }
    if safety.home_diff is not None:  # how far the measured joints are from the pose
        out["home_joint"], diff = safety.home_diff
        out["home_diff"] = round(diff, 4)
        out["home_tolerance"] = safety.home_tolerance
    return out


def _follower(node, robot: Follower, cfg: RobotConfig):
    bus = robot.open_device(cfg.mock)
    safety = FollowerSafety(robot.safety_config(), bus)
    traits = robot.traits()
    status = StatusReporter(Publisher(robot.name), "follower")
    intervals: deque[float] = deque(maxlen=int(robot.control_hz * 2))
    clamped: deque[bool] = deque(maxlen=int(robot.control_hz * 2))
    rejected: deque[bool] = deque(maxlen=int(robot.control_hz * 2))
    work: deque[float] = deque(maxlen=int(robot.control_hz * 2))  # ms in tick()
    gc_pauses = GcPauses()
    error = ""
    log_dir = os.environ.get("ROBOLOOM_LOG_DIR")
    trace = (
        FollowerTrace(
            Path(log_dir) / f"{robot.name}_trace.npz",
            robot.joint_names,
            FollowerSafety.MODES,
        )
        if log_dir
        else None
    )
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
                elif command == "home":
                    error = _home_follower(safety, robot, cfg)
                if command == "quit":
                    return
            elif event_id == "tick":
                began = time.perf_counter()
                state, action = safety.tick()
                work.append((time.perf_counter() - began) * 1e3)
                _send(node, "state", state)
                _send(node, ACTION, action)
                if trace is not None:
                    trace.add(state.t_capture_ns, state.payload)
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
                    **_home_fields(safety),
                    "torque_off": traits.torque_off,
                    "unattended": traits.unattended,
                }
                level = {"FAULT": "error", "ESTOP": "error", "RELEASED": "warn"}.get(
                    safety.mode, "warn" if any(rejected) else "ok"
                )
                _send(node, "status", status.make(fields, level, now))
    finally:
        try:
            if trace is not None:
                trace.save()
        finally:
            bus.close()


def _controller(node, controller: Controller):
    """Step the controller on every intent once every follower it drives has reported.

    A follower that latched FAULT or ESTOP, or whose state is older than
    `follower_timeout_ms`, resets the controller: no follower of the group gets a command
    until it has re-aligned (the controller contract)."""
    views: dict[str, FollowerView] = {}
    status = StatusReporter(Publisher(controller.name), "controller")
    last_intent_ns = 0
    commands: deque[int] = deque(
        maxlen=1000
    )  # send times; command_hz counts the last second
    timeout_ns = int(controller.cfg.get("input_timeout_ms", 150) * 1e6)
    stale_ns = int(controller.cfg.get("follower_timeout_ms", 150) * 1e6)
    stopped = ""  # why the group is reset: a latched or silent follower
    while True:
        event_id, msg = _event(node)
        if _quit(event_id, msg):
            return
        now = time.monotonic_ns()
        follower = (
            event_id.removeprefix(STATE_PREFIX)
            if event_id is not None and event_id.startswith(STATE_PREFIX)
            else None
        )
        if follower in controller.followers and msg is not None:
            views[follower] = FollowerView.of(msg, now)
            if views[follower].mode in ("FAULT", "ESTOP"):
                controller.reset()
                stopped = f"{follower} {views[follower].mode}"
            elif stopped.startswith(f"{follower} "):
                stopped = ""
        elif (
            event_id == "estimate"
            and msg is not None
            and controller.feedback is not None
        ):
            following = controller.status().get("state") == "following"
            mode = views.get(controller.follower.name)
            feedback = controller.feedback.make(
                msg, mode.mode if mode else None, following
            )
            if feedback is not None:
                _send(node, "feedback", feedback)
        elif event_id == "intent" and msg is not None:
            last_intent_ns = now
            missing = [n for n in controller.followers if n not in views]
            silent = [n for n, v in views.items() if now - v.t_ns > stale_ns]
            if silent and not stopped:
                controller.reset()
                stopped = f"{silent[0]} silent"
            elif not silent and stopped.endswith(" silent"):
                stopped = ""
            latched = [n for n, v in views.items() if v.mode in ("FAULT", "ESTOP")]
            if not missing and not silent and not latched:
                sent = controller.update(msg, views)
                for name, command in sent.items():
                    _send(node, command_output(name), command)
                if sent:
                    commands.append(time.monotonic_ns())
        if status.due(now):
            fields = controller.status()
            if now - last_intent_ns > timeout_ns:
                fields["state"] = "input_stale" if last_intent_ns else "waiting_input"
            waiting = [
                n
                for n in controller.followers
                if n not in views or now - views[n].t_ns > stale_ns
            ]
            if waiting:
                fields["waiting_state"] = ", ".join(waiting)
            if stopped:
                fields["stopped_by"] = stopped
            recent = [t for t in commands if now - t < 1e9]
            fields["command_hz"] = len(recent)
            level = "ok" if fields.get("state") == "following" else "warn"
            _send(node, "status", status.make(fields, level, now))


def _estimator(node, estimator: Estimator):
    """Estimate the follower's external effort from each state it publishes."""
    p = Publisher(estimator.name)
    status = StatusReporter(Publisher(estimator.name), "estimator")
    states: deque[int] = deque(maxlen=60)
    work: deque[float] = deque(maxlen=60)  # ms in update()
    last: Estimate | None = None
    while True:
        event_id, msg = _event(node)
        if _quit(event_id, msg):
            return
        if event_id == "follower" and msg is not None:
            began = time.perf_counter()
            last = estimator.update(msg.payload)
            work.append((time.perf_counter() - began) * 1e3)
            _send(
                node,
                "estimate",
                p.make(
                    estimator.kind,
                    estimator.encode(last, msg.t_capture_ns),
                    msg.t_capture_ns,
                ),
            )
            states.append(time.monotonic_ns())
        now = time.monotonic_ns()
        if status.due(now):
            rate = (
                (len(states) - 1) / ((states[-1] - states[0]) / 1e9)
                if len(states) > 1 and states[-1] > states[0]
                else 0.0
            )
            age_ms = (now - states[-1]) / 1e6 if states else None
            fields = {
                "rate_hz": round(rate, 1),
                "age_ms": None if age_ms is None else round(age_ms),
                "valid": last is not None and last.valid,
                "contact": last is not None and last.contact,
                # L1 norm the contact thresholds compare (estimator unit)
                "residual_l1": (
                    round(sum(abs(r) for r in last.residual), 1)
                    if last is not None and last.valid
                    else None
                ),
                **_work_fields(work),
            }
            level = "ok" if age_ms is not None and age_ms < 500 else "warn"
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
    warmed: set[str] = set()
    received: dict[str, int] = {}  # when each follower's state last arrived
    stale_ns = int(controller.cfg.get("follower_timeout_ms", 150) * 1e6)
    stopped = ""  # why the running episode was stopped: a silent follower
    while True:
        event_id, msg = _event(node)
        if _quit(event_id, msg):
            return
        follower = (
            event_id.removeprefix(STATE_PREFIX)
            if event_id is not None and event_id.startswith(STATE_PREFIX)
            else None
        )
        if follower in controller.followers and msg is not None:
            received[follower] = time.monotonic_ns()
            controller.observe(follower, msg)
            if follower not in warmed:
                # The first message on a dora connection stalls the receiving follower
                # loop about 130 ms (measured in mock). Send it now, while the follower
                # is not armed and ignores commands, not at the first episode's start.
                _send(
                    node,
                    command_output(follower),
                    controller.command(
                        follower, list(msg.payload["positions"]), time.monotonic_ns()
                    ),
                )
                warmed.add(follower)
        elif (
            event_id is not None and event_id.startswith("observe_") and msg is not None
        ):
            controller.observe(event_id.removeprefix("observe_"), msg)
        elif event_id == "session" and msg is not None and controller.state != "failed":
            command = msg.payload["command"]
            if command == "start":
                controller.start(msg.payload.get("task", ""))
                stopped = ""
            elif command in ("stop", "discard", "estop", "release"):
                controller.stop()
        elif event_id == "tick":
            now = time.monotonic_ns()
            silent = [
                n
                for n in controller.followers
                if n in received and now - received[n] > stale_ns
            ]
            if silent and controller.running:
                # a frozen state would make the policy act on a robot that is not there
                controller.stop()
                stopped = f"{silent[0]} silent"
            try:
                sent = controller.tick()
            except Exception as exc:  # noqa: BLE001 - a bad policy output stops the episode
                controller.stop()
                controller.state, controller.error = "failed", str(exc)
                sent = {}
            for name, command in sent.items():
                _send(node, command_output(name), command)
            if sent:
                commands.append(time.monotonic_ns())
        now = time.monotonic_ns()
        if status.due(now):
            fields = controller.status()
            fields["command_hz"] = len([t for t in commands if now - t < 1e9])
            if stopped:
                fields["stopped_by"] = stopped
            level = (
                "error"
                if controller.state == "failed"
                else "ok"
                if controller.state in ("ready", "running")
                else "warn"
            )
            _send(node, "status", status.make(fields, level, now))


def _recorder(node, cfg: RobotConfig):
    """Records episodes. `save` (video encoding) runs on a worker thread so this loop keeps
    draining dora events; otherwise queued frames exceed dora's per-reply size limit and are lost."""
    p = Publisher("recorder")
    writer = EpisodeRecorder(cfg, **cfg.recorder)
    writer.open_dataset()  # creating/resuming takes ~1 s; never inside an episode
    follower_modes: dict[str, str | None] = {}
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
                    # rows in which a follower sent no command
                    "no_action": {k: v for k, v in writer.action_missing.items() if v},
                    "episodes": writer.dataset.num_episodes,
                }
                level = (
                    "warn" if any(writer.missing.values()) and writer.active else "ok"
                )
                _send(node, "status", status.make(fields, level, now))
            if event_id in writer.samples and msg is not None:
                writer.ingest(event_id, msg)
                if event_id in cfg.followers and msg.payload.get(
                    "mode"
                ) != follower_modes.get(event_id):
                    follower_modes[event_id] = msg.payload.get("mode")
                    _send(
                        node,
                        "report",
                        p.make(
                            "report",
                            {
                                "follower": event_id,
                                "follower_mode": follower_modes[event_id],
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


def config_from_env(path: str, env: Mapping[str, str]) -> RobotConfig:
    """The configuration as the launching process chose it (`session.config_env`)."""
    mode = env.get("ROBOLOOM_MODE")
    tree = read_config(
        path,
        options=env_options(env.get("ROBOLOOM_OPTIONS")),
        mock=None if mode is None else mode == "mock",
        sensors=json.loads(env["ROBOLOOM_SENSORS"])
        if "ROBOLOOM_SENSORS" in env
        else None,
    )
    for controller, selected in json.loads(env.get("ROBOLOOM_OBSERVE", "{}")).items():
        tree["controllers"][controller]["observe"] = selected
    if "ROBOLOOM_VIDEO_CODEC" in env:  # the parent's choice, None included
        tree["recorder"]["video_codec"] = json.loads(env["ROBOLOOM_VIDEO_CODEC"])
    return parse_config(tree)


def main() -> None:
    from dora import Node

    name, path = sys.argv[1:3]
    cfg = config_from_env(path, os.environ)
    node = Node()
    if name == "session":
        _session(node, cfg)
    elif name == "recorder":
        _recorder(node, cfg)
    elif name in cfg.followers:
        _follower(node, cfg.followers[name], cfg)
    elif name in cfg.controllers:
        controller = cfg.controllers[name]
        if isinstance(controller, PolicyController):
            _policy(node, controller)
        else:
            _controller(node, controller)
    elif name in cfg.trackers:
        _tracker(node, cfg.trackers[name], cfg)
    elif name in cfg.inputs:
        _source(node, cfg.inputs[name], cfg, "input")
    elif name in cfg.sensors:
        _source(node, cfg.sensors[name], cfg, "sensor")
    elif name in cfg.estimators:
        _estimator(node, cfg.estimators[name])
    else:
        raise SystemExit(f"unknown node {name!r}")


if __name__ == "__main__":
    main()
