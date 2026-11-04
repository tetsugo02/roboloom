"""LeRobot checkpoints as roboloom policies (`roboloom.policy.lerobot:load`).

    type: policy
    factory: roboloom.policy.lerobot:load
    kwargs:
      path: outputs/train/act_piper/checkpoints/last/pretrained_model  # or a hub repo id
      device: auto          # cuda when available, else cpu
      mode: step            # step: select_action, one step per call (action_horizon: 1)
                            # chunk: predict_action_chunk, [H, n] per call
      rename: {}            # {checkpoint feature: roboloom feature}

Loading follows LeRobot 0.6.1's own rollout: the config and weights from the checkpoint,
then its saved pre- and post-processors, which hold the normalization statistics.
`bind` checks the checkpoint's input and output features against what the configuration
observes and drives, so a policy trained on other cameras or joints is refused at load.

`mode: step` lets the LeRobot policy keep its own action queue and observation history,
as LeRobot's rollout does; it is right for every policy type (Diffusion needs the
history). `mode: chunk` returns the whole predicted chunk for roboloom's
`action_horizon`; it skips the history, so use it only for single-frame policies (ACT).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from ..errors import ConfigError
from . import PolicySpec

MODES = ("step", "chunk")
# besides the images, the inputs LeRobot policies read (robot_state_feature, env_state)
READ = ("observation.state", "observation.environment_state")


def _import():
    try:
        import torch
        from lerobot.configs.policies import PreTrainedConfig
        from lerobot.policies.factory import get_policy_class, make_pre_post_processors
        from lerobot.policies.utils import prepare_observation_for_inference
    except ImportError as exc:
        raise ConfigError(
            f"LeRobot policies need lerobot with torch ({exc}); install "
            "`roboloom[policy]` (in this repository: uv sync --extra policy). Policy "
            "types such as diffusion or smolvla need lerobot's own extra as well."
        ) from exc
    return (
        torch,
        PreTrainedConfig,
        get_policy_class,
        make_pre_post_processors,
        prepare_observation_for_inference,
    )


def _device(torch: Any, device: str) -> str:
    if device != "auto":
        return device
    return "cuda" if torch.cuda.is_available() else "cpu"


class LeRobotPolicy:
    def __init__(
        self,
        path: str,
        *,
        device: str = "auto",
        mode: str = "step",
        rename: Mapping[str, str] | None = None,
        revision: str | None = None,
    ):
        if mode not in MODES:
            raise ConfigError(
                f"lerobot policy: mode must be one of {MODES}, not {mode!r}"
            )
        if rename is not None and not (
            isinstance(rename, Mapping)
            and all(
                isinstance(k, str) and isinstance(v, str) for k, v in rename.items()
            )
        ):
            raise ConfigError(
                "lerobot policy: rename maps checkpoint feature names to roboloom ones"
            )
        torch, config_cls, policy_class, processors, prepare = _import()
        self.torch, self.prepare, self.mode = torch, prepare, mode
        self.path = str(path)
        self.device = _device(torch, device)
        cfg = config_cls.from_pretrained(self.path, revision=revision)
        cfg.pretrained_path = self.path
        cfg.device = self.device
        self.config = cfg
        self.model = (
            policy_class(cfg.type)
            .from_pretrained(self.path, config=cfg, revision=revision)
            .to(self.device)
            .eval()
        )
        self.pre, self.post = processors(
            cfg,
            pretrained_path=self.path,
            pretrained_revision=revision,
            preprocessor_overrides={"device_processor": {"device": self.device}},
        )
        # checkpoint feature -> roboloom feature
        self.sources = {key: (rename or {}).get(key, key) for key in self.inputs()}
        unknown = set(rename or {}) - set(self.sources)
        if unknown:
            raise ConfigError(
                f"lerobot policy: rename names {sorted(unknown)}, which the checkpoint "
                f"does not take (it takes {sorted(self.sources)})"
            )

    def inputs(self) -> dict[str, tuple[str, tuple[int, ...]]]:
        """The checkpoint's input features the policy reads -> (type, shape).

        LeRobot's training lists every `observation.*` of the dataset as an input
        (`observation.meta.*`, `observation.effort`, a Sense's pose, ...), but its
        policies read only the robot state, the images and the environment state."""
        out = {}
        for key, f in self.config.input_features.items():
            kind = str(getattr(f.type, "value", f.type))
            if kind == "VISUAL" or key in READ:
                out[key] = (kind, tuple(f.shape))
        return out

    def action_size(self) -> int:
        feature = self.config.output_features.get("action")
        if feature is None:
            raise ConfigError(
                f"lerobot policy {self.path}: the checkpoint has no action"
            )
        return int(np.prod(feature.shape))

    def bind(self, spec: PolicySpec) -> None:
        problems = []
        for key, (kind, shape) in self.inputs().items():
            source = self.sources[key]
            given = spec.observation.get(source)
            named = key if source == key else f"{key} (from {source})"
            if given is None:
                problems.append(f"{named} is not observed")
                continue
            have = tuple(given["shape"])
            if kind == "VISUAL":  # LeRobot keeps images as [c, h, w]
                have = (have[2], have[0], have[1]) if len(have) == 3 else have
            if have != shape:
                problems.append(f"{named} has shape {have}, the checkpoint {shape}")
        if self.action_size() != len(spec.action):
            problems.append(
                f"the action has {len(spec.action)} entries "
                f"({', '.join(spec.action)}), the checkpoint {self.action_size()}"
            )
        if problems:
            available = sorted(spec.observation)
            raise ConfigError(
                f"lerobot policy {self.path} does not fit this configuration: "
                + "; ".join(problems)
                + f". Observed: {', '.join(available)} (add the missing sources to "
                "`observe:`, or map names with kwargs.rename)"
            )

    def reset(self) -> None:
        self.model.reset()
        self.pre.reset()
        self.post.reset()

    def infer(self, observation: dict[str, Any]) -> np.ndarray:
        batch = {
            key: np.array(observation[source], copy=True)
            for key, source in self.sources.items()
        }
        with self.torch.inference_mode():
            batch = self.prepare(batch, self.device, observation.get("task") or None)
            batch = self.pre(batch)
            if self.mode == "step":
                action = self.model.select_action(batch)
            else:
                action = self.model.predict_action_chunk(batch)
            action = self.post(action)
        out = action.squeeze(0).detach().to("cpu").numpy()
        return out.astype(np.float64)


def load(path: str, **kwargs: Any) -> LeRobotPolicy:
    """`roboloom.policy.lerobot:load`: a LeRobot checkpoint (local directory or hub id)."""
    return LeRobotPolicy(path, **kwargs)
