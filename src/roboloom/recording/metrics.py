"""Distribution summaries reported after each saved episode."""

from __future__ import annotations

import numpy as np


def summarize(values: list[float]) -> dict:
    if not values:
        return {key: 0.0 for key in ("mean", "p95", "p99", "max")}
    a = np.asarray(values, dtype=float)
    return {
        "mean": float(a.mean()),
        "p95": float(np.percentile(a, 95)),
        "p99": float(np.percentile(a, 99)),
        "max": float(a.max()),
    }


QUALITY = {  # defaults of `recorder.quality` in an experiment
    "max_missing_rate": 0.05,  # per stream: share of rows without a fresh sample
    "min_action_valid_rate": 0.9,
    "max_interval_ms": 100.0,  # longest robot control tick (a stall jerks the data)
}


def assess(metrics: dict, quality: dict) -> list[str]:
    """Quality limits an episode exceeded, as readable warnings (empty: within limits)."""
    limits = {**QUALITY, **quality}
    out = []
    for stream, rate in (metrics.get("missing_rate") or {}).items():
        if rate > limits["max_missing_rate"]:
            out.append(
                f"{stream}: {rate:.0%} of rows missing (limit {limits['max_missing_rate']:.0%})"
            )
    valid = metrics.get("action_valid_rate")
    if valid is not None and valid < limits["min_action_valid_rate"]:
        out.append(
            f"only {valid:.0%} of rows have a valid action "
            f"(limit {limits['min_action_valid_rate']:.0%})"
        )
    worst = (metrics.get("control_interval_ms") or {}).get("max")
    if worst is not None and worst > limits["max_interval_ms"]:
        out.append(
            f"control tick stalled {worst:.0f} ms (limit {limits['max_interval_ms']:.0f} ms)"
        )
    return out
