"""Serial Session operations, independent monitoring, and an emergency send path."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from ..config import CONFIG_FILE
from ..controllers.teleop import teleop_mode
from ..core.traits import ending_note
from ..errors import Cancelled
from ..runtime.node import start_warning
from ..runtime.session import Session, SessionError, _ui_launch, steps_done
from .models import (
    Capabilities,
    Closed,
    LogEvent,
    NodeSnapshot,
    Operation,
    Publish,
    Snapshot,
    Value,
)
from .record import describe, episode_number, progress
from .render import describe_report


@dataclass(frozen=True)
class RecordingPlan:
    task: str
    seconds: float
    episodes: int = 1
    save: bool = True
    home: bool | str = False
    # end an episode after this many actions of the policy; `seconds` is then its limit
    steps: int | None = None
    confirm: bool = False

    def __post_init__(self) -> None:
        if not self.task.strip() or self.seconds <= 0 or self.episodes < 1:
            raise ValueError(
                "task, positive seconds and at least one episode are required"
            )
        if self.confirm and not self.save:
            raise ValueError("confirm requires a plan that saves episodes")


class SessionBackend:
    def __init__(
        self,
        launch: Callable[[], Session],
        *,
        mode: str = "run",
        recording: RecordingPlan | None = None,
        reselect: bool = False,
    ):
        """`reselect`: the quit dialog also offers to close and choose the launch options
        again (the run then ends with the outcome "reselect")."""
        self.launch, self.mode, self.recording = launch, mode, recording
        self.reselect = reselect
        self._reselected = False
        self.session: Session | None = None
        self._publish: Publish = lambda _: None
        self._queue: queue.Queue[str] = queue.Queue()
        self._emergencies: queue.Queue[bool] = queue.Queue()
        self._cancel = threading.Event()
        self._finish_recording = threading.Event()
        self._discard_requested = False
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._lock = threading.RLock()
        self._threads: list[threading.Thread] = []
        self._busy = True
        self._closing = False
        self._release = False
        self._phase = "launching"
        self._warning = ""
        self._episode = False
        self._recording = False
        self._index = 0
        self._estop = False
        self._estop_ns = 0
        self._estop_confirmed = False
        self._log_offset = 0
        self.failure = ""
        # teleop / policy asked for while an episode of the recording plan runs
        self._handovers: queue.Queue[str] = queue.Queue()

    def start(self, publish: Publish) -> None:
        if self._threads:
            raise RuntimeError("backend already started")
        self._publish = publish
        publish(self._snapshot())
        emergency = threading.Thread(target=self._emergency_loop, name="operator-estop")
        worker = threading.Thread(target=self._work, name="operator-session")
        self._threads = [worker, emergency]
        emergency.start()
        worker.start()

    def _log(self, text: str, level: str = "info", style: str = "") -> None:
        self._publish(LogEvent(text, level, style))

    def _report(self, report: dict) -> None:
        line = describe_report(report)
        self._log(line.plain, style=str(line.style))

    def _snapshot(self) -> Snapshot:
        with self._lock:
            session = self.session
            if session is None:
                return Snapshot(
                    "roboloom",
                    self.mode,
                    self._phase,
                    operations=(
                        Operation("estop", "Emergency stop"),
                        Operation("quit", "Quit", confirmation="quit"),
                    ),
                )
            status = session.status()
            now = time.monotonic_ns()
            nodes: list[NodeSnapshot] = []
            owners = {
                **session.cfg.followers,
                **session.cfg.inputs,
                **session.cfg.controllers,
                **session.cfg.sensors,
            }
            for name, item in status.items():
                owner = owners.get(name)
                config = getattr(owner, "cfg", {})
                kind = str(config.get("type", ""))
                nodes.append(
                    NodeSnapshot(
                        name,
                        str(item.get("role", "unknown")),
                        kind,
                        str(item.get("level", "ok")),
                        max(0.0, (now - item.get("t_ns", 0)) / 1e9),
                        cast(dict[str, Value], item.get("fields", {})),
                        int(item.get("t_ns", 0)),
                    )
                )
            mode = teleop_mode(session.cfg.controllers)
            control = None
            if mode is not None and mode.policy is not None:
                control = status.get(mode.policy, {}).get("fields", {}).get("control")
            elif (
                mode is not None
                and not self._recording
                and any(
                    status.get(f, {}).get("fields", {}).get("armed")
                    for f in session.cfg.followers
                )
            ):
                control = "teleop"
            caps = Capabilities(
                home=any(c.homes for c in session.cfg.controllers.values()),
                teleop=mode is not None,
                handback=mode is not None and mode.handback,
                release=bool(session.torqued or session.actuated),
                hold=bool(session.held),
                torqued=bool(session.torqued),
                reselect=self.reselect,
                release_note=session.release_note(),
                quit_note=ending_note(session.limp_at_end),
            )
            readiness = start_warning(session.cfg, status, now) or ""
            warning = self._warning or readiness
            busy_reason = (
                "closing"
                if self._closing
                else "operation in progress"
                if self._busy
                else ""
            )
            start_reason = (
                busy_reason
                or ("ESTOP: restart required" if self._estop else "")
                or ("episode already open" if self._episode else "")
                or readiness
            )
            # the planned count is a goal, not a limit: Start runs another episode
            operations = (
                Operation(
                    "start", "Start episode", not bool(start_reason), start_reason
                ),
                Operation(
                    "stop",
                    "Stop recording",
                    self._recording,
                    busy_reason or "no recording",
                ),
                Operation(
                    "save",
                    "Save episode",
                    not self._busy and self._episode and not self._recording,
                    busy_reason or "stop an episode first",
                ),
                Operation(
                    "discard",
                    "Discard episode",
                    self._episode
                    and (
                        not self._busy
                        or (self.recording is not None and self._recording)
                    ),
                    busy_reason or "no episode",
                ),
                Operation(
                    "home",
                    "Move home",
                    caps.home
                    and not self._busy
                    and not self._episode
                    and not self._estop
                    and control != "teleop",
                    (
                        "no home pose"
                        if not caps.home
                        else "stop/discard the episode first"
                        if self._episode
                        else "ESTOP: restart required"
                        if self._estop
                        else "stop teleoperating first"
                        if control == "teleop"
                        else busy_reason
                    ),
                ),
                Operation(
                    "release",
                    "Release torque",
                    caps.release and not self._busy,
                    "no actuated input or follower"
                    if not caps.release
                    else busy_reason,
                    "release",
                ),
                *self._teleop_operations(caps, control, busy_reason),
                Operation("estop", "Emergency stop"),
                Operation("quit", "Quit", confirmation="quit"),
            )
            path = Path(session.cfg.path)
            return Snapshot(
                path.parent.name if path.name == CONFIG_FILE else path.stem,
                self.mode
                + (" / mock" if session.cfg.mock else " / hardware")
                + (
                    f" / {', '.join(session.cfg.options)}"
                    if session.cfg.options
                    else ""
                ),
                self._phase,
                tuple(nodes),
                operations,
                caps,
                warning,
            )

    def _teleop_operations(
        self, caps: Capabilities, control: object, busy_reason: str
    ) -> tuple[Operation, ...]:
        """Teleop and Stop teleop for operator input, plus Policy when hand-back is
        available. A policy allows Teleop and Policy while recording an intervention."""
        if not caps.teleop:
            return ()
        busy = "" if self._recording and caps.handback else busy_reason
        teleop_reason = (
            "ESTOP: restart required"
            if self._estop
            else (
                "the input already drives the episode"
                if self._recording and not caps.handback
                else ""
            )
            or (
                "stopped episode: save or discard first"
                if self._episode and not self._recording
                else ""
            )
            or busy
            or ("already teleoperating" if control == "teleop" else "")
        )
        policy_reason = (
            "only during an episode (start begins with the policy)"
            if not self._recording
            else "the policy is driving"
            if control != "teleop"
            else ""
        )
        stop_reason = (
            (
                "during an episode: Stop, or Policy to hand back"
                if caps.handback
                else "during an episode: Stop"
            )
            if self._episode
            else busy_reason or ("not teleoperating" if control != "teleop" else "")
        )
        teleop = Operation(
            "teleop",
            "Teleoperate (take over)"
            if caps.handback
            else "Teleoperate (no recording)",
            not teleop_reason,
            teleop_reason,
        )
        stop = Operation(
            "stop_teleop", "Stop teleoperating", not stop_reason, stop_reason
        )
        if not caps.handback:
            return (teleop, stop)
        return (
            teleop,
            Operation(
                "policy", "Hand back to policy", not policy_reason, policy_reason
            ),
            stop,
        )

    def submit(self, command: str) -> None:
        name = command.split(" ", 1)[0]
        if name == "estop":
            self.emergency()
            return
        with self._lock:
            if name == "stop" and self._busy and self._recording:
                self._finish_recording.set()
                return
            if name == "discard" and self.recording is not None and self._recording:
                self._discard_requested = True
                self._finish_recording.set()
                return
            if name in ("teleop", "policy") and self._busy and self._recording:
                operation = next(
                    (o for o in self._snapshot().operations if o.command == name), None
                )
                if operation is None or not operation.enabled:
                    self._log(operation.reason if operation else name, "warn")
                    return
                self._handovers.put(name)  # the recording loop sends it
                return
            operation = next(
                (o for o in self._snapshot().operations if o.command == name), None
            )
            if operation is None or not operation.enabled or name == "quit":
                self._log(
                    operation.reason if operation else f"unknown command: {name}",
                    "warn",
                )
                return
            if (
                name == "start"
                and self.recording is None
                and not command.partition(" ")[2].strip()
            ):
                self._log("start <task>: task is required", "warn")
                return
            self._busy = True
            self._cancel.clear()
            self._queue.put(command)

    def _prepare(self, session: Session) -> None:
        plan = self.recording
        if plan is not None:
            if self._estop:
                self._phase = "ESTOP: restart required"
                return
            if plan.home:
                self._phase = "moving home"
                if isinstance(plan.home, str):
                    session.home(pose=plan.home)
                else:
                    session.home()
        self._phase = "waiting for readiness"
        session.wait_ready(120)
        self._phase = self._ready_phase()

    def _ready_phase(self) -> str:
        plan = self.recording
        if plan is None:
            return "ready"
        return f"ready: {episode_number(self._index, plan.episodes)}"

    def _advance(self, session: Session) -> None:
        plan = self.recording
        assert plan is not None
        self._index += 1
        if self._index == plan.episodes:
            # The app asks once whether to quit. Start can still run another episode.
            self._phase = "complete"
        elif self._index < plan.episodes:
            self._prepare(session)
        else:  # past the plan: the operator moves the robot (Home, Teleop)
            self._phase = self._ready_phase()

    def _execute(self, session: Session, command: str) -> None:
        name, _, task = command.partition(" ")
        self._warning = ""
        self._phase = name
        if name == "start":
            plan = self.recording
            if plan is None:
                session.wait_ready(10)  # e.g. the last episode is still being saved
                session.start(task)
                self._episode = self._recording = True
                self._phase = "recording"
            else:
                self._finish_recording.clear()
                self._discard_requested = False
                session.wait_ready(120)
                session.start(plan.task)
                self._episode = self._recording = True
                try:
                    began = time.monotonic()
                    end, done = began + plan.seconds, 0
                    while (
                        time.monotonic() < end and not self._finish_recording.is_set()
                    ):
                        session._check_running()
                        self._hand_over(session)
                        if plan.steps:
                            done = steps_done(session.status())
                        self._phase = progress(
                            self._index,
                            plan.episodes,
                            time.monotonic() - began,
                            plan.seconds,
                            done,
                            plan.steps,
                        )
                        if plan.steps and done >= plan.steps:
                            break
                        self._finish_recording.wait(
                            min(0.1, max(0.0, end - time.monotonic()))
                        )
                    if (
                        plan.steps
                        and done < plan.steps
                        and not self._finish_recording.is_set()
                    ):
                        self._log(f"ended by time at {done}/{plan.steps} steps", "warn")
                    with self._lock:
                        self._phase = "stopping"
                        self._recording = False
                        discarded = self._discard_requested
                        if discarded:
                            # A handover queued for this episode must end with it.
                            self._handovers = queue.Queue()
                    result = session.stop()
                    if plan.confirm and not discarded:
                        number = episode_number(self._index, plan.episodes)
                        self._phase = f"stopped: save or discard ({number})"
                        return
                    if plan.save and not discarded:
                        self._phase = "saving"
                        result = session.save()
                        if result.pending:
                            self._phase = "queued for save"
                    else:
                        self._phase = "discarding"
                        session.discard()
                    self._log(describe(result))
                except BaseException:
                    self._episode = self._recording = False
                    if session.alive:
                        with session._cancellable(None):
                            session.discard()
                    raise
                self._episode = False
                if discarded:
                    self._prepare(session)
                else:
                    self._advance(session)
        elif name == "home":
            if pose := task.strip():
                session.home(pose=pose)
            else:
                session.home()
            session.wait_ready(120)
            self._phase = "ready"
        elif name == "stop":
            try:
                self._log(describe(session.stop()))
            except SessionError as exc:
                if exc.report.get("dropped"):  # nothing left to save or discard
                    self._episode = self._recording = False
                raise
            self._recording = False
            self._phase = "stopped: save or discard"
        elif name == "save":  # `save success` / `save failure`: with the verdict
            try:
                result = session.save(label=task.strip() or None)
            except SessionError as exc:
                if self.recording is not None and exc.report.get("dropped"):
                    self._episode = False
                raise
            self._episode = False
            self._log(describe(result))
            if self.recording is not None:
                self._advance(session)
            else:
                self._phase = "queued for save" if result.pending else "saved"
        elif name == "discard":
            session.discard()
            self._episode = self._recording = False
            self._phase = "discarded"
            if self.recording is not None:
                self._prepare(session)
        elif name == "release":
            session.release(confirm=True)
            self._phase = "release sent; check node status"
        elif name == "teleop":
            session.teleop()
            mode = teleop_mode(session.cfg.controllers)
            self._phase = (
                "teleoperating: the followers follow the input (nothing recorded)"
                if mode is not None and not mode.handback
                else "teleoperating: joints follow once the leader reaches them"
            )
        elif name == "policy":
            session.policy()
            self._phase = "recording: the policy drives"
        elif name == "stop_teleop":
            session.stop_teleop()
            self._phase = "ready"

    def _hand_over(self, session: Session) -> None:
        """Send the teleop / policy asked for during the episode (refusals are logged;
        the episode goes on)."""
        while True:
            try:
                name = self._handovers.get_nowait()
            except queue.Empty:
                return
            try:
                session.teleop() if name == "teleop" else session.policy()
                self._log(
                    "intervention: the leader drives (joints follow once reached)"
                    if name == "teleop"
                    else "handed back to the policy"
                )
            except Exception as exc:  # noqa: BLE001 - refused: keep recording
                self._log(str(exc), "warn")

    def _work(self) -> None:
        monitor: threading.Thread | None = None
        outcome = "done"

        def opened(session: Session) -> None:
            nonlocal monitor
            self.session = session
            session.listen(self._report)
            self._ready.set()
            monitor = threading.Thread(target=self._monitor, name="operator-monitor")
            monitor.start()

        try:
            with _ui_launch(self._cancel, opened):
                session = self.launch()
            # Fake / alternative factories may not invoke Session.launch.
            if self.session is None:
                opened(session)
            with session._cancellable(self._cancel):
                try:
                    self._prepare(session)
                except Exception as exc:  # noqa: BLE001 - report failures while preserving lifecycle cleanup
                    self._warning = str(exc)
                    self._log(str(exc), "warn")
            self._busy = False
            while not self._closing:
                try:
                    command = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if self._closing:
                    break
                try:
                    with session._cancellable(self._cancel):
                        self._execute(session, command)
                except Cancelled as exc:
                    self._phase = "cancelled"
                    self._log(str(exc), "warn")
                except Exception as exc:  # noqa: BLE001 - report failures while preserving lifecycle cleanup
                    self._phase = (
                        "save failed; retry or discard"
                        if self.recording is not None
                        and command.partition(" ")[0] == "save"
                        and self._episode
                        else "operation refused; retry when ready"
                    )
                    self._warning = str(exc)
                    self._log(str(exc), "warn")
                finally:
                    self._busy = False
        except Exception as exc:  # noqa: BLE001 - report failures while preserving lifecycle cleanup
            self.failure = str(exc)
            outcome = "failed"
            self._log(self.failure, "error")
        finally:
            self._stop.set()
            self._ready.set()
            if monitor is not None:
                monitor.join()
            try:
                if self.session is not None:
                    self.session.close(release=self._release)
            except Exception as exc:  # noqa: BLE001 - surface cleanup failure without losing the final notification
                self.failure = str(exc)
                outcome = "failed"
                self._log(self.failure, "error")
            finally:
                self._emergencies.put(False)
                self._threads[1].join()
                if self._reselected and outcome == "done":
                    outcome = "reselect"
                self._publish(Closed(outcome))

    def _monitor(self) -> None:
        while not self._stop.is_set():
            try:
                session = self.session
                assert session is not None
                session.poll()
                snapshot = self._snapshot()
                if self._estop_ns and not self._estop_confirmed:
                    robots = [n for n in snapshot.nodes if n.role == "follower"]
                    expected = set(session.cfg.followers)
                    if (
                        expected
                        and expected <= {n.name for n in robots}
                        and all(
                            n.fields.get("mode") == "ESTOP" and n.t_ns > self._estop_ns
                            for n in robots
                        )
                    ):
                        self._estop_confirmed = True
                        self._log("ESTOP confirmed by all followers", "error")
                self._publish(snapshot)
                try:
                    with session.log_path.open("rb") as stream:
                        stream.seek(self._log_offset)
                        data = stream.read(65536)
                    # Leave partial lines for the next read.
                    end = data.rfind(b"\n") + 1
                    self._log_offset += end
                    for line in data[:end].decode(errors="replace").splitlines():
                        self._log(line)
                except OSError:
                    pass
                if not session.alive:
                    self.request_close("hold")
            except Exception as exc:  # noqa: BLE001 - report failures while preserving lifecycle cleanup
                self._log(str(exc), "error")
            self._stop.wait(0.1)

    def emergency(self) -> None:
        self._estop = True
        self._estop_ns = 0
        self._estop_confirmed = False
        self._cancel.set()
        self._log("ESTOP requested; awaiting send and follower confirmation", "error")
        self._emergencies.put(True)

    def _emergency_loop(self) -> None:
        while self._emergencies.get():
            while not self._ready.wait(0.1):
                if self._stop.is_set():
                    return
            if self.session is None:
                return
            try:
                # FIFO writes are atomic. Bypass normal queue, wait, and log inspection.
                sent_ns = time.monotonic_ns()
                self.session.client.send("estop", attempts=1)
                self._estop_ns = sent_ns
                self._log("ESTOP sent; follower stop is not yet confirmed", "error")
            except Exception as exc:  # noqa: BLE001 - report failures while preserving lifecycle cleanup
                self._log(f"ESTOP SEND FAILED: {exc}", "error")

    def request_close(self, choice: str) -> None:
        with self._lock:
            if self._closing:
                return
            self._release = choice == "release"
            self._reselected = choice == "reselect"
            self._closing = True
            self._cancel.set()

    def shutdown(self) -> None:
        self.request_close("hold")
        for thread in self._threads:
            thread.join()
