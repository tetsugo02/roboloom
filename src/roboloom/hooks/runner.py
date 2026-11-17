"""Synchronous steps, per-hook ordered event workers and write enforcement."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from queue import Queue

import numpy as np

from .config import BoundHook
from .events import BARRIERS, EpisodeEnded, Event
from .types import Scalar, StepContext

log = logging.getLogger(__name__)
START_TIMEOUT_S = 60.0
DRAIN_TIMEOUT_S = 60.0


class HookError(RuntimeError):
    """A hook with on_error: fail refused a control period or barrier."""


@dataclass
class HookStats:
    ms: float = 0.0
    max_ms: float = 0.0
    errors: int = 0
    over: int = 0
    changed: int = 0
    notes: dict[str, Scalar] = field(default_factory=dict)


@dataclass
class _Delivery:
    event: Event
    settle: Callable[[], None] | None = None
    done: threading.Event = field(default_factory=threading.Event)


class _Entry:
    def __init__(self, bound: BoundHook):
        self.bound = bound
        self.lock = threading.Lock()
        self.stats = HookStats()
        self.pending: Exception | None = None
        self.queue: Queue[_Delivery | None] = Queue()
        self.thread: threading.Thread | None = None
        if callable(getattr(bound.hook, "on_event", None)):
            self.thread = threading.Thread(
                target=self._work, daemon=True, name=f"hook-{bound.name}"
            )
            self.thread.start()

    def _close(self) -> None:
        close = getattr(self.bound.hook, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                log.exception("hook %s close raised", self.bound.name)

    def _work(self) -> None:
        try:
            while (delivery := self.queue.get()) is not None:
                try:
                    if delivery.settle is not None:
                        delivery.settle()
                    with self.lock:
                        handler = getattr(self.bound.hook, "on_event", None)
                        if callable(handler):
                            handler(delivery.event)
                except Exception:
                    log.exception(
                        "hook %s event %s raised", self.bound.name, delivery.event.kind
                    )
                finally:
                    delivery.done.set()
        finally:
            with self.lock:
                self._close()


class HookChain:
    """Run bound hooks in order; step and event methods of one hook never overlap.

    ``start_timeout_s`` is injectable for tests. Event errors are logged; a barrier
    timeout uses on_error. No synchronous step can be interrupted by a time budget.
    """

    def __init__(
        self,
        hooks: Sequence[BoundHook] = (),
        *,
        start_timeout_s: float = START_TIMEOUT_S,
    ):
        self.entries = [_Entry(h) for h in hooks]
        self.start_timeout_s = start_timeout_s
        self.filtered = 0
        self.ms = self.max_ms = 0.0
        self.closed = False
        owners: dict[str, str] = {}
        for h in hooks:
            for name in h.requirements.writes:
                if name in owners:
                    log.warning(
                        "hook writes overlap at %s: %s then %s (later wins)",
                        name,
                        owners[name],
                        h.name,
                    )
                owners[name] = h.name

    @property
    def observe(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(k for e in self.entries for k in e.bound.requirements.observe)
        )

    def reset_stats(self) -> None:
        self.filtered = 0
        self.ms = self.max_ms = 0.0
        for entry in self.entries:
            entry.stats = HookStats()
            entry.pending = None

    @staticmethod
    def _error_value(
        entry: _Entry, action: np.ndarray, ctx: StepContext, error: Exception
    ) -> np.ndarray:
        """The single decision point for refused/failed entries (future fallback seam)."""
        mode = entry.bound.requirements.on_error
        if mode == "fail":
            raise HookError(f"hook {entry.bound.name}: {error}") from error
        output = action.copy()
        if mode == "hold":
            output[ctx.writable_mask] = ctx.held[ctx.writable_mask]
        return output

    def run(self, action: np.ndarray, ctx: StepContext) -> np.ndarray:
        """One period. Each hook sees the preceding output and only its observation."""
        chosen = np.asarray(action, dtype=np.float64)
        if chosen.shape != (len(ctx.names),) or not np.isfinite(chosen).all():
            raise HookError("hook chain requires a finite complete action")
        out = chosen.copy()
        total = 0.0
        for entry in self.entries:
            bound = entry.bound
            step = getattr(bound.hook, "step", None)
            if not callable(step) or ctx.source not in bound.requirements.sources:
                continue
            context = ctx.for_hook(bound.requirements, entry.stats.notes)
            before = out.copy()
            t0 = time.perf_counter()
            acquired = False
            pending, entry.pending = entry.pending, None
            try:
                if pending is not None:
                    raise pending
                acquired = entry.lock.acquire(blocking=False)
                if not acquired:
                    raise TimeoutError("previous event is still running")
                result = step(out.copy(), context)
                if result is None:
                    result = before
                after = np.asarray(result, dtype=np.float64)
                if after.shape != before.shape or not np.isfinite(after).all():
                    raise ValueError(
                        f"expected finite action shape {before.shape}; got {after.shape}"
                    )
                mask = ~context.writable_mask
                if after[mask].tobytes() != before[mask].tobytes():
                    raise ValueError("changed entries outside declared writes")
                out = after.copy()
            except Exception as exc:  # noqa: BLE001 - hook failures use on_error
                if pending is None:
                    entry.stats.errors += 1
                log.warning("hook %s step error: %s", bound.name, exc)
                out = self._error_value(entry, before, context, exc)
            finally:
                if acquired:
                    entry.lock.release()
                ms = (time.perf_counter() - t0) * 1000
                total += ms
                self.ms = total
                self.max_ms = max(total, self.max_ms)
                entry.stats.ms = ms
                entry.stats.max_ms = max(ms, entry.stats.max_ms)
                budget = bound.requirements.budget_ms
                # default: half an action period, in milliseconds
                budget = 500.0 / ctx.rate_hz if budget is None else budget
                if ms > budget:
                    entry.stats.over += 1
                    log.warning(
                        "hook %s over budget: %.3f ms > %.3f ms", bound.name, ms, budget
                    )
            entry.stats.changed += int(bool(np.any(out != before)))
        self.ms = total
        self.max_ms = max(total, self.max_ms)
        self.filtered += int(bool(np.any(out != chosen)))
        return out

    def emit(
        self,
        event: Event,
        *,
        rate_hz: float = 1.0,
        settle: Callable[[], None] | None = None,
    ) -> None:
        """Queue for every event hook; barriers wait only for hooks with a step."""
        deliveries: list[tuple[_Entry, _Delivery]] = []
        for entry in self.entries:
            if entry.thread is not None:
                delivery = _Delivery(
                    event, settle if isinstance(event, EpisodeEnded) else None
                )
                entry.queue.put(delivery)
                deliveries.append((entry, delivery))
        deadline = time.monotonic() + self.start_timeout_s
        for entry, delivery in deliveries:
            if event.kind not in BARRIERS or not callable(
                getattr(entry.bound.hook, "step", None)
            ):
                continue
            budget = entry.bound.requirements.budget_ms
            seconds = ((0.5 / rate_hz if budget is None else budget) * 10) / 1000
            timeout = (
                max(0.0, deadline - time.monotonic())
                if event.kind == "episode_started"
                else seconds
            )
            if not delivery.done.wait(timeout):
                error = TimeoutError(
                    f"{event.kind} barrier timed out after {timeout:g} s"
                )
                entry.stats.errors += 1
                log.warning("hook %s: %s", entry.bound.name, error)
                if event.kind == "episode_started":
                    raise HookError(f"hook {entry.bound.name}: {error}")
                # A pending hold/pass is applied at the next period, never concurrently.
                entry.pending = error
                if entry.bound.requirements.on_error == "fail":
                    raise HookError(f"hook {entry.bound.name}: {error}")

    def status(self) -> dict[str, float | int]:
        return {
            "hook_ms": round(self.ms, 3),
            "hook_max_ms": round(self.max_ms, 3),
            "hook_errors": sum(e.stats.errors for e in self.entries),
            "hook_over": sum(e.stats.over for e in self.entries),
            "filtered": self.filtered,
        }

    def log_stats(self) -> None:
        for entry in self.entries:
            log.info("hook %s episode stats: %s", entry.bound.name, asdict(entry.stats))

    def close(self, timeout: float = DRAIN_TIMEOUT_S) -> bool:
        """Drain workers, then close. On timeout the worker closes after its queue."""
        if self.closed:
            return not any(e.thread and e.thread.is_alive() for e in self.entries)
        self.closed = True
        for entry in self.entries:
            if entry.thread is not None:
                entry.queue.put(None)
            else:
                with entry.lock:
                    entry._close()
        deadline = time.monotonic() + timeout
        drained = True
        for entry in self.entries:
            if entry.thread is not None:
                entry.thread.join(max(0.0, deadline - time.monotonic()))
                if entry.thread.is_alive():
                    drained = False
                    log.warning(
                        "hook %s still draining after %g s", entry.bound.name, timeout
                    )
        return drained
