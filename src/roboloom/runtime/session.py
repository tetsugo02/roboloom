"""Launch an experiment's dora dataflow and direct it from Python.

The dataflow runs the control loops, sensors and recorder in their own processes; a
`Session` never runs a control loop. It sends events (start an episode with a task,
stop, save, ...) and reads the nodes' reports and status. The CLI (`run`, `record`,
`infer`) and Python scripts use this same class.

    with Session.launch("rakuda2/experiment_gravity", hardware=True) as s:
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
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from ..config import ExperimentConfig, load_experiment
from ..errors import ConfigError, HardwareError, RoboloomError
from ..recording.metrics import assess
from ..ui.client import SessionClient
from .flow import write_flow


class SessionError(RoboloomError):
    """The dataflow refused a command or stopped."""


@dataclass
class EpisodeInfo:
    """What a task-naming function knows about the episode it names."""

    index: int  # episode index in the dataset (episodes already saved)
    number: int  # episodes recorded by this session so far
    experiment: str  # experiment file stem, e.g. experiment_gravity
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


def log_dir_for(cfg: ExperimentConfig) -> Path:
    """Next to the experiment, so a project keeps its own logs (ignored by git)."""
    return (
        Path(cfg.path).parent
        / "logs"
        / f"{Path(cfg.path).stem}-{time.strftime('%Y%m%d-%H%M%S')}"
    ).resolve()


def _dora() -> str:
    dora = shutil.which("dora")
    if dora is None:
        raise ConfigError("dora CLI unavailable; install dependencies with uv sync")
    return dora


def validate_flow(cfg: ExperimentConfig, directory: Path) -> Path:
    """Write the experiment's dataflow into `directory` and check it with `dora validate`."""
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


def fifo_for(cfg: ExperimentConfig) -> Path:
    """The command FIFO of a running dataflow; `roboloom session` writes to it."""
    return Path(cfg.output).resolve().with_suffix(".fifo")


class Session:
    def __init__(
        self,
        cfg: ExperimentConfig,
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
        self._reports: list[dict] = []
        self._recorded: list[str] = []
        self._episode: str | None = None  # task of the episode in progress
        self._saved = 0  # dataset episodes after this session's last save

    # -- lifecycle --------------------------------------------------------------

    @classmethod
    def launch(
        cls,
        experiment: str | Path | ExperimentConfig,
        *,
        hardware: bool = False,
        policy: str | None = None,
        policy_kwargs: dict | None = None,
        log_dir: str | Path | None = None,
        timeout: float = 60.0,
    ) -> Session:
        """Validate and start the dataflow; returns once every node reports status.
        Real devices open only with `hardware=True`. `policy` ("module:callable") and
        `policy_kwargs` replace the policy of a `type: policy` controller."""
        cfg = (
            experiment
            if isinstance(experiment, ExperimentConfig)
            else load_experiment(experiment)
        )
        if not cfg.mock and not hardware:
            raise HardwareError(
                f"{cfg.path} opens real devices; pass hardware=True (--hardware)"
            )
        if (policy or policy_kwargs) and not any(
            not c.uses_input for c in cfg.controllers.values()
        ):
            raise ConfigError(f"{cfg.path} has no `type: policy` controller")
        dora = _dora()
        fifo = fifo_for(cfg)
        fifo.parent.mkdir(parents=True, exist_ok=True)
        if fifo.exists():
            raise SessionError(
                f"session FIFO already exists: {fifo} (another run of this experiment, "
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
        try:
            session._wait_nodes(timeout)
        except BaseException:
            session.close()
            raise
        return session

    @property
    def alive(self) -> bool:
        return self.process.poll() is None

    def close(self, timeout: float = 15.0) -> None:
        """Discard an unfinished episode, stop every node and wait for the dataflow to exit."""
        try:
            if self.alive:
                try:
                    if self._episode is not None:
                        self.discard()
                    self.client.send("quit")
                except (OSError, RoboloomError):
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
        self._pull()
        out, self._reports = self._reports, []
        return out

    def _pull(self) -> None:
        self._reports += self.client.new_reports()

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

    def _check_alive(self) -> None:
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
            warning = start_warning(self.cfg, self.status(), time.monotonic_ns())
            if warning is None:
                return
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
            self._pull()
            for k, report in enumerate(self._reports):
                if report.get("id") == ident:
                    del self._reports[k]
                    if "warning" in report or "error" in report:
                        raise SessionError(
                            f"{report.get('command')}: "
                            f"{report.get('warning') or report.get('error')}"
                        )
                    return report
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
        """Write the stopped episode (video encoding can take a while)."""
        task = self._episode or ""
        report = self.wait_report(self.send("save"), timeout)
        self._episode = None
        self._recorded.append(task)
        self._saved = int(report.get("episodes", 0))
        metrics = report.get("metrics", {})
        return EpisodeResult(
            task,
            True,
            int(report.get("saved_frames", 0)),
            int(report.get("episodes", 0)) - 1,
            metrics,
            assess(metrics, self.cfg.quality),
        )

    def discard(self) -> None:
        """Stop the robot and drop the episode in progress."""
        self.wait_report(self.send("discard"))
        self._episode = None

    def estop(self) -> None:
        """Latch the follower in ESTOP (stays until the dataflow restarts)."""
        self.send("estop")

    def release(self, *, confirm: bool = False) -> None:
        """Torque off the follower after stopping; support the arms first."""
        if not confirm:
            raise HardwareError(
                "release drops the arms; support them and pass confirm=True"
            )
        self.send("release")

    # -- episodes ---------------------------------------------------------------

    def next_info(self) -> EpisodeInfo:
        return EpisodeInfo(
            self.episodes,
            len(self._recorded),
            Path(self.cfg.path).stem,
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
    ) -> EpisodeResult:
        """One episode: start, record for `seconds`, stop, then save it unless `keep`
        rejects the stopped episode (default: keep every one; quality warnings are in the
        result either way).

        `task` is a string or a function of `EpisodeInfo`. `on_tick(status)` is called
        every `tick_s` while recording. An exception or Ctrl-C discards the episode.
        """
        name = task(self.next_info()) if callable(task) else task
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
                self.discard()
            raise
        if keep is not None and not keep(stopped):
            self.discard()
            return stopped
        return self.save()


def _node_ids(cfg: ExperimentConfig) -> list[dict]:
    from .flow import build_flow

    return build_flow(cfg)["nodes"]
