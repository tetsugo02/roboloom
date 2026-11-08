"""Turn a hand-held recording into a training dataset (`roboloom convert-handheld`).

The recording (a configuration without followers) keeps each device's absolute pose, jaw,
tracking and engaged as `observation.<hand>` and has no `action`. The conversion writes a
new LeRobotDataset with the same frames and videos plus:

- `action`, one of
  - `delta`: per hand `inv(P[t]) @ P[t+1]` (9) and the jaw at t+1: 10 per hand;
  - `relative-chunk`: per hand `inv(P[t]) @ P[t+k]` (9) and the jaw at t+k, for
    k = 1..H, flattened k-major: H x 10 per hand (train with chunk_size 1);
- `observation.state`: per hand `inv(P[t]) @ P[t-1]` (9, a cue for velocity) and the jaw
  at t; with two or more hands, each further hand's pose seen from the first (9).

Untracked rows are filled when a gap is at most `max_gap` rows; episodes with a longer
gap are left out (reported). `meta/roboloom_handheld.json` records how the dataset was
made, so a robot can turn the policy's output back into poses.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..errors import ConfigError
from ..inputs.base import POSE_FIELDS
from . import poses as P

ACTIONS = ("delta", "relative-chunk")
METADATA = "meta/roboloom_handheld.json"
_X, _Q, _JAW, _TRACKING = (
    slice(0, 3),
    slice(3, 7),
    POSE_FIELDS.index("gripper"),
    POSE_FIELDS.index("tracking"),
)


@dataclass
class Report:
    output: Path
    episodes: int
    frames: int
    dropped: dict[int, str] = field(default_factory=dict)  # source episode -> reason
    filled_rows: int = 0

    def describe(self) -> str:
        lines = [
            f"wrote {self.output}: {self.episodes} episodes, {self.frames} frames"
            + (
                f", {self.filled_rows} untracked rows filled"
                if self.filled_rows
                else ""
            )
        ]
        lines += [f"  left out episode {k}: {why}" for k, why in self.dropped.items()]
        return "\n".join(lines)


def hands_of(features: dict[str, dict]) -> list[str]:
    """Recorded hand-held poses: `observation.<name>` features laid out as POSE_FIELDS."""
    return [
        key.removeprefix("observation.")
        for key, f in features.items()
        if key.startswith("observation.")
        and list(f.get("names") or []) == list(POSE_FIELDS)
    ]


def recorded_poses(raw: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Poses `[N, 4, 4]` and which rows are tracked, from recorded `[N, 10]` rows.

    A row without a fresh sample is recorded as zeros (no rotation, tracking 0); such
    rows, and untracked ones, get the identity rotation here and count as untracked, so
    `fill_gaps` fills or reports them instead of the conversion failing."""
    raw = np.asarray(raw, dtype=float)
    quaternion = raw[:, _Q].copy()
    norm = np.linalg.norm(quaternion, axis=1)
    tracked = (raw[:, _TRACKING] > 0.5) & np.isfinite(norm) & (norm > 1e-6)
    tracked &= np.isfinite(raw[:, _X]).all(axis=1)
    quaternion[~tracked] = (0.0, 0.0, 0.0, 1.0)
    position = np.where(tracked[:, None], raw[:, _X], 0.0)
    return P.poses_from(position, quaternion), tracked


def _names(hands: Sequence[str], action: str, horizon: int) -> tuple[list, list]:
    per_hand = [*P.POSE_NAMES, "gripper"]
    if action == "delta":
        act = [f"{h}.{n}" for h in hands for n in per_hand]
    else:
        act = [
            f"k{k:02d}.{h}.{n}"
            for k in range(1, horizon + 1)
            for h in hands
            for n in per_hand
        ]
    state = [
        name
        for h in hands
        for name in (*(f"{h}.prev_{n}" for n in P.POSE_NAMES), f"{h}.gripper")
    ]
    state += [f"{hands[0]}_to_{h}.{n}" for h in hands[1:] for n in P.POSE_NAMES]
    return act, state


def episode_arrays(
    rows: dict[str, np.ndarray], hands: Sequence[str], action: str, horizon: int
) -> tuple[np.ndarray, np.ndarray]:
    """`action` and `observation.state` of one episode from filled `[N, 10]` rows; the
    poses in `rows` are already filled (see `fill_gaps`) and passed as `<hand>.pose`."""
    acts, states, firsts = [], [], []
    for hand in hands:
        pose = rows[f"{hand}.pose"]
        jaw = rows[hand][:, _JAW]
        n = len(pose)
        if action == "delta":
            nxt = np.minimum(np.arange(n) + 1, n - 1)
            acts.append(np.concatenate([P.encode(P.deltas(pose)), jaw[nxt, None]], 1))
        else:
            index = np.minimum(np.arange(n)[:, None] + np.arange(1, horizon + 1), n - 1)
            chunk = np.concatenate(
                [P.encode(P.relative_chunks(pose, horizon)), jaw[index][..., None]], -1
            )  # [N, H, 10]
            acts.append(chunk)
        prev = np.concatenate([pose[:1], pose[:-1]])
        states.append(
            np.concatenate([P.encode(P.inverse(pose) @ prev), jaw[:, None]], 1)
        )
        firsts.append(pose)
    if action == "delta":
        act = np.concatenate(acts, 1)
    else:  # [N, H, hands * 10], k-major
        act = np.concatenate(acts, -1).reshape(len(acts[0]), -1)
    pairs = [P.encode(P.inverse(firsts[0]) @ other) for other in firsts[1:]]
    state = np.concatenate([*states, *pairs], 1)
    return act.astype(np.float32), state.astype(np.float32)


def convert(
    source: str | Path,
    output: str | Path,
    repo_id: str,
    action: str = "delta",
    horizon: int = 16,
    hands: Sequence[str] | None = None,
    max_gap: int = 3,
    source_repo_id: str | None = None,
) -> Report:
    if action not in ACTIONS:
        raise ConfigError(f"action must be one of {ACTIONS}, not {action!r}")
    if horizon < 1 or max_gap < 0:
        raise ConfigError("horizon must be >= 1 and max_gap >= 0")
    try:
        from lerobot.datasets import LeRobotDataset
        from lerobot.datasets.dataset_tools import (
            delete_episodes,
            modify_features,
            recompute_stats,
        )
    except ImportError as exc:
        raise ConfigError(
            f"converting needs lerobot ({exc}); install roboloom with the record "
            "extra (uv add git+https://github.com/tetsugo02/roboloom.git --extra "
            "record; in a roboloom checkout: uv sync --extra record)"
        ) from exc
    source, output = Path(source).resolve(), Path(output).resolve()
    if not (source / "meta" / "info.json").exists():
        raise ConfigError(f"{source}: not a LeRobot dataset (no meta/info.json)")
    if output.exists():
        raise ConfigError(f"{output} exists; choose another --output or move it")
    dataset = LeRobotDataset(source_repo_id or f"local/{source.name}", root=source)
    features = dataset.meta.features
    if "action" in features:
        raise ConfigError(
            f"{source} already has an action: it is not a hand-held recording (a "
            "configuration without followers)"
        )
    found = hands_of(features)
    chosen = list(hands) if hands else found
    unknown = [h for h in chosen if h not in found]
    if not chosen or unknown:
        raise ConfigError(
            f"hands {unknown or chosen} are not recorded poses; the recording has "
            f"{found or 'none'}"
        )

    columns = {h: np.stack(dataset.hf_dataset[f"observation.{h}"]) for h in chosen}
    episode = np.asarray(dataset.hf_dataset["episode_index"]).ravel()
    order = np.argsort(np.asarray(dataset.hf_dataset["index"]).ravel(), kind="stable")
    report = Report(output, 0, 0)
    actions, states = [], []
    for ep in dict.fromkeys(episode[order].tolist()):
        at = order[episode[order] == ep]
        rows: dict[str, np.ndarray] = {}
        problem = None
        for h in chosen:
            raw = columns[h][at].astype(float)
            pose, filled, problem = P.fill_gaps(*recorded_poses(raw), max_gap)
            if problem:
                problem = f"{h}: {problem}"
                break
            rows[h], rows[f"{h}.pose"] = raw, pose
            report.filled_rows += filled
        if problem:
            report.dropped[int(ep)] = problem
            continue
        act, state = episode_arrays(rows, chosen, action, horizon)
        actions.append(act)
        states.append(state)
    if not actions:
        raise ConfigError(
            f"no episode is usable: {'; '.join(report.dropped.values()) or 'empty'}"
        )

    staging = output.with_name(f".{output.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    try:
        kept = dataset
        if report.dropped:
            kept = delete_episodes(
                dataset,
                sorted(report.dropped),
                output_dir=staging,
                repo_id=f"{repo_id}-staging",
            )
        act_names, state_names = _names(chosen, action, horizon)
        result = modify_features(
            kept,
            add_features={
                "action": (
                    np.concatenate(actions),
                    {
                        "dtype": "float32",
                        "shape": (len(act_names),),
                        "names": act_names,
                    },
                ),
                "observation.state": (
                    np.concatenate(states),
                    {
                        "dtype": "float32",
                        "shape": (len(state_names),),
                        "names": state_names,
                    },
                ),
            },
            output_dir=output,
            repo_id=repo_id,
        )
        result = recompute_stats(result)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    meta: dict[str, Any] = {
        "action": action,
        "horizon": horizon if action == "relative-chunk" else 1,
        "hands": chosen,
        "pose": list(P.POSE_NAMES),
        "rotation": "6d: the first two columns of the rotation matrix",
        "fps": dataset.meta.fps,
        "max_gap": max_gap,
        "source": str(source),
        "dropped_episodes": report.dropped,
    }
    (output / METADATA).write_text(json.dumps(meta, indent=2) + "\n")
    report.episodes, report.frames = result.num_episodes, result.num_frames
    return report


def read_metadata(root: str | Path) -> dict[str, Any]:
    """How a converted dataset was made (for turning a policy's output into poses)."""
    return json.loads((Path(root) / METADATA).read_text())
