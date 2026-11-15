"""Launch a robot's dora dataflow and direct it from Python.

The dataflow runs the control loops, sensors and recorder in their own processes; a
`Session` never runs a control loop. It sends events (start an episode with a task,
stop, save, ...) and reads the nodes' reports and status. The CLI (`run`, `record`,
`infer`) and Python scripts use this same class.

    with Session.launch("rakuda2", options=["gravity"], mock=False) as s:
        s.wait_ready()
        for _ in range(3):
            s.record(lambda info: f"pick cube #{info.index}", seconds=20)
"""

from __future__ import annotations

import itertools
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from ..config import NO_OPTIONS, RobotConfig, load_config
from ..core.traits import WORST_CASE, SafetyTraits, ending_note, precautions
from ..errors import Cancelled, ConfigError, HardwareError, RoboloomError
from ..operator import Operator
from ..recording.metrics import assess
from ..recording.video import check_video_encoding
from ..ui.client import SessionClient
from ..ui.screen import SessionScreen, wanted
from .flow import write_flow


@dataclass(frozen=True)
class _Startup:
    cancelled: threading.Event
    opened: Callable[[Session], None]


_startup: ContextVar[_Startup | None] = ContextVar("session_ui_startup", default=None)


@contextmanager
def _ui_launch(
    cancelled: threading.Event, opened: Callable[[Session], None]
) -> Iterator[None]:
    """Internal startup hook without changing the public launch signature."""
    token = _startup.set(_Startup(cancelled, opened))
    try:
        yield
    finally:
        _startup.reset(token)


class SessionError(RoboloomError):
    """The dataflow refused a command or stopped. `report` is the node's answer, when
    one caused it."""

    def __init__(self, message: str, report: dict | None = None):
        super().__init__(message)
        self.report = report or {}


@dataclass
class EpisodeInfo:
    """What a task-naming function knows about the episode it names."""

    index: int  # episode index in the dataset (episodes already saved)
    number: int  # episodes recorded by this session so far
    dataset: str  # the dataset's name, e.g. rakuda2-digit (tells the options)
    previous: list[str] = field(default_factory=list)  # tasks saved by this session


@dataclass
class EpisodeResult:
    task: str
    saved: bool
    frames: int  # rows recorded
    index: int | None = None  # dataset episode index when saved
    metrics: dict = field(default_factory=dict)  # EpisodeRecorder.metrics()
    warnings: list[str] = field(default_factory=list)  # quality limits exceeded

    @property
    def ok(self) -> bool:
        return not self.warnings


Task = str | Callable[[EpisodeInfo], str]

ANSI = re.compile(r"\x1b\[[0-9;]*m")
FAILED = ("exited with code", "exited with error")  # dora's node-failure lines
ERROR_LINE = re.compile(r"^[A-Za-z_.]*(Error|Exception): ")  # a traceback's last line


def log_dir_for(cfg: RobotConfig) -> Path:
    """Next to the configuration, so a project keeps its own logs (ignored by git).
    Named after the operation's dataset (`rakuda2-digit-...`), which tells the options."""
    name = Path(cfg.path).stem
    if name == "config":
        name = cfg.repo_id.rpartition("/")[2]
    return (
        Path(cfg.path).parent / "logs" / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}"
    ).resolve()


def _dora() -> str:
    # the venv's own dora too, when the interpreter runs without an activated venv
    dora = shutil.which("dora") or shutil.which(
        "dora", path=str(Path(sys.executable).parent)
    )
    if dora is None:
        raise ConfigError(
            "dora CLI unavailable; run from the project environment (uv run ...) "
            "after uv sync"
        )
    return dora


def validate_flow(cfg: RobotConfig, directory: Path) -> Path:
    """Write the configuration's dataflow into `directory` and check it with `dora validate`."""
    flow = write_flow(cfg, directory / "flow.yaml")
    check = subprocess.run(
        [_dora(), "validate", "--offline", str(flow)],
        capture_output=True,
        text=True,
        check=False,
    )
    if check.returncode:
        raise ConfigError(f"dora validate failed:\n{check.stdout}{check.stderr}")
    return flow


def config_env(cfg: RobotConfig) -> dict[str, str]:
    """The choices the nodes need to reload `cfg` from `cfg.path` as the parent loaded
    it (read back by `runtime.node.config_from_env`)."""
    return {
        "ROBOLOOM_OPTIONS": ",".join(cfg.options) or NO_OPTIONS,
        "ROBOLOOM_MODE": cfg.mode,
        "ROBOLOOM_SENSORS": json.dumps(list(cfg.sensors)),
        "ROBOLOOM_VIDEO_CODEC": json.dumps(cfg.recorder.get("video_codec")),
        "ROBOLOOM_OBSERVE": json.dumps(
            {
                name: controller.observes()
                for name, controller in cfg.controllers.items()
                if hasattr(controller, "observes")
            }
        ),
    }


def fifo_for(cfg: RobotConfig) -> Path:
    """The command FIFO of a running dataflow; `roboloom session` writes to it. One per
    configuration file, whatever options the run enabled (they change the dataset name)."""
    return Path(cfg.path).resolve().with_suffix(".fifo")


class Session:
    def __init__(
        self,
        cfg: RobotConfig,
        process: subprocess.Popen,
        client: SessionClient,
        log_dir: Path,
        workdir: tempfile.TemporaryDirectory,
        fifo: Path,
    ):
        self.cfg, self.process, self.client = cfg, process, client
        self.log_dir, self._workdir, self.fifo = log_dir, workdir, fifo
        self.log_path = log_dir / "dora.log"
        self._ids = itertools.count(1)
        self._closed = False
        self._cancel_local = threading.local()
        self._reports: list[dict] = []
        self._recorded: list[str] = []
        self._episode: str | None = None  # task of the episode in progress
        self._saved = 0  # dataset episodes after this session's last save
        self._lock = threading.RLock()  # the screen thread reads reports too
        self._listeners: list[Callable[[dict], None]] = []
        self.screen: SessionScreen | None = None
        self.operator: Operator | None = (
            None  # asked before an actuated leader goes limp
        )

    # -- lifecycle --------------------------------------------------------------

    @classmethod
    def launch(
        cls,
        config: str | Path | RobotConfig,
        *,
        options: Iterable[str] | None = None,
        mock: bool | None = None,
        sensors: Iterable[str] | None = None,
        observe: Iterable[str] | None = None,
        video_codec: str | None = None,
        policy: str | None = None,
        policy_kwargs: dict | None = None,
        log_dir: str | Path | None = None,
        timeout: float = 60.0,
        screen: bool | str = "auto",
        operator: Operator | None | str = "auto",
    ) -> Session:
        """Validate and start the dataflow; returns once every node reports status.

        - `options`: the launch options to enable (None: their defaults); `mock`:
          True runs mock devices, False real ones (None: the YAML's `mode`, default
          hardware). Both apply only when `config` is a path or name.
        - `sensors`, `observe`, `video_codec`: as in `load_config` (None: the YAML);
          with a `RobotConfig`, choose them in `load_config` instead.
        - `policy` ("module:callable") and `policy_kwargs` replace the policy of a
          `type: policy` controller.
        - `screen`: the node-status screen, drawn on a thread ("auto": when stdout is
          a terminal; see `roboloom.ui.screen`).
        - `operator`: asked to support the arms before closing makes an actuated leader
          go limp ("auto": a TerminalOperator when stdin is a terminal; None: no question).
        """
        if isinstance(config, RobotConfig) and (
            sensors is not None or observe is not None or video_codec is not None
        ):
            raise ConfigError(
                "select sensors, observe and video_codec in load_config before "
                "passing RobotConfig"
            )
        cfg = (
            config
            if isinstance(config, RobotConfig)
            else load_config(
                config,
                options=options,
                mock=mock,
                sensors=sensors,
                observe=observe,
                video_codec=video_codec,
            )
        )
        check_video_encoding(cfg)  # before any node opens the dataset
        if (policy or policy_kwargs) and not any(
            c.drives_all_followers for c in cfg.controllers.values()
        ):
            raise ConfigError(f"{cfg.path} has no `type: policy` controller")
        dora = _dora()
        fifo = fifo_for(cfg)
        fifo.parent.mkdir(parents=True, exist_ok=True)
        if fifo.exists():
            raise SessionError(
                f"session FIFO already exists: {fifo} (another run of this robot, "
                "or a stale file to delete)"
            )
        workdir = tempfile.TemporaryDirectory(prefix="roboloom-flow-")
        directory = Path(workdir.name)
        try:
            flow = validate_flow(cfg, directory)
            logs = Path(log_dir).resolve() if log_dir else log_dir_for(cfg)
            logs.mkdir(parents=True, exist_ok=True)
            report, status = directory / "report.jsonl", directory / "status.json"
            report.touch()
            os.mkfifo(fifo, 0o600)
        except BaseException:
            workdir.cleanup()
            raise
        env: dict[str, object] = {
            "ROBOLOOM_SESSION_FIFO": fifo,
            "ROBOLOOM_REPORT_PATH": report,
            "ROBOLOOM_STATUS_PATH": status,
            "ROBOLOOM_LOG_DIR": logs,
            **config_env(cfg),
        }
        if policy:
            env["ROBOLOOM_POLICY"] = policy
        if policy_kwargs:
            env["ROBOLOOM_POLICY_KWARGS"] = json.dumps(policy_kwargs)
        command = [dora, "run", "--log-level", "error"]
        for key, value in env.items():
            command += ["--env", f"{key}={value}"]
        try:
            with open(logs / "dora.log", "w") as out:
                # own process group: Ctrl-C reaches only this process, which sends `quit`
                process = subprocess.Popen(
                    [*command, str(flow)],
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                )
        except BaseException:
            fifo.unlink(missing_ok=True)
            workdir.cleanup()
            raise
        session = cls(
            cfg, process, SessionClient(fifo, report, status), logs, workdir, fifo
        )
        if operator == "auto":
            from ..operator import TerminalOperator

            operator = TerminalOperator() if sys.stdin.isatty() else None
        session.operator = operator if not isinstance(operator, str) else None
        try:
            startup = _startup.get()
            if startup is not None:
                session._cancel_local.event = startup.cancelled
                startup.opened(session)
            if wanted(screen):
                session.screen = SessionScreen(
                    session, f"roboloom  {Path(cfg.path).parent.name}"
                )
                session.screen.start()
            session._wait_nodes(timeout)
        except BaseException:
            session.close()
            raise
        session._cancel_local.event = None
        return session

    @property
    def alive(self) -> bool:
        return self.process.poll() is None

    @property
    def actuated(self) -> list[str]:
        """Inputs whose motors run control laws; they go limp when the session ends."""
        return [n for n, i in self.cfg.inputs.items() if getattr(i, "actuated", False)]

    @property
    def torqued(self) -> dict[str, SafetyTraits]:
        """Followers that run with torque, with their safety traits."""
        return {n: f.traits() for n, f in self.cfg.followers.items() if f.torque}

    @property
    def held(self) -> list[str]:
        """Followers that keep holding after the session unless released: torque on and
        `unattended: holds` (core.traits)."""
        return [n for n, t in self.torqued.items() if t.holds_unattended]

    @property
    def limp_at_end(self) -> dict[str, SafetyTraits]:
        """What goes, or may go, limp when the session ends without release: actuated
        inputs, and followers that do not hold unattended (or are not known to)."""
        return {
            **self._actuated_traits(),
            **{n: t for n, t in self.torqued.items() if not t.holds_unattended},
        }

    def _actuated_traits(self) -> dict[str, SafetyTraits]:
        return {
            n: getattr(i, "safety_traits", WORST_CASE)
            for n, i in self.cfg.inputs.items()
            if getattr(i, "actuated", False)
        }

    def release_note(self) -> str:
        """What the operator does before `release` turns torque off on the actuated inputs
        and the followers."""
        devices = {**self._actuated_traits(), **self.torqued}
        if not devices:
            return "nothing has torque"
        return precautions(devices) or (
            f"{', '.join(devices)} neither falls nor lets go without torque"
        )

    def close(self, timeout: float = 15.0, *, release: bool | None = None) -> None:
        """Discard an unfinished episode, stop every node and wait for the dataflow to exit.

        An actuated leader goes limp. The follower torque goes off when `release` is
        true; when it is None, the operator is asked (Enter releases, `hold` keeps the
        follower holding) and without an operator the follower keeps holding."""
        if self._closed:
            return
        self._closed = True
        try:
            if self.alive:
                try:
                    if self._episode is not None:
                        self.discard()
                except (OSError, RoboloomError):
                    pass
                if self.screen is not None:
                    self.screen.stop()
                if self.operator is not None and release is None:
                    release = self._ask_close()
                try:
                    if release and (self.torqued or self.actuated):
                        self.client.send("release")
                    self.client.send("quit")
                except OSError:
                    pass
                try:
                    self.process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid, signal.SIGTERM)
                    try:
                        self.process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(self.process.pid, signal.SIGKILL)
                        self.process.wait()
        finally:
            if self.screen is not None:
                self.screen.stop()
            self.fifo.unlink(missing_ok=True)
            self._workdir.cleanup()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # -- state ------------------------------------------------------------------

    def status(self) -> dict:
        """Latest status of every node: {name: {"role", "level", "fields", "t_ns"}}."""
        return (self.client.status() or {}).get("nodes", {})

    @property
    def episodes(self) -> int:
        """Episodes in the dataset, as the recorder last reported."""
        fields = self.status().get("recorder", {}).get("fields", {})
        # the status file lags a save by up to a few hundred ms
        return max(int(fields.get("episodes") or 0), self._saved)

    def reports(self) -> list[dict]:
        """Reports not yet returned by a wait (robot mode changes, warnings, ...)."""
        with self._lock:
            self.poll()
            out, self._reports = self._reports, []
        return out

    def listen(self, listener: Callable[[dict], None]) -> None:
        """Call `listener` with every report and session note (the screen uses this)."""
        self._listeners.append(listener)

    def poll(self) -> None:
        """Read new reports from the dataflow; safe from any thread."""
        with self._lock:
            new = self.client.new_reports()
            self._reports += new
        for report in new:
            self._tell(report)

    def note(self, text: str, level: str = "info") -> None:
        """A message from this side (e.g. quality warnings) for the listeners."""
        self._tell({"note": text, "level": level})

    def _tell(self, item: dict) -> None:
        for listener in self._listeners:
            listener(item)

    def node_errors(self) -> list[str]:
        """Error lines of failed nodes in dora.log (a node can die while dora keeps running)."""
        try:
            text = ANSI.sub("", self.log_path.read_text(errors="ignore"))
        except OSError:
            return []
        if not any(marker in text for marker in FAILED):
            return []
        return [
            line.strip()
            for line in text.splitlines()
            if any(marker in line for marker in FAILED)
            or ERROR_LINE.match(line.strip())
        ][-6:]

    @contextmanager
    def _cancellable(self, cancelled: threading.Event | None) -> Iterator[None]:
        """Internal UI hook; default Python API waits remain unchanged."""
        previous = getattr(self._cancel_local, "event", None)
        self._cancel_local.event = cancelled
        try:
            yield
        finally:
            self._cancel_local.event = previous

    def _check_cancelled(self) -> None:
        cancelled = getattr(self._cancel_local, "event", None)
        if cancelled is not None and cancelled.is_set():
            raise Cancelled("operation cancelled")

    def _check_alive(self) -> None:
        self._check_cancelled()
        if not self.alive:
            tail = self.log_path.read_text()[-2000:] if self.log_path.exists() else ""
            raise SessionError(
                f"the dataflow exited ({self.process.returncode}); log {self.log_path}:\n{tail}"
            )
        errors = self.node_errors()
        if errors:
            raise SessionError(
                "a node failed; log "
                + str(self.log_path)
                + ":\n  "
                + "\n  ".join(errors)
            )

    def _wait_nodes(self, timeout: float) -> None:
        expected = {n["id"] for n in _node_ids(self.cfg)} - {
            "session"
        }  # it writes status
        deadline = time.monotonic() + timeout
        while not expected <= set(self.status()):
            self._check_alive()
            if time.monotonic() > deadline:
                missing = sorted(expected - set(self.status()))
                raise SessionError(
                    f"nodes did not start within {timeout:g} s: {missing}"
                )
            time.sleep(0.1)

    def wait_ready(self, timeout: float = 30.0) -> None:
        """Until every controller may start an episode (e.g. the leader is aligned)."""
        from .node import start_warning

        deadline = time.monotonic() + timeout
        while True:
            self._check_alive()
            status = self.status()
            warning = start_warning(self.cfg, status, time.monotonic_ns())
            if warning is None:
                return
            failed = any(
                status.get(name, {}).get("fields", {}).get("state") == "failed"
                for name in self.cfg.controllers
            )
            if failed:  # a controller that failed does not recover by waiting
                raise SessionError(warning)
            if time.monotonic() > deadline:
                raise SessionError(f"not ready after {timeout:g} s: {warning}")
            time.sleep(0.1)

    # -- commands ---------------------------------------------------------------

    def send(self, command: str, task: str = "") -> int:
        """Send one command to every node; returns its id (echoed in the reports)."""
        self._check_alive()
        ident = next(self._ids)
        self.client.send(json.dumps({"id": ident, "command": command, "task": task}))
        return ident

    def wait_report(self, ident: int, timeout: float = 10.0) -> dict:
        """The report answering command `ident`; raises SessionError if it failed."""
        deadline = time.monotonic() + timeout
        while True:
            self._check_cancelled()
            self.poll()
            with self._lock:
                found = next((r for r in self._reports if r.get("id") == ident), None)
                if found is not None:
                    self._reports.remove(found)
            if found is not None:
                if "warning" in found or "error" in found:
                    raise SessionError(
                        f"{found.get('command')}: "
                        f"{found.get('warning') or found.get('error')}",
                        found,
                    )
                return found
            self._check_alive()
            if time.monotonic() > deadline:
                raise SessionError(f"no answer to command {ident} within {timeout:g} s")
            time.sleep(0.05)

    def start(self, task: str) -> None:
        if not task.strip():
            raise ValueError("task is required")
        self.wait_report(self.send("start", task))
        self._episode = task

    def stop(self) -> EpisodeResult:
        """End the episode's recording; the result (not yet saved) has its metrics and
        quality warnings, to decide between `save` and `discard`."""
        report = self.wait_report(self.send("stop"))
        metrics = report.get("metrics", {})
        return EpisodeResult(
            self._episode or "",
            False,
            int(metrics.get("rows", 0)),
            metrics=metrics,
            warnings=assess(metrics, self.cfg.quality),
        )

    def save(self, timeout: float = 300.0) -> EpisodeResult:
        """Write the stopped episode (video encoding can take a while). When the
        write fails the episode is dropped (SessionError); the dataset keeps the
        episodes saved before it and the next one can be recorded."""
        task = self._episode or ""
        try:
            report = self.wait_report(self.send("save"), timeout)
        except SessionError as exc:
            if exc.report.get("dropped"):  # nothing left to save or discard
                self._episode = None
            raise
        self._episode = None
        self._recorded.append(task)
        self._saved = int(report.get("episodes", 0))
        metrics = report.get("metrics", {})
        result = EpisodeResult(
            task,
            True,
            int(report.get("saved_frames", 0)),
            int(report.get("episodes", 0)) - 1,
            metrics,
            assess(metrics, self.cfg.quality),
        )
        for warning in result.warnings:
            self.note(f"episode {result.index} quality: {warning}", "warn")
        return result

    def discard(self) -> None:
        """Stop the robot and drop the episode in progress."""
        self.wait_report(self.send("discard"))
        self._episode = None

    def _ask_close(self) -> bool:
        """Tell the operator what goes limp and what to do about it (core.traits); True
        releases the followers."""
        assert self.operator is not None
        limp, held = self.limp_at_end, self.held
        if not (limp or self.torqued):
            return False
        try:
            if not self.torqued:  # only actuated inputs, which go limp anyway
                self.operator.prompt(
                    f"When the session ends, {ending_note(limp)}. Press Enter to end: "
                )
                return False
            # followers that do not hold are offered the release too: left enabled
            # without commands, nothing could turn them off safely afterwards
            keep = f"with {', '.join(held)} holding" if held else "without releasing"
            answer = self.operator.prompt(
                f"Enter ends with the torque off ({self.release_note()}); 'hold' ends "
                f"{keep}" + (f" ({ending_note(limp)})" if limp else "") + ": "
            )
        except (KeyboardInterrupt, EOFError):
            return False  # nobody confirmed supporting the arms
        return answer.strip().lower() != "hold"

    def home(self, timeout: float | None = None) -> None:
        """Move every leader-follower pair with a `home` pose there, slowly, and wait until
        both arrived (at most `timeout` s, default the YAML's `timeout_s`). Leaders go back to
        their normal laws a second after arriving. Raises SessionError when a node refused or did not
        arrive."""
        sent_ns, limit = self.begin_home()
        deadline = time.monotonic() + (timeout if timeout is not None else limit)
        while True:
            waiting = self.home_waiting(sent_ns)
            if not waiting:
                return
            if time.monotonic() > deadline:
                raise SessionError(f"home not reached: {', '.join(waiting)}")
            time.sleep(0.1)

    def begin_home(self) -> tuple[int, float]:
        """Send `home`; returns (send time in monotonic ns, the YAML's timeout in s)."""
        homes = [h for c in self.cfg.controllers.values() for h in c.homes.values()]
        if not homes:
            raise SessionError("no controller has a home pose (home: in its YAML)")
        sent_ns = time.monotonic_ns()
        self.wait_report(self.send("home"))
        return sent_ns, max(h.timeout_s for h in homes)

    def home_waiting(self, sent_ns: int) -> list[str]:
        """Nodes still moving home since `sent_ns` (empty: arrived); raises SessionError
        when one refused."""
        self._check_alive()
        status = self.status()
        waiting = []
        for c in self.cfg.controllers.values():
            if not c.homes:
                continue
            # an actuated leader moves home with its follower (node._source); a pose
            # input or an unpowered leader stays where the operator holds it
            moves = (
                c.source is not None
                and getattr(c.source, "actuated", False)
                and getattr(c, "leader_pose", None) is not None
            )
            for name in (*c.homes, *([c.source.name] if moves and c.source else [])):
                item = status.get(name, {})
                fields = item.get("fields", {})
                fresh = item.get("t_ns", 0) > sent_ns
                problem = fields.get("home_error") or (
                    fields.get("error") if name in self.cfg.followers else ""
                )
                if fresh and problem:
                    raise SessionError(f"{name}: home: {problem}")
                # A status sent after `home` but before the node handled it still shows
                # the previous move's result: count only a move that began after sent_ns.
                began = fields.get("home_since_ns", 0) >= sent_ns
                # a follower whose measured joints stayed out of home.tolerance
                if (
                    fresh
                    and began
                    and name in self.cfg.followers
                    and fields.get("home_state") == "short"
                ):
                    from .node import home_short

                    raise SessionError(f"{name}: {home_short(fields)}")
                # a leader's "short": the move ended short of the pose where friction
                # stopped a spring; the start check (alignment) decides whether that is
                # close enough
                if not (fresh and began) or fields.get("home_state") not in (
                    "reached",
                    "short",
                ):
                    waiting.append(f"{name} ({fields.get('home_state', 'waiting')})")
        return waiting

    # -- teleoperation of a policy (`teleop:` in the policy YAML) ------------------

    def teleop(self) -> None:
        """Drive the followers with the leader: before an episode (nothing is recorded)
        or during one (an intervention, recorded as `action.intervention`). Each joint
        holds until the leader reaches it, then follows; the policy's status lists the
        joints still to reach (`pickup`)."""
        self.wait_report(self.send("teleop"))

    def policy(self) -> None:
        """Hand the followers back to the policy during an episode (it restarts from
        where they are, with a fresh history)."""
        self.wait_report(self.send("policy"))

    def stop_teleop(self) -> None:
        """Stop teleoperating outside an episode; the followers hold where they are."""
        self.wait_report(self.send("stop_teleop"))

    def estop(self) -> None:
        """Latch the follower in ESTOP (stays until the dataflow restarts)."""
        self.send("estop")

    def release(self, *, confirm: bool = False) -> None:
        """Torque off the actuated inputs and the followers after stopping; first do what
        `release_note()` says (support what falls, empty what lets go)."""
        if not confirm:
            raise HardwareError(
                f"release turns torque off: {self.release_note()}; then pass confirm=True"
            )
        self.send("release")

    # -- episodes ---------------------------------------------------------------

    def next_info(self) -> EpisodeInfo:
        return EpisodeInfo(
            self.episodes,
            len(self._recorded),
            self.cfg.repo_id.rpartition("/")[2],
            list(self._recorded),
        )

    def record(
        self,
        task: Task,
        seconds: float,
        *,
        keep: Callable[[EpisodeResult], bool] | None = None,
        on_tick: Callable[[dict], None] | None = None,
        tick_s: float = 0.2,
        ready_timeout: float = 60.0,
        home: bool = False,
    ) -> EpisodeResult:
        """One episode: wait until it may start (leader aligned with the follower, at most
        `ready_timeout` s), start, record for `seconds`, stop, then save it unless `keep`
        rejects the stopped episode (default: keep every one; quality warnings are in the
        result either way).

        `task` is a string or a function of `EpisodeInfo`. `on_tick(status)` is called
        every `tick_s` while recording. An exception or Ctrl-C discards the episode.
        `home=True` first moves to the saved home pose (`home`), so every episode starts
        from the same pose.
        """
        name = task(self.next_info()) if callable(task) else task
        if home:
            self.home()
        self.wait_ready(
            ready_timeout
        )  # every episode starts aligned, not only the first
        self.start(name)
        try:
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                self._check_alive()
                if on_tick is not None:
                    on_tick(self.status())
                time.sleep(min(tick_s, max(0.0, end - time.monotonic())))
            stopped = self.stop()
        except BaseException:
            if self.alive:
                with self._cancellable(None):
                    self.discard()
            raise
        if keep is not None and not keep(stopped):
            self.discard()
            return stopped
        return self.save()


def _node_ids(cfg: RobotConfig) -> list[dict]:
    from .flow import build_flow

    return build_flow(cfg)["nodes"]
