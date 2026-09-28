import time

import numpy as np

from roboloom.config import load_experiment
from roboloom.protocol import Envelope
from roboloom.recording import EpisodeRecorder


def msg(kind, seq, capture, ready, receive, payload):
    return Envelope(kind, kind, "boot", seq, capture, ready, payload, t_receive_ns=receive)


def test_causal_selection_and_next_action():
    cfg = load_experiment("examples/mock/experiment.yaml")
    recorder = EpisodeRecorder(cfg)
    t = time.monotonic_ns()
    recorder.start("handover", t)
    recorder.ingest(msg("robot", 0, t - 1_000_000, t - 1_000_000, t - 1_000_000, {"positions": [2048] * 17}))
    recorder.ingest(msg("robot", 1, t - 1_000_000, t + 1, t + 1, {"positions": [3000] * 17}))
    recorder.ingest(msg("action", 2, t + 20_000_000, t + 20_000_000, t + 21_000_000, {"valid": True, "positions": [2050] * 17, "command_seq": 4, "t_sent_ns": t + 20_000_000}))
    recorder.stop(t + 100_000_000)
    row = recorder.frames()[0]
    assert row["observation.state"][0] == 2048
    assert row["action"][0] == 2050
    assert row["action.valid"][0] == 1
    assert row["observation.meta.camera.valid"][0] == 0
    assert np.count_nonzero(row["observation.images.camera"]) == 0
