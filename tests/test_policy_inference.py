"""Policies the configuration checks at load (`bind`), and LeRobot checkpoints."""

from __future__ import annotations

import sys

import numpy as np
import pytest

from roboloom.config import load_config
from roboloom.errors import ConfigError

MOCK = ".roboloom/piper-mock/config.yaml"


def mock_policy_controller():
    return load_config(MOCK, options=["policy"]).controllers["policy"]


def test_the_spec_has_the_recorded_observation_and_action():
    from roboloom.recording.schema import features

    controller = mock_policy_controller()
    spec = controller.spec()
    cfg = load_config(MOCK, options=["policy"])
    recorded = {
        k: v
        for k, v in features(cfg).items()
        if k.startswith("observation.") and not k.startswith("observation.meta.")
    }
    # the policy observes every recorded source here, so it sees every recorded feature
    assert {k: tuple(v["shape"]) for k, v in spec.observation.items()} == {
        k: tuple(v["shape"]) for k, v in recorded.items()
    }
    assert tuple(spec.observation["observation.images.left_wrist"]["shape"]) == (
        48,
        64,
        3,
    )
    assert (
        spec.action[0] == "left.joint1" and spec.action[-1] == "right_gripper.gripper"
    )
    assert len(spec.action) == spec.observation["observation.state"]["shape"][0] == 14


def test_a_policy_with_bind_checks_the_configuration_at_load(tmp_path, monkeypatch):
    (tmp_path / "bound_policy_for_test.py").write_text(
        "from roboloom.policy import Hold\n"
        "class Picky(Hold):\n"
        "    def __init__(self, needs):\n"
        "        super().__init__(); self.needs = needs; self.spec = None\n"
        "    def bind(self, spec):\n"
        "        if self.needs not in spec.observation:\n"
        "            raise ValueError(f'{self.needs} is not observed')\n"
        "        self.spec = spec\n"
        "def make(needs):\n"
        "    return Picky(needs)\n"
    )
    monkeypatch.setattr(sys, "path", [*sys.path, str(tmp_path)])
    controller = mock_policy_controller()
    controller.load(
        "bound_policy_for_test:make", {"needs": "observation.images.camera"}
    )
    assert controller.state == "ready" and controller.policy.spec.rate_hz == 10
    refused = mock_policy_controller()
    with pytest.raises(ValueError, match="left_sense is not observed"):
        refused.load("bound_policy_for_test:make", {"needs": "observation.left_sense"})
    assert refused.policy is None  # the node shows the reason; start is refused
    with pytest.raises(RuntimeError):
        refused.start("task")


def test_a_policy_without_bind_loads_as_before():
    controller = mock_policy_controller()
    controller.load()  # demo_policy:wave from the robot's directory
    assert controller.state == "ready"
    controller.load("roboloom.policy:hold", {})
    assert controller.state == "ready"


# -- LeRobot -------------------------------------------------------------------------


@pytest.fixture(scope="module")
def act_checkpoint(tmp_path_factory):
    """An untrained, tiny ACT for the mock (state 14, the left wrist camera), on CPU."""
    pytest.importorskip("lerobot.policies.act.modeling_act")
    from lerobot.configs.types import FeatureType, PolicyFeature
    from lerobot.policies.act.configuration_act import ACTConfig
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors

    path = tmp_path_factory.mktemp("act") / "pretrained_model"
    cfg = ACTConfig(
        input_features={
            "observation.state": PolicyFeature(FeatureType.STATE, (14,)),
            "observation.images.wrist": PolicyFeature(FeatureType.VISUAL, (3, 48, 64)),
            # LeRobot's training lists every observation.* of a roboloom dataset; its
            # policies read none of these
            "observation.left_sense": PolicyFeature(FeatureType.STATE, (10,)),
            "observation.meta.left.valid": PolicyFeature(FeatureType.STATE, (1,)),
        },
        output_features={
            "action": PolicyFeature(FeatureType.ACTION, (14,)),
            "action.valid": PolicyFeature(FeatureType.ACTION, (1,)),
        },
        dim_model=32,
        n_heads=2,
        dim_feedforward=64,
        n_encoder_layers=1,
        n_decoder_layers=1,
        chunk_size=4,
        n_action_steps=4,
        pretrained_backbone_weights=None,
        use_vae=False,
        device="cpu",
    )

    def stats(shape, low=-1.0):
        return {
            "mean": np.zeros(shape),
            "std": np.full(shape, 0.01),  # small actions: the mock arms barely move
            "min": np.full(shape, low),
            "max": np.ones(shape),
        }

    pre, post = make_pre_post_processors(
        cfg,
        dataset_stats={
            "observation.state": stats(14),
            "action": stats(14),
            "observation.images.wrist": stats((3, 1, 1), 0.0),
        },
    )
    for part in (ACTPolicy(cfg), pre, post):
        part.save_pretrained(path)
    return str(path)


RENAME = {"observation.images.wrist": "observation.images.left_wrist"}


def test_a_lerobot_checkpoint_is_checked_against_the_configuration(act_checkpoint):
    from roboloom.policy.lerobot import load

    spec = mock_policy_controller().spec()
    load(act_checkpoint, device="cpu", rename=RENAME).bind(spec)
    with pytest.raises(ConfigError, match=r"observation.images.wrist is not observed"):
        load(act_checkpoint, device="cpu").bind(spec)
    with pytest.raises(ConfigError, match="does not take"):
        load(act_checkpoint, device="cpu", rename={"observation.images.top": "x"})
    with pytest.raises(ConfigError, match="mode"):
        load(act_checkpoint, device="cpu", mode="async")
    small = type(spec)(
        observation={
            **spec.observation,
            "observation.images.left_wrist": {"dtype": "video", "shape": (96, 128, 3)},
        },
        action=spec.action[:12],
        rate_hz=spec.rate_hz,
        dataset_fps=spec.dataset_fps,
    )
    with pytest.raises(ConfigError, match=r"\(3, 96, 128\).*12 entries"):
        load(act_checkpoint, device="cpu", rename=RENAME).bind(small)


def test_a_lerobot_policy_infers_one_step_or_a_chunk(act_checkpoint):
    from roboloom.policy.lerobot import load

    observation = {
        "observation.state": np.zeros(14, np.float32),
        "observation.images.left_wrist": np.zeros((48, 64, 3), np.uint8),
        "observation.images.camera": np.zeros((48, 64, 3), np.uint8),
        "task": "pick",
    }
    step = load(act_checkpoint, device="cpu", rename=RENAME)
    step.reset()
    first = step.infer(observation)
    assert first.shape == (14,) and np.isfinite(first).all()
    assert len(step.model._action_queue) == 3  # LeRobot keeps the rest of its chunk
    step.reset()
    assert len(step.model._action_queue) == 0
    chunk = load(act_checkpoint, device="cpu", rename=RENAME, mode="chunk")
    chunk.reset()
    assert chunk.infer(observation).shape == (4, 14)


def test_a_lerobot_policy_drives_the_mock(act_checkpoint, tmp_path):
    import shutil

    from roboloom.runtime.session import Session

    project = tmp_path / ".roboloom" / "piper-mock"
    shutil.copytree(
        ".roboloom/piper-mock",
        project,
        ignore=shutil.ignore_patterns("datasets", "__pycache__"),
    )
    with Session.launch(
        project / "config.yaml",
        options=["policy"],
        policy="roboloom.policy.lerobot:load",
        policy_kwargs={"path": act_checkpoint, "device": "cpu", "rename": RENAME},
        log_dir=tmp_path / "logs",
    ) as s:
        s.wait_ready(60)
        result = s.record("pick", 2.0)
        status = s.status()["policy"]["fields"]
    assert result.saved, result
    assert result.metrics["action_valid_rate"] > 0.5, result.metrics
    assert status["state"] in ("running", "ready") and "infer_ms" in status, status


def test_a_failed_controller_says_why_instead_of_asking_to_wait():
    import time

    from roboloom.runtime.node import start_warning

    cfg = load_config(MOCK, options=["policy"])
    now = time.monotonic_ns()
    latest = {
        "policy": {
            "t_ns": now,
            "fields": {"state": "failed", "error": "loading the policy: no camera"},
        }
    }
    warning = start_warning(cfg, latest, now)
    assert warning == "policy: controller failed: loading the policy: no camera"


def test_a_recorded_mock_dataset_trains_a_lerobot_policy_that_loads(tmp_path):
    """The path of `lerobot-train` (LeRobot 0.6.1) on a dataset roboloom recorded: the
    metadata and stats it reads, a training step, and the checkpoint back in roboloom."""
    pytest.importorskip("lerobot.policies.act.modeling_act")
    import shutil

    import torch
    from lerobot.datasets import LeRobotDataset, LeRobotDatasetMetadata
    from lerobot.datasets.factory import resolve_delta_timestamps
    from lerobot.policies import make_policy, make_pre_post_processors
    from lerobot.policies.act.configuration_act import ACTConfig

    from roboloom.policy.lerobot import load
    from roboloom.runtime.session import Session

    project = tmp_path / ".roboloom" / "piper-mock"
    shutil.copytree(
        ".roboloom/piper-mock",
        project,
        ignore=shutil.ignore_patterns("datasets", "logs", "__pycache__"),
    )
    with Session.launch(project / "config.yaml", log_dir=tmp_path / "logs") as s:
        s.wait_ready(60)
        assert s.record("pick", 4.0, home=True).saved  # the mock Senses teleoperate
    root = project / "datasets" / "piper-mock"

    cfg = ACTConfig(
        dim_model=32,
        n_heads=2,
        dim_feedforward=64,
        n_encoder_layers=1,
        n_decoder_layers=1,
        chunk_size=4,
        n_action_steps=4,
        pretrained_backbone_weights=None,
        device="cpu",
    )
    meta = LeRobotDatasetMetadata("local/piper-mock", root=root)
    dataset = LeRobotDataset(
        "local/piper-mock",
        root=root,
        delta_timestamps=resolve_delta_timestamps(cfg, meta),
    )
    policy = make_policy(cfg, ds_meta=meta)
    pre, post = make_pre_post_processors(cfg, dataset_stats=meta.stats)
    # every observation.* is an input, as in lerobot-train; ACT reads state and images
    assert "observation.meta.left.seq" in cfg.input_features
    assert cfg.output_features["action"].shape == (14,)
    batch = pre(next(iter(torch.utils.data.DataLoader(dataset, batch_size=4))))
    loss, _ = policy.forward(batch)
    loss.backward()
    assert torch.isfinite(loss)

    path = tmp_path / "pretrained_model"
    for part in (policy, pre, post):
        part.save_pretrained(path)
    trained = load(str(path), device="cpu")
    trained.bind(mock_policy_controller().spec())  # same names: no rename needed
    trained.reset()
    frame = dataset.hf_dataset[0]
    observation = {
        "observation.state": np.asarray(frame["observation.state"], np.float32),
        **{
            f"observation.images.{name}": np.zeros((48, 64, 3), np.uint8)
            for name in ("camera", "left_wrist", "right_wrist")
        },
        "task": "pick",
    }
    assert trained.infer(observation).shape == (14,)
