"""The viewer node: the live observations in Rerun.

The loop keeps the newest envelope of every recorded stream and the followers'
actions, and redraws on its own timer; every input is `latest` (queue_size 1,
drop_oldest), so the view never holds anything back. What is drawn is what the
recorder would record of the sources that have sent something (`observation_frame`),
plus the action when every follower sent a valid one, and each stream's capture age.

Rerun is imported inside the functions only: roboloom imports without the viz
extra. A failure of the view is reported in the status and the dataflow goes on.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from contextlib import suppress
from numbers import Real
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import numpy as np

from ..config import RobotConfig
from ..core.protocol import Envelope, Publisher
from ..core.status import StatusReporter
from ..recording import action_stream
from ..recording.schema import observation_frame
from .events import _events, _quit, _send

SESSION_COMMANDS = ("start", "stop", "save", "discard")  # logged to session/events
LOOPBACK = "127.0.0.1"
DEFAULT_GRPC_PORT = 9876
_blueprint_paths: tuple[set[str], set[str], set[str]] | None = None


def _rerun_cli() -> str | None:
    executable = Path(sys.executable).with_name("rerun")
    if executable.is_file() and os.access(executable, os.X_OK):
        return str(executable)
    return shutil.which("rerun")


def _listening(port: int) -> bool:
    try:
        with socket.create_connection((LOOPBACK, port), timeout=0.1):
            return True
    except OSError:
        return False


def _ensure_server(
    port: int, web_port: int, bind: str, memory_limit: str, cors_origins: list[str]
) -> int | None:
    """Return the PID of a new detached server, or reuse a listening server."""
    if _listening(port):
        return None
    if port == web_port or _listening(web_port):
        raise RuntimeError(
            f"Rerun web port {web_port} is unavailable (gRPC port {port}); "
            "choose a free web_port distinct from port"
        )
    executable = _rerun_cli()
    if executable is None:
        raise RuntimeError("Rerun CLI 'rerun' was not found; install the viz extra")

    command = [
        executable,
        "--serve-web",
        "--port",
        str(port),
        "--web-viewer-port",
        str(web_port),
        "--bind",
        bind,
        "--server-memory-limit",
        memory_limit,
    ]
    for origin in cors_origins:
        command.extend(("--cors-allow-origin", origin))
    log_dir = os.environ.get("ROBOLOOM_LOG_DIR")
    log_path = Path(log_dir) / "rerun-server.log" if log_dir else Path(os.devnull)
    with log_path.open("ab") as output:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and process.poll() is None:
            if _listening(port) and _listening(web_port):
                break
            time.sleep(0.05)
        else:
            reason = (
                f"exited with code {process.returncode}"
                if process.returncode is not None
                else "timed out waiting for listeners"
            )
            raise RuntimeError(
                f"Rerun server did not start on gRPC port {port} and web port {web_port} "
                f"(bind {bind}, {reason}); server output: {log_path}"
            )
    except BaseException:
        # The CLI launcher can have a child. Stop the whole new session on failure.
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        raise
    # Reap the child if it exits while the node is alive.
    threading.Thread(target=process.wait, daemon=True).start()
    return process.pid


def _proxy(host: str, port: int) -> str:
    return f"rerun+http://{host}:{port}/proxy"


def _web_url(host: str, port: int, web_port: int) -> str:
    if ":" in host and not host.startswith("["):  # an IPv6 literal in a URL
        host = f"[{host}]"
    return f"http://{host}:{web_port}/?{urlencode({'url': _proxy(host, port)})}"


def _open_browser(url: str) -> str | None:
    try:
        if webbrowser.open(url):
            return None
    except Exception as exc:  # noqa: BLE001 - opening a browser is optional
        return f"Could not open the Rerun web viewer: {exc}"
    return "Could not open the Rerun web viewer"


def start(cfg: RobotConfig) -> tuple[str | None, str | None, str | None]:
    """Open the Rerun sinks and return the shareable and localhost URLs and browser warning."""
    global _blueprint_paths

    settings = cfg.viewer
    if settings is None:
        return None, None, None
    import rerun as rr

    _blueprint_paths = None
    rr.init(f"roboloom {cfg.robot}")
    ip, port, save = settings["ip"], settings["port"], settings["save"]
    url = local_url = browser_url = None
    sinks: list[rr.GrpcSink | rr.FileSink] = []
    if ip is not None:
        sinks.append(rr.GrpcSink(_proxy(ip, port)))
    elif settings["serve"]:
        port = port or DEFAULT_GRPC_PORT
        web_port = settings["web_port"]
        bind = settings["bind"]
        url = _web_url(settings["public_host"] or socket.gethostname(), port, web_port)
        authority = urlsplit(url).netloc.lower()
        if web_port == 80:  # Browsers omit the default HTTP port from Origin.
            authority = authority.removesuffix(":80")
        cors_origins = [f"http://{authority}", *settings["cors_allow_origins"]]
        pid = _ensure_server(
            port, web_port, bind, settings["server_memory_limit"], cors_origins
        )
        sinks.append(rr.GrpcSink(_proxy(LOOPBACK, port)))
        local_url = _web_url("localhost", port, web_port)
        browser_url = local_url if bind == LOOPBACK else url
        server = f"PID {pid}" if pid is not None else "reused server"
        print(
            f"Rerun web viewer ({server}): {url}\nRerun localhost: {local_url}",
            file=sys.stderr,
        )
    if save is not None:
        sinks.append(rr.FileSink(save))
    if sinks:
        rr.set_sinks(*sinks)
    else:
        rr.spawn(memory_limit=settings["memory_limit"])
    warning = (
        _open_browser(browser_url)
        if browser_url is not None and settings["open_browser"]
        else None
    )
    return url, local_url, warning


def _target(settings: dict | None) -> str | None:
    """Where the view goes, for the status: the server, the file, or a local window."""
    if settings is None:
        return None
    if settings["ip"] is not None:
        return f"{settings['ip']}:{settings['port']}"
    if settings["serve"]:
        return f"{LOOPBACK}:{settings['port'] or DEFAULT_GRPC_PORT}"
    if settings["save"] is not None:
        return settings["save"]
    return "spawn"


def _log_image(path: str, array: np.ndarray, compress: bool) -> None:
    import rerun as rr

    if (
        array.ndim == 3
        and array.shape[0] in (1, 3, 4)
        and array.shape[-1] not in (1, 3, 4)
    ):
        array = np.moveaxis(array, 0, -1)
    image: rr.DepthImage | rr.EncodedImage | rr.Image
    if array.ndim == 2 or array.shape[-1] == 1:
        # Match LeRobot's depth units: float samples in meters, integers in mm.
        meter = 1.0 if np.issubdtype(array.dtype, np.floating) else 1000.0
        image = rr.DepthImage(
            array, meter=meter, colormap=rr.components.Colormap.Viridis
        )
    else:
        rgb = rr.Image(array)
        image = rgb.compress() if compress else rgb
    rr.log(path, image)


def _send_blueprint(
    images: set[str], observations: set[str], actions: set[str]
) -> None:
    global _blueprint_paths

    known_images, known_observations, known_actions = _blueprint_paths or (
        set(),
        set(),
        set(),
    )
    paths = (
        known_images | images,
        known_observations | observations,
        known_actions | actions,
    )
    if paths == _blueprint_paths:
        return
    import rerun as rr
    import rerun.blueprint as rrb

    images, observations, actions = paths
    rr.send_blueprint(
        rrb.Blueprint(
            rrb.Grid(
                *(
                    rrb.Spatial2DView(origin=f"/{path}", name=path)
                    for path in sorted(images)
                ),
                rrb.TimeSeriesView(name="observation", contents=sorted(observations)),
                rrb.TimeSeriesView(name="action", contents=sorted(actions)),
                rrb.TimeSeriesView(name="capture age", contents="/meta/**"),
                rrb.TextLogView(origin="/session/events", name="session/events"),
            ),
            rrb.TimePanel(timeline="roboloom"),
        )
    )
    _blueprint_paths = paths


def draw(latest: dict[str, Envelope], cfg: RobotConfig) -> None:
    """Log the newest envelopes to Rerun: the observation of the sources that have
    sent something, one action per follower (`action.<follower>`) only when every
    follower sent a valid one, and each stream's capture age. A tick without samples
    logs no samples; an observation that cannot be built yet is left out."""
    settings = cfg.viewer
    if settings is None:
        return
    import rerun as rr

    rr.set_time("roboloom", timestamp=time.time())
    sources = {n: s for n, s in cfg.sources.items() if n in latest}
    msgs = {n: latest[n] for n in sources}
    try:
        obs = observation_frame(sources, msgs, cfg.dataset_fps)
    except (ValueError, KeyError, TypeError):
        obs = {}  # a joined feature cannot be built yet: no observation this tick
    images: set[str] = set()
    observations: set[str] = set()
    for key, value in obs.items():
        path = key if key.startswith("observation.") else f"observation.{key}"
        if isinstance(value, np.ndarray) and value.ndim > 1:
            _log_image(path, value, settings["compress_images"])
            images.add(path)
        elif isinstance(value, np.ndarray):
            rr.log(path, rr.Scalars(value.reshape(-1).astype(float)))
            observations.add(path)
        elif isinstance(value, (Real, np.integer, np.floating)):
            rr.log(path, rr.Scalars(float(value)))
            observations.add(path)

    parts: dict[str, np.ndarray] = {}
    for name, follower in cfg.followers.items():
        msg = latest.get(action_stream(name))
        if msg is None or not msg.payload.get("valid"):
            parts.clear()
            break
        positions = msg.payload["positions"]
        if len(positions) != len(follower.joint_names):
            parts.clear()
            break
        path = name if name.startswith("action.") else f"action.{name}"
        parts[path] = np.asarray(positions, dtype=np.float32)
    for path, positions in parts.items():
        rr.log(path, rr.Scalars(positions.reshape(-1)))
    # Envelope timestamps are this host's time.monotonic_ns() (core.protocol)
    now = time.monotonic_ns()
    for name, msg in latest.items():
        age_ms = (now - msg.t_capture_ns) / 1e6
        rr.log(f"meta/{name}/capture_age_ms", rr.Scalars(age_ms))
    _send_blueprint(images, observations, set(parts))


def _session_event(msg: Envelope) -> None:
    """The episode lifecycle in the view's text panel."""
    import rerun as rr

    command = msg.payload.get("command")
    if command in SESSION_COMMANDS:
        task = msg.payload.get("task", "")
        rr.set_time("roboloom", timestamp=time.time())
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
    url = local_url = browser_warning = None
    failed = False
    try:
        url, local_url, browser_warning = start(cfg)
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
                    "url": url,
                    "local_url": local_url,
                }
                if note:
                    fields["error"] = note
                if browser_warning:
                    fields["browser_error"] = browser_warning
                status_level = "warn" if browser_warning and level == "ok" else level
                _send(node, "status", status.make(fields, status_level, now))
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
                import rerun as rr

                rr.rerun_shutdown()
            except Exception:  # noqa: BLE001, S110 - the dataflow ends regardless
                pass
