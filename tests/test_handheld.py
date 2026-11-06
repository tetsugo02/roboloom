"""Hand-held collection: a configuration without followers, and its conversion."""

from __future__ import annotations

import json
import shutil
import time

import numpy as np
import pytest
import yaml

from roboloom.config import load_config
from roboloom.core.protocol import Envelope
from roboloom.errors import ConfigError
from roboloom.handheld import poses as P
from roboloom.kinematics.spec import pose_xyz_rpy
from roboloom.recording import features
from roboloom.recording.recorder import EpisodeRecorder
from roboloom.runtime.flow import build_flow

MOCK = ".roboloom/pika-handheld-mock"
MS = 1_000_000


def trajectory(n: int = 30) -> np.ndarray:
    t = np.linspace(0, 2 * np.pi, n)
    return np.stack(
        [
            pose_xyz_rpy(
                (0.1 * np.sin(s), 0.05 * np.cos(s), 0.02 * s),
                (0.4 * np.sin(s), 0.3 * np.cos(2 * s), 0.2 * s),
            )
            for s in t
        ]
    )


# -- poses ---------------------------------------------------------------------------


def test_6d_rotations_and_poses_round_trip():
    poses = trajectory()
    assert np.allclose(P.from_rot6d(P.rot6d(poses[:, :3, :3])), poses[:, :3, :3])
    assert np.allclose(P.decode(P.encode(poses)), poses)
    assert np.allclose(P.inverse(poses) @ poses, np.eye(4), atol=1e-12)


def test_deltas_and_chunks_give_back_the_trajectory_from_the_observed_pose():
    poses = trajectory()
    t, h = 5, 6
    steps = P.encode(P.deltas(poses))[t : t + h]
    assert np.allclose(P.targets_from_deltas(poses[t], steps), poses[t + 1 : t + 1 + h])
    chunk = P.encode(P.relative_chunks(poses, h))[t]
    assert np.allclose(P.targets_from_chunk(poses[t], chunk), poses[t + 1 : t + 1 + h])
    assert np.allclose(P.deltas(poses)[-1], np.eye(4))  # no next pose: stay
    last = P.relative_chunks(poses, h)[-2]  # past the end: the last pose
    assert np.allclose(poses[-2] @ last[-1], poses[-1])


def test_short_tracking_gaps_are_filled_and_long_ones_reported():
    poses = trajectory(20)
    tracked = np.ones(20, bool)
    tracked[[0, 7, 8, 19]] = False
    filled, count, problem = P.fill_gaps(poses, tracked, max_gap=2)
    assert problem is None and count == 4
    assert np.allclose(filled[0], poses[1]) and np.allclose(filled[19], poses[18])
    assert np.allclose(
        filled[7, :3, 3], poses[6, :3, 3] + (poses[9, :3, 3] - poses[6, :3, 3]) / 3
    )
    r = filled[8, :3, :3]
    assert np.allclose(r @ r.T, np.eye(3), atol=1e-9)
    tracked[10:14] = False
    _, _, problem = P.fill_gaps(poses, tracked, max_gap=2)
    assert problem == "tracking lost for 4 rows from row 10"
    assert P.fill_gaps(poses, np.zeros(20, bool), 2)[2] == "never tracked"


# -- a configuration without followers ------------------------------------------------


def copy_mock(tmp_path):
    project = tmp_path / ".roboloom" / "pika-handheld-mock"
    shutil.copytree(
        MOCK, project, ignore=shutil.ignore_patterns("datasets", "logs", "__pycache__")
    )
    return project


def test_a_configuration_without_followers_records_inputs_and_sensors():
    cfg = load_config(f"{MOCK}/config.yaml")
    assert not cfg.followers and not cfg.controllers
    names = features(cfg)
    assert not any(k.startswith("action") for k in names)
    assert "observation.state" not in names
    assert names["observation.left_sense"]["names"][-2:] == ["tracking", "engaged"]
    nodes = {n["id"]: n for n in build_flow(cfg)["nodes"]}
    assert set(nodes) >= {"left_sense", "right_sense", "left_wrist", "recorder"}


def test_without_followers_controllers_and_unpaced_inputs_are_refused(tmp_path):
    project = copy_mock(tmp_path)
    sense = project / "nodes" / "left_sense.yaml"
    tree = yaml.safe_load(sense.read_text())
    del tree["poll_hz"]
    sense.write_text(yaml.safe_dump(tree))
    with pytest.raises(
        ValueError, match="left_sense: without followers, set the polling"
    ):
        load_config(project / "config.yaml")
    tree["poll_hz"] = 100
    sense.write_text(yaml.safe_dump(tree))
    config = yaml.safe_load((project / "config.yaml").read_text())
    config["controllers"] = {"ik": "nodes/ik.yaml"}
    (project / "nodes" / "ik.yaml").write_text(
        yaml.safe_dump({"type": "pose_ik", "input": "left_sense", "followers": ["x"]})
    )
    (project / "config.yaml").write_text(yaml.safe_dump(config))
    with pytest.raises(ValueError, match="must reference|nothing for controllers"):
        load_config(project / "config.yaml")


def test_rows_without_followers_close_with_time():
    cfg = load_config(f"{MOCK}/config.yaml")

    class Rows:
        def __init__(self):
            self.frames = []

        def add_frame(self, row):
            self.frames.append(row)

    rows = Rows()
    recorder = EpisodeRecorder(cfg, rows)
    t = time.monotonic_ns()
    recorder.start("pick", t)
    payload = {
        "position": [0.1, 0.0, 0.2],
        "quaternion": [0.0, 0.0, 0.0, 1.0],
        "frame": "libsurvive",
        "gripper": 0.5,
        "tracking": False,
        "engaged": True,
    }
    recorder.ingest(
        "left_sense",
        Envelope("pose_intent", "left_sense", "b", 0, t, t, payload, t_receive_ns=t),
    )
    assert recorder.poll(t + 50 * MS) == 0  # row 0 is open until t + 100 ms
    assert recorder.poll(t + 250 * MS) == 2  # no follower stream to wait for
    row = rows.frames[0]
    assert not any(k.startswith("action") for k in row)
    assert row["observation.left_sense"].tolist()[-3:] == [0.5, 0.0, 1.0]
    recorder.stop(t + 300 * MS)
    metrics = recorder.metrics()
    assert "action_valid_rate" not in metrics and metrics["rows"] == 3


# -- record, convert, train ------------------------------------------------------------


@pytest.mark.skipif(shutil.which("dora") is None, reason="needs dora")
def test_a_handheld_recording_converts_and_trains(tmp_path):
    pytest.importorskip("lerobot.policies.act.modeling_act")
    import torch
    from lerobot.datasets import LeRobotDataset, LeRobotDatasetMetadata
    from lerobot.datasets.factory import resolve_delta_timestamps
    from lerobot.policies import make_policy, make_pre_post_processors
    from lerobot.policies.act.configuration_act import ACTConfig

    from roboloom.handheld.convert import convert, read_metadata
    from roboloom.runtime.session import Session

    project = copy_mock(tmp_path)
    with Session.launch(project / "config.yaml", log_dir=tmp_path / "logs") as s:
        s.wait_ready(60)
        result = s.record("pick", 3.0)
    assert result.saved and "action_valid_rate" not in result.metrics, result
    source = project / "datasets" / "pika-handheld-mock"

    with pytest.raises(ConfigError, match="not recorded poses"):
        convert(source, tmp_path / "x", "local/x", hands=["camera"])
    chunk = convert(
        source, tmp_path / "chunk", "local/chunk", action="relative-chunk", horizon=4
    )
    info = json.loads((tmp_path / "chunk/meta/info.json").read_text())["features"]
    assert info["action"]["shape"] == [4 * 2 * 10]
    assert info["action"]["names"][:2] == ["k01.left_sense.x", "k01.left_sense.y"]
    assert read_metadata(chunk.output)["horizon"] == 4

    report = convert(source, tmp_path / "delta", "local/delta")
    assert report.episodes == 1 and not report.dropped
    meta = LeRobotDatasetMetadata("local/delta", root=report.output)
    assert meta.features["action"]["shape"] == (20,)
    assert meta.features["observation.state"]["shape"] == (
        29,
    )  # 2 x 10 + right from left
    assert "action" in meta.stats and "observation.state" in meta.stats
    with pytest.raises(ConfigError, match="exists"):
        convert(source, tmp_path / "delta", "local/delta")

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
    dataset = LeRobotDataset(
        "local/delta",
        root=report.output,
        delta_timestamps=resolve_delta_timestamps(cfg, meta),
    )
    policy = make_policy(cfg, ds_meta=meta)
    pre, _ = make_pre_post_processors(cfg, dataset_stats=meta.stats)
    batch = pre(next(iter(torch.utils.data.DataLoader(dataset, batch_size=4))))
    loss, _ = policy.forward(batch)
    assert torch.isfinite(loss)


def test_rows_recorded_without_a_sample_count_as_untracked():
    from roboloom.handheld.convert import recorded_poses

    rows = np.zeros((6, 10))
    rows[:, 6] = 1.0  # qw
    rows[:, 0] = np.arange(6) * 0.1
    rows[:, 8] = 1.0  # tracking
    rows[2] = 0.0  # no fresh sample: every value is zero
    rows[4, 8] = 0.0  # untracked (the pose is the last tracked one)
    poses, tracked = recorded_poses(rows)
    assert tracked.tolist() == [True, True, False, True, False, True]
    filled, count, problem = P.fill_gaps(poses, tracked, max_gap=1)
    assert problem is None and count == 2
    assert np.isclose(filled[2, 0, 3], 0.2) and np.allclose(
        filled[2, :3, :3], np.eye(3)
    )
    rows[1:5] = 0.0
    _, _, problem = P.fill_gaps(*recorded_poses(rows), max_gap=3)
    assert problem == "tracking lost for 4 rows from row 1"
