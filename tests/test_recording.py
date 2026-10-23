import time

import numpy as np

from roboloom.config import load_experiment
from roboloom.core.protocol import Envelope
from roboloom.recording import EpisodeRecorder

MS = 1_000_000


def msg(kind, seq, capture, ready, receive, payload, source="robot"):
    return Envelope(
        kind, source, "boot", seq, capture, ready, payload, t_receive_ns=receive
    )


def action(seq, t, value=2050):
    return msg(
        "action",
        seq,
        t,
        t,
        t + MS,
        {"valid": True, "positions": [value] * 17, "command_seq": seq, "t_sent_ns": t},
    )


def test_causal_selection_and_next_action():
    cfg = load_experiment("examples/mock/experiment.yaml")
    recorder = EpisodeRecorder(cfg)
    t = time.monotonic_ns()
    recorder.start("handover", t, write=False)
    recorder.ingest(
        "robot",
        msg("robot_state", 0, t - MS, t - MS, t - MS, {"positions": [2048] * 17}),
    )
    recorder.ingest(
        "robot", msg("robot_state", 1, t - MS, t + 1, t + 1, {"positions": [3000] * 17})
    )
    recorder.ingest("action", action(2, t + 20 * MS))
    recorder.stop(t + 100 * MS)
    row = recorder.frames()[0]
    assert row["observation.state"][0] == 2048
    assert row["action"][0] == 2050
    assert row["action.valid"][0] == 1
    assert row["observation.meta.camera.valid"][0] == 0
    assert np.count_nonzero(row["observation.images.camera"]) == 0


class FakeDataset:
    def __init__(self):
        self.frames, self.episodes = [], 0

    def add_frame(self, row):
        self.frames.append(row)

    def save_episode(self):
        self.episodes += 1

    def has_pending_frames(self):
        return bool(self.frames)

    def clear_episode_buffer(self):
        self.frames.clear()


def test_streaming_rows_watermark_preroll_and_pruning():
    cfg = load_experiment("examples/mock/experiment.yaml")  # 10 fps -> 100 ms rows
    dataset = FakeDataset()
    recorder = EpisodeRecorder(cfg, dataset=dataset, grace_ms=500)
    t = time.monotonic_ns()
    recorder.ingest(
        "robot",
        msg(
            "robot_state",
            0,
            t - 5 * MS,
            t - 5 * MS,
            t - 5 * MS,
            {"positions": [2000] * 17},
        ),
    )  # pre-roll
    recorder.start("task", t)
    for k in range(30):
        tick = t + k * 33 * MS
        recorder.ingest(
            "robot",
            msg(
                "robot_state",
                k + 1,
                tick,
                tick,
                tick + MS,
                {"positions": [2048 + k] * 17},
            ),
        )
        recorder.ingest("action", action(k, tick, 2048 + k))
        recorder.poll(tick + MS)
    assert len(dataset.frames) >= 8  # rows closed by the action watermark, not by grace
    first = dataset.frames[0]
    assert (
        first["observation.state"][0] == 2000
        and first["observation.meta.robot.valid"][0] == 1
    )
    assert first["action"][0] == 2048
    assert len(recorder.samples["robot"]) < 10 and len(recorder.samples["action"]) < 10
    recorder.stop(t + 1000 * MS)
    assert recorder.written == 10
    metrics = recorder.metrics()
    assert metrics["rows"] == 10 and metrics["action_valid_rate"] > 0.5
    assert recorder.save() == 10 and dataset.episodes == 1


def test_discard_mid_episode_clears_written_rows():
    cfg = load_experiment("examples/mock/experiment.yaml")
    dataset = FakeDataset()
    recorder = EpisodeRecorder(cfg, dataset=dataset)
    t = time.monotonic_ns()
    recorder.start("task", t)
    recorder.ingest("action", action(0, t + 250 * MS))
    recorder.poll(t + 260 * MS)
    assert dataset.frames
    recorder.discard()
    assert not dataset.frames and not recorder.active
