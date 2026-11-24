"""The viewer node: the live observations in Rerun.

The loop keeps the newest envelope of every recorded stream and the followers'
actions, and redraws on its own timer; every input is `latest` (queue_size 1,
drop_oldest), so the view never holds anything back. What is drawn is what the
recorder would record of the sources that have sent something (`observation_frame`),
plus the action when every follower sent a valid one, and each stream's capture age.

Rerun and LeRobot are imported inside the functions only: roboloom imports without
the viz extra. A failure of the view is reported in the status, never raised into
the dataflow.
"""

from __future__ import annotations

import os
import time

import numpy as np

from ..config import RobotConfig
from ..core.protocol import Envelope, Publisher
from ..core.status import StatusReporter
from ..recording import action_stream
from ..recording.schema import observation_frame
from .events import _events, _quit, _send

SESSION_COMMANDS = ("start", "stop", "save", "discard")  # logged to session/events


def start(cfg: RobotConfig) -> None:
    """Open the Rerun session the settings name: a server at ip:port (also saving to
    `save` when given), a .rrd file alone (headless: tests, later review), or a viewer
    window on this machine. Nothing is opened when the viewer is off."""
    settings = cfg.viewer
    if settings is None:
        return
    import rerun as rr
    from lerobot.utils.rerun_visualization import init_rerun

    session = f"roboloom {cfg.robot}"
    ip, port, save = settings["ip"], settings["port"], settings["save"]
    if ip is not None:
        os.environ["LEROBOT_RERUN_MEMORY_LIMIT"] = settings["memory_limit"]
        init_rerun(session, ip, port)
        if save is not None:
            rr.set_sinks(
                rr.GrpcSink(f"rerun+http://{ip}:{port}/proxy"), rr.FileSink(save)
            )
    elif save is not None:
        rr.init(session)
        rr.save(save)
    else:
        os.environ["LEROBOT_RERUN_MEMORY_LIMIT"] = settings["memory_limit"]
        init_rerun(session)


def _target(settings: dict | None) -> str | None:
    """Where the view goes, for the status: the server, the file, or a local window."""
    if settings is None:
        return None
    if settings["ip"] is not None:
        return f"{settings['ip']}:{settings['port']}"
    if settings["save"] is not None:
        return settings["save"]
    return "spawn"


def draw(latest: dict[str, Envelope], cfg: RobotConfig) -> None:
    """Log the newest envelopes to Rerun: the observation of the sources that have
    sent something, one action per follower (`action.<follower>`) only when every
    follower sent a valid one, and each stream's capture age. A tick without samples
    logs nothing; an observation that cannot be built yet is left out, not fatal."""
    settings = cfg.viewer
    if settings is None:
        return
    import rerun as rr
    from lerobot.utils.rerun_visualization import log_rerun_data

    rr.set_time("roboloom", timestamp=time.time())
    sources = {n: s for n, s in cfg.sources.items() if n in latest}
    msgs = {n: latest[n] for n in sources}
    try:
        obs: dict | None = dict(observation_frame(sources, msgs, cfg.dataset_fps))
    except (ValueError, KeyError, TypeError):
        obs = None  # a joined feature cannot be built yet: no observation this tick
    action = None
    parts: dict = {}
    for name, follower in cfg.followers.items():
        msg = latest.get(action_stream(name))
        if msg is None or not msg.payload.get("valid"):
            parts = {}
            break
        positions = msg.payload["positions"]
        if len(positions) != len(follower.joint_names):
            parts = {}
            break
        parts[name] = np.asarray(positions, dtype=np.float32)
    action = parts or None
    log_rerun_data(
        observation=obs, action=action, compress_images=settings["compress_images"]
    )
    # Envelope timestamps are this host's time.monotonic_ns() (core.protocol)
    now = time.monotonic_ns()
    for name, msg in latest.items():
        age_ms = (now - msg.t_capture_ns) / 1e6
        rr.log(f"meta/{name}/capture_age_ms", rr.Scalars(age_ms))


def _session_event(msg: Envelope) -> None:
    """The episode lifecycle in the view's text panel."""
    import rerun as rr

    command = msg.payload.get("command")
    if command in SESSION_COMMANDS:
        task = msg.payload.get("task", "")
        rr.log("session/events", rr.TextLog(f"{command} {task}".strip()))


def run(node, cfg: RobotConfig) -> None:
    """The viewer loop: the newest envelope per input, a redraw on every tick, and
    an end on the session's quit. Status every ~0.5 s, as the recorder reports. A
    failed start keeps consuming events (dora must not back up) without drawing; a
    failed draw is counted and reported until a later draw succeeds, and the loop
    goes on."""
    status = StatusReporter(Publisher("viewer"), "viewer", period_s=0.5)
    latest: dict[str, Envelope] = {}
    drawn = errors = 0
    state, level, note = "viewing", "ok", ""
    target = _target(cfg.viewer)
    failed = False
    try:
        start(cfg)
    except Exception as exc:  # noqa: BLE001 - the view must never stop the dataflow
        failed = True
        state, level, note = "failed", "error", str(exc)
    try:
        while True:
            batch = _events(node)
            now = time.monotonic_ns()
            if status.due(now):
                fields = {
                    "state": state,
                    "streams": len(latest),
                    "drawn": drawn,
                    "errors": errors,
                    "target": target,
                }
                if note:
                    fields["error"] = note
                _send(node, "status", status.make(fields, level, now))
            for event_id, msg in batch:
                if _quit(event_id, msg):
                    return
                if event_id == "tick":
                    if not failed:
                        try:
                            draw(latest, cfg)
                            drawn += 1
                            if level == "warn":  # a later draw succeeded
                                level, note = "ok", ""
                        except Exception as exc:  # noqa: BLE001 - report, go on
                            errors += 1
                            level, note = "warn", str(exc)
                elif event_id == "session" and msg is not None:
                    if cfg.viewer is not None and not failed:
                        try:
                            _session_event(msg)
                        except Exception as exc:  # noqa: BLE001 - report, go on
                            errors += 1
                            level, note = "warn", str(exc)
                elif event_id is not None and msg is not None:
                    latest[event_id] = msg
    finally:
        if cfg.viewer is not None:
            try:
                from lerobot.utils.rerun_visualization import shutdown_rerun

                shutdown_rerun()
            except Exception:  # noqa: BLE001, S110 - the dataflow ends regardless
                pass
