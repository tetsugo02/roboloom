"""A small custom policy, from a roboloom recording to `roboloom infer`.

Not a good model: a template that shows where each model-specific step goes. It reads
the joint state only (no images), so it trains on a CPU in seconds.

    # train (needs torch and lerobot: the `policy` extra)
    uv run python examples/policies/chunk_mlp.py train \
        --dataset .roboloom/rakuda2/datasets/rakuda2 --out outputs/chunk_mlp.pt \
        --history 4 --horizon 8 --stride 3 --exclude torso_yaw head_yaw head_pitch

    # run (stride 3 on a 15 fps dataset: the policy's rate is 5 Hz)
    PYTHONPATH=examples/policies uv run roboloom infer rakuda2 --seconds 20 \
        --policy chunk_mlp:load --policy-kwargs '{"checkpoint": "outputs/chunk_mlp.pt"}'
    # with rate_hz: 5 in nodes/policy.yaml

What roboloom gives and what the policy does:

- roboloom: `observation["history"]` (the last frames and the actions executed, one per
  action period), the held targets for the joints named in `hold`, interpolation to the
  control rate, speed limits and safety checks.
- this file: which joints the model drives (`exclude`), normalization (min/max from the
  training data, kept in the checkpoint), the model's action form (`delta`: offsets from
  the current state, turned back into absolute targets in `infer`).

`options()` tells the controller the history length, the held joints and the chunk
length from the checkpoint, so nodes/policy.yaml needs only `factory` and `rate_hz`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch
from torch import nn


def build(inputs: int, outputs: int, hidden: int = 256) -> nn.Module:
    return nn.Sequential(
        nn.Linear(inputs, hidden),
        nn.ReLU(),
        nn.Linear(hidden, hidden),
        nn.ReLU(),
        nn.Linear(hidden, outputs),
    )


def scale(x: np.ndarray, low: np.ndarray, high: np.ndarray) -> np.ndarray:
    """Min/max to [-1, 1]; a joint that never moved maps to 0."""
    span = np.where(high > low, high - low, 1.0)
    return 2 * (x - low) / span - 1


def unscale(x: np.ndarray, low: np.ndarray, high: np.ndarray) -> np.ndarray:
    span = np.where(high > low, high - low, 1.0)
    return (x + 1) / 2 * span + low


class ChunkMlp:
    """state history + executed-action history -> a chunk of joint targets."""

    def __init__(self, checkpoint: str, device: str = "cpu"):
        saved = torch.load(checkpoint, map_location="cpu", weights_only=False)
        self.cfg = saved["config"]
        self.stats = {k: np.asarray(v) for k, v in saved["stats"].items()}
        self.keep = list(self.cfg["keep"])  # action entries the model drives
        n, history, horizon = len(self.keep), self.cfg["history"], self.cfg["horizon"]
        self.model = build(2 * n * history, n * horizon).to(device).eval()
        self.model.load_state_dict(saved["model"])
        self.device = device

    def options(self) -> dict:
        names = self.cfg["names"]
        return {
            "observation_history": self.cfg["history"],
            "hold": [n for i, n in enumerate(names) if i not in self.keep],
            "action_horizon": self.cfg["horizon"],
        }

    def bind(self, spec) -> None:
        if tuple(spec.action) != tuple(self.cfg["names"]):
            raise ValueError(
                f"trained on {self.cfg['names']}, the configuration drives {spec.action}"
            )
        if abs(spec.rate_hz - self.cfg["rate_hz"]) > 1e-6:
            raise ValueError(
                f"trained at {self.cfg['rate_hz']:g} Hz; set rate_hz (not {spec.rate_hz:g})"
            )

    def reset(self) -> None:
        pass  # no state between calls: the history comes from roboloom

    def infer(self, observation: dict) -> np.ndarray:
        history = observation["history"]
        states = history["observation.state"][:, self.keep].astype(np.float64)
        actions = history["action"][:, self.keep].astype(np.float64)
        low, high = self.stats["low"], self.stats["high"]
        x = np.concatenate([scale(states, low, high), scale(actions, low, high)])
        with torch.inference_mode():
            y = self.model(
                torch.as_tensor(x.ravel(), dtype=torch.float32, device=self.device)
            )
        chunk = y.cpu().numpy().astype(np.float64).reshape(self.cfg["horizon"], -1)
        if self.cfg["delta"]:  # offsets from the current state -> absolute targets
            chunk = states[-1] + chunk * self.stats["delta_scale"]
        else:
            chunk = unscale(chunk, low, high)
        out = np.full((len(chunk), len(self.cfg["names"])), np.nan)  # hold: ignored
        out[:, self.keep] = chunk
        return out


def load(checkpoint: str, device: str = "cpu") -> ChunkMlp:
    return ChunkMlp(checkpoint, device)


# -- training -----------------------------------------------------------------------


def episodes(dataset_root: str, stride: int) -> tuple[list[dict], list[str], float]:
    """Each episode's state and action rows (every `stride`-th), the action's names and
    the resulting rate. Rows without a command (`action.valid` 0) are kept: their action
    is the target the follower held."""
    from lerobot.datasets import LeRobotDataset

    root = Path(dataset_root)
    dataset = LeRobotDataset(f"local/{root.name}", root=root)
    table = dataset.hf_dataset
    index = np.asarray(table["index"]).ravel()
    episode = np.asarray(table["episode_index"]).ravel()
    state = np.stack(table["observation.state"]).astype(np.float64)
    action = np.stack(table["action"]).astype(np.float64)
    order = np.argsort(index, kind="stable")
    out = []
    for ep in dict.fromkeys(episode[order].tolist()):
        rows = order[episode[order] == ep][::stride]
        out.append({"state": state[rows], "action": action[rows]})
    names = list(dataset.meta.features["action"]["names"])
    return out, names, dataset.meta.fps / stride


def samples(
    data: list[dict], keep: list[int], history: int, horizon: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(state history, executed-action history, current state, target chunk) per row.

    The history at row t is rows t-history+1 .. t (the first row repeated before the
    episode starts). The action executed before row t is action[t-1]; before the first
    row it is the state there, as roboloom gives the held target. The chunk is
    action[t .. t+horizon-1], the last action repeated past the end."""
    states, actions, current, targets = [], [], [], []
    for ep in data:
        s, a = ep["state"][:, keep], ep["action"][:, keep]
        executed = np.concatenate([s[:1], a[:-1]])
        for t in range(len(s)):
            past = np.clip(np.arange(t - history + 1, t + 1), 0, None)
            future = np.clip(np.arange(t, t + horizon), None, len(a) - 1)
            states.append(s[past])
            actions.append(executed[past])
            current.append(s[t])
            targets.append(a[future])
    return tuple(np.asarray(x) for x in (states, actions, current, targets))  # type: ignore[return-value]


def train(
    dataset: str,
    out: str,
    history: int = 4,
    horizon: int = 8,
    stride: int = 1,
    exclude: tuple[str, ...] = (),
    delta: bool = False,
    steps: int = 500,
    batch_size: int = 64,
    seed: int = 0,
) -> Path:
    torch.manual_seed(seed)
    data, names, rate_hz = episodes(dataset, stride)
    drop = [n for n in names if n.split(".")[-1] in exclude or n in exclude]
    keep = [i for i, n in enumerate(names) if n not in drop]
    states, actions, current, targets = samples(data, keep, history, horizon)
    everything = np.concatenate(
        [states.reshape(-1, len(keep)), targets.reshape(-1, len(keep))]
    )
    low, high = everything.min(axis=0), everything.max(axis=0)
    stats = {"low": low, "high": high}
    x = np.concatenate(
        [scale(states, low, high), scale(actions, low, high)], axis=1
    ).reshape(len(states), -1)
    if delta:
        offsets = targets - current[:, None, :]
        stats["delta_scale"] = np.maximum(np.abs(offsets).max(axis=(0, 1)), 1e-6)
        y = offsets / stats["delta_scale"]
    else:
        y = scale(targets, low, high)
    y = y.reshape(len(targets), -1)
    model = build(x.shape[1], y.shape[1])
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    xs = torch.as_tensor(x, dtype=torch.float32)
    ys = torch.as_tensor(y, dtype=torch.float32)
    for step in range(steps):
        batch = torch.randint(len(xs), (min(batch_size, len(xs)),))
        loss = nn.functional.mse_loss(model(xs[batch]), ys[batch])
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        if step % 100 == 0 or step == steps - 1:
            print(f"step {step}: loss {loss.item():.5f}")
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model": model.state_dict(),
            "stats": {k: v.tolist() for k, v in stats.items()},
            "config": {
                "names": names,
                "keep": keep,
                "history": history,
                "horizon": horizon,
                "rate_hz": rate_hz,
                "delta": delta,
            },
        },
        path,
    )
    print(f"saved {path}: {len(keep)} of {len(names)} joints, {rate_hz:g} Hz")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("train")
    t.add_argument("--dataset", required=True, help="a recorded LeRobotDataset")
    t.add_argument("--out", required=True)
    t.add_argument("--history", type=int, default=4)
    t.add_argument("--horizon", type=int, default=8)
    t.add_argument("--stride", type=int, default=1, help="rate = dataset fps / stride")
    t.add_argument("--exclude", nargs="*", default=[], help="joints left to hold")
    t.add_argument("--delta", action="store_true", help="learn offsets from the state")
    t.add_argument("--steps", type=int, default=500)
    args = parser.parse_args()
    train(
        args.dataset,
        args.out,
        args.history,
        args.horizon,
        args.stride,
        tuple(args.exclude),
        args.delta,
        args.steps,
    )


if __name__ == "__main__":
    main()
