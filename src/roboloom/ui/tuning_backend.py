"""Own all tuning device access on one control thread, including open and close."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable

from ..control.tuning import TuningSave, TuningSession
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

GUIDE = (
    "gain: share of identified gravity current; sinks → gain +0.1; rises → gain -0.1. "
    "hold: breakaway resistance; sticky → hold -5 mA; pose-dependent error → hold +5 mA. "
    "compare toggles gravity for the selected joint. Support the mechanism before resume."
)


class TuningBackend:
    def __init__(self, open_session: Callable[[], TuningSession], title: str):
        self.open_session, self.title = open_session, title
        self._publish: Publish = lambda _: None
        self._commands: queue.Queue[str] = queue.Queue()
        self._saves: queue.Queue[TuningSave | None] = queue.Queue()
        self._saved: queue.Queue[tuple[TuningSave, str | None]] = queue.Queue()
        self._estop = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._close_choice: str | None = None
        self._saving = False
        self._phase = "opening tuning device"
        self._warning = ""
        self.failure = ""

    def start(self, publish: Publish) -> None:
        if self._thread is not None:
            raise RuntimeError("backend already started")
        self._publish = publish
        publish(
            Snapshot(
                self.title,
                "tune-gravity",
                self._phase,
                operations=(
                    Operation("estop", "Emergency stop"),
                    Operation("quit", "Quit", confirmation="tuning-quit"),
                ),
                capabilities=Capabilities(gravity=True),
            )
        )
        self._thread = threading.Thread(target=self._control, name="gravity-control")
        self._thread.start()

    def submit(self, command: str) -> None:
        self._commands.put(command)

    def emergency(self) -> None:
        self._estop.set()
        self._publish(
            LogEvent("ESTOP requested; torque-off pending next control step", "error")
        )

    def request_close(self, choice: str) -> None:
        self._commands.put("__close " + choice)

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()

    def _save_loop(self) -> None:
        while (saved := self._saves.get()) is not None:
            error: str | None = None
            try:
                saved.write()
            except Exception as exc:  # noqa: BLE001 - report write errors to control owner
                error = str(exc)
            self._saved.put((saved, error))

    def _begin_save(self, session: TuningSession) -> None:
        if self._saving:
            return
        self._saving = True
        self._phase = ""
        self._warning = ""
        self._saves.put(session.save_snapshot())

    def _command(self, session: TuningSession, command: str) -> None:
        name, _, argument = command.partition(" ")
        if name == "__close":
            if argument in ("save", "discard"):
                self._close_choice = argument
            return
        if self._close_choice is not None:
            return
        if name == "joint":
            if argument not in session.names:
                raise ValueError("joint <name>: " + ", ".join(session.names))
            session.selected = session.names.index(argument)
            return
        if name == "save":
            self._begin_save(session)
            return
        if name == "estop":
            self.emergency()
            return
        key = {
            ("gain", "+"): "]",
            ("gain", "-"): "[",
            ("hold", "+"): "=",
            ("hold", "-"): "-",
            ("compare", ""): "0",
            ("resume", ""): "r",
        }.get((name, argument.strip()))
        if key is None:
            raise ValueError(f"unknown tuning command: {command}")
        if key == "r" and self._estop.is_set():
            raise ValueError("ESTOP: restart required; resume is disabled")
        message = session.key(key)
        if message:
            self._publish(LogEvent(message))

    def _snapshot(self, session: TuningSession) -> Snapshot:
        nodes: list[NodeSnapshot] = []
        for row in session.rows():
            fields: dict[str, Value] = {
                "state": row.state,
                "motor ID": row.motor_id,
                "gain": row.gain,
                "hold mA": row.hold_mA,
                "model mA": row.model_mA,
                "sent mA": row.sent_mA,
                "measured mA": row.measured_mA,
                "position (device units)": row.position,
                "velocity (device units)": row.velocity,
                "guide": row.hint or "choose a pose where this joint carries weight",
                "explanation": GUIDE,
            }
            nodes.append(
                NodeSnapshot(
                    row.joint,
                    "gravity-joint",
                    level="error" if session.stopped else "ok",
                    fields=fields,
                )
            )
        operations = (
            Operation("joint", "Select joint: joint <name>"),
            Operation("gain +", "Gain +0.1 (maximum 3)"),
            Operation("gain -", "Gain -0.1 (minimum 0)"),
            Operation("hold +", "Hold +5 mA (maximum 100)"),
            Operation("hold -", "Hold -5 mA (minimum 0)"),
            Operation("compare", "Compare: toggle gravity"),
            Operation(
                "resume",
                "Supported: resume after STOPPED",
                bool(session.stopped) and not session.estopped,
                "ESTOP: restart required" if session.estopped else "already running",
            ),
            Operation(
                "save",
                "Save tuning",
                not self._saving,
                "save in progress" if self._saving else "",
            ),
            Operation("estop", "Emergency stop"),
            Operation("quit", "Quit", confirmation="tuning-quit"),
        )
        phase = self._phase or (
            "saving"
            if self._saving
            else "STOPPED: " + session.stopped
            if session.stopped
            else "running"
        )
        return Snapshot(
            self.title,
            "tune-gravity",
            phase,
            tuple(nodes),
            operations,
            Capabilities(gravity=True),
            self._warning or session.stopped or "",
            session.names[session.selected],
            session.dirty,
        )

    def _control(self) -> None:
        session: TuningSession | None = None
        saver = threading.Thread(target=self._save_loop, name="gravity-save")
        saver.start()
        outcome = "discarded"
        try:
            session = self.open_session()
            if not self._stop.is_set() and not self._estop.is_set():
                session.start()
            self._phase = ""
            next_draw = 0.0
            while not self._stop.is_set():
                tick = time.monotonic()
                if self._estop.is_set() and not session.estopped:
                    session.emergency()
                    self._publish(
                        LogEvent(
                            "ESTOP torque-off confirmed by control owner; restart required",
                            "error",
                        )
                    )
                # Bounded drain keeps input floods out of the control period.
                for _ in range(16):
                    if self._estop.is_set() and not session.estopped:
                        break
                    try:
                        command = self._commands.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        self._command(session, command)
                    except Exception as exc:  # noqa: BLE001 - a refused request must not stop control
                        self._publish(LogEvent(str(exc), "warn"))
                while not self._saved.empty():
                    saved, error = self._saved.get_nowait()
                    self._saving = False
                    if error is None:
                        session.mark_saved(saved)
                        self._publish(
                            LogEvent(
                                f"saved {saved.path}"
                                + (
                                    "; newer changes remain unsaved"
                                    if session.dirty
                                    else ""
                                )
                            )
                        )
                    else:
                        self._warning = f"save failed: {error}"
                        self._publish(LogEvent(self._warning, "error"))
                        self._phase = "save failed; retry or discard"
                        self._close_choice = None
                if self._close_choice == "discard":
                    break
                if self._close_choice == "save" and not self._saving:
                    if not session.dirty:
                        outcome = "saved"
                        break
                    self._begin_save(session)
                session.step()
                if tick >= next_draw:
                    self._publish(self._snapshot(session))
                    next_draw = tick + 0.1
                self._stop.wait(max(0.0, session.period_s - (time.monotonic() - tick)))
        except Exception as exc:  # noqa: BLE001 - always close on device failure
            self.failure = str(exc)
            self._publish(LogEvent(self.failure, "error"))
            outcome = "failed"
        finally:
            try:
                if session is not None:
                    session.close()
            except Exception as exc:  # noqa: BLE001 - cleanup failures must also reach the UI
                self.failure = str(exc)
                self._publish(LogEvent(self.failure, "error"))
                outcome = "failed"
            finally:
                self._saves.put(None)
                saver.join()
                self._publish(Closed(outcome))
