"""Fitting helpers for `roboloom identify-gravity` (numpy only).

Joint directions and zeros come from calibration. Gravity data alone cannot
always decide them: a planar chain with every angle flipped is the same as one
with mirrored masses, and a constant offset on a joint whose downstream axes are
parallel is absorbed by the first moments. `search_directions` therefore only
checks the calibrated directions and lists every combination that fits as well.
"""

from __future__ import annotations

import itertools
from dataclasses import replace

import numpy as np

from .regressor import Fit, JointMap, Regressor


def holdout_mask(count: int, every: int = 4) -> np.ndarray:
    """Every `every`-th pose (both approach directions) is held out for validation."""
    return np.arange(count) % every == every - 1


def score(fit: Fit) -> float:
    errors = fit.holdout_rms_mA or fit.rms_mA
    return float(np.sqrt(np.mean(np.square(errors))))


def search_directions(
    urdf: str,
    inputs: list[JointMap],
    outputs: list[str],
    samples: np.ndarray,
    currents: np.ndarray,
    holdout: np.ndarray,
    fixed: frozenset[str] | set[str] = frozenset(),
    shared: bool = False,
) -> list[tuple[float, list[JointMap], Fit]]:
    """Fit every sign combination of the non-fixed inputs; best (lowest holdout RMS) first."""
    free = [k for k, m in enumerate(inputs) if m.name not in fixed]
    results = []
    for signs in itertools.product((1, -1), repeat=len(free)):
        trial = list(inputs)
        for k, sign in zip(free, signs, strict=True):
            trial[k] = replace(inputs[k], direction=sign * abs(inputs[k].direction))
        fit = Regressor(urdf, trial, outputs).fit(samples, currents, holdout, shared)
        results.append((score(fit), trial, fit))
    return sorted(results, key=lambda r: r[0])


def robust_outliers(values: np.ndarray, floor: float, max_fraction: float = 0.1) -> np.ndarray:
    """Rows (N x joints) far outside the bulk: |v - median| > max(4 robust sigma, floor) on any joint.

    At most `max_fraction` of the rows are flagged, worst first, so a poor model cannot
    discard the data that disagrees with it.
    """
    center = np.median(values, axis=0)
    sigma = 1.4826 * np.median(np.abs(values - center), axis=0)
    excess = np.abs(values - center) / np.maximum(4 * sigma, floor)
    worst = excess.max(axis=1)
    flagged = np.flatnonzero(worst > 1)
    keep = int(max_fraction * len(values))
    flagged = flagged[np.argsort(-worst[flagged])][:keep]
    mask = np.zeros(len(values), bool)
    mask[flagged] = True
    return mask
