"""Horizontal seams in DIGIT frames: a rolled stream or a pasted band of rows.

A seam is one native row where the pixel values jump across most columns: the
row-wise difference peaks there in most columns at once, far above the rows on
either side. Smooth illumination and contact blobs never do that. numpy only;
no cv2 import, so this runs wherever the reader runs.
"""

from __future__ import annotations

import numpy as np

SEAM_MIN_COLUMNS = 0.5  # share of columns whose largest jump is at the seam row
SEAM_MIN_RATIO = 10.0  # seam row's mean jump / mean jump of the 5 rows on each side


def find_seam(
    frame: np.ndarray,
    min_columns: float = SEAM_MIN_COLUMNS,
    min_ratio: float = SEAM_MIN_RATIO,
) -> int | None:
    """The native row index (0-based, the row after the jump) of a horizontal seam in a DIGIT
    frame as get_frame() returns it (transposed, HxWx3 uint8), or None."""
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError(f"expected an HxWx3 frame, got shape {frame.shape}")
    native = frame.transpose(1, 0, 2).astype(np.int16)  # (rows, cols, 3)
    diff = np.abs(np.diff(native, axis=0)).max(axis=2)  # (rows-1, cols)
    rows = diff.argmax(axis=0)
    modal = int(np.bincount(rows).argmax())
    frac = float(np.mean(rows == modal))
    peak = float(diff[modal].mean())
    neighbours = np.concatenate(
        [diff[max(modal - 5, 0) : modal], diff[modal + 1 : modal + 6]]
    )
    ratio = peak / max(float(neighbours.mean()), 0.1) if neighbours.size else peak / 0.1
    return modal + 1 if frac >= min_columns and ratio >= min_ratio else None
