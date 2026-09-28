"""Distribution summaries reported after each saved episode."""

from __future__ import annotations

import numpy as np


def summarize(values: list[float]) -> dict:
    if not values:
        return {key: 0.0 for key in ("mean", "p95", "p99", "max")}
    a = np.asarray(values, dtype=float)
    return {"mean": float(a.mean()), "p95": float(np.percentile(a, 95)), "p99": float(np.percentile(a, 99)), "max": float(a.max())}
