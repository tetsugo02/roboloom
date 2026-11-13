"""Selection before file loading, continuous capture and schema guards."""

import json
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from conftest import mock_project

from roboloom.config import load_config
from roboloom.errors import ConfigError
from roboloom.recording.recorder import EpisodeRecorder
from roboloom.sensors.audio.microphone import MelMono, SoundDeviceReader


def test_selection_skips_files_and_keeps_observe_explicit(tmp_path):
    robot = mock_project(tmp_path)
    (robot / "nodes/camera.yaml").unlink()
    cfg = load_config(robot / "config.yaml", options=["policy"], sensors=[], observe=[])
    assert not cfg.sensors
    with pytest.raises(ConfigError, match="observes unknown"):
        load_config(robot / "config.yaml", options=["policy"], sensors=[])
    with pytest.raises(ConfigError, match="unknown sensors"):
        load_config(robot / "config.yaml", sensors=["unknown"])


def test_independent_digit_and_audio(tmp_path):
    robot = mock_project(tmp_path)
    cfg = load_config(
        robot / "config.yaml",
        options=["policy"],
        sensors=["digit_left"],
        observe=["digit_left"],
    )
    assert list(cfg.sensors) == ["digit_left"]
    assert cfg.controller_for("follower").observes() == ["digit_left"]
    (robot / "nodes/audio.yaml").write_text(
        "type: mel_mono\ndevice: mock\nchannels: 1\n"
    )
    cfg = load_config(robot / "config.yaml", sensors=["audio"])
    audio = cfg.sensors["audio"]
    sample = audio.open(True, cfg.dataset_fps).read()
    assert sample.value.shape == (64, 64)
    assert sample.value.dtype == np.float32


def test_continuous_window_freshness_and_close(monkeypatch):
    events = []

    class Stream:
        def __init__(self, **kwargs):
            events.append(kwargs)

        def start(self):
            events.append("start")

        def stop(self):
            events.append("stop")

        def close(self):
            events.append("close")

    monkeypatch.setattr(
        "roboloom.sensors.audio.microphone.import_module",
        lambda name: SimpleNamespace(InputStream=Stream),
    )
    reader = SoundDeviceReader("mock", 10, 4)
    assert reader.read() is None
    reader._capture(np.array([[1], [2]], np.int16), 2, None, False)
    assert reader.read() is None
    reader._capture(np.array([[3], [4]], np.int16), 2, None, False)
    sample = reader.read()
    np.testing.assert_array_equal(sample.value, [1, 2, 3, 4])
    assert sample.capture_ns > 0
    assert reader.read() is None
    reader._capture(np.array([[5]], np.int16), 1, None, False)
    np.testing.assert_array_equal(reader.read().value, [2, 3, 4, 5])
    reader.close()
    assert events[-2:] == ["stop", "close"]


def test_schema_rejection_precedes_resume(tmp_path):
    robot = mock_project(tmp_path)
    cfg = load_config(robot / "config.yaml", sensors=[])
    root = tmp_path / "data"
    cfg = replace(cfg, output=str(root))
    from lerobot.utils.constants import DEFAULT_FEATURES

    from roboloom.recording.schema import features

    meta = root / "meta"
    meta.mkdir(parents=True)
    info = {
        "features": {
            **features(cfg),
            **DEFAULT_FEATURES,
            "observation.audio.old": {"dtype": "int16", "shape": [1], "names": None},
        },
        "fps": cfg.dataset_fps,
        "robot_type": cfg.robot,
    }
    original = json.dumps(info)
    (meta / "info.json").write_text(original)
    recorder = EpisodeRecorder(cfg)
    with pytest.raises(ValueError, match="removed feature: observation.audio.old"):
        recorder.open_dataset()
    assert recorder.dataset is None
    assert (meta / "info.json").read_text() == original


def test_mel_numeric_contract():
    sensor = MelMono("mic", {"device": "mock", "channels": 1})
    assert sensor.shape == (64, 64)
    assert sensor.signature(15)["frequency_order"] == "ascending"
    with pytest.raises(ValueError):
        MelMono("mic", {"device": "mock", "channels": 1, "fmax": 30000})


def test_mel_transform_and_dataset_roundtrip(tmp_path):
    pytest.importorskip("librosa")
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    from roboloom.config import RobotConfig
    from roboloom.core.protocol import Envelope
    from roboloom.core.source import ConstantReader
    from roboloom.sensors.audio.microphone import MelReader

    sensor = MelMono("mic", {"device": "mock", "channels": 1})
    wave = (10000 * np.sin(2 * np.pi * 1000 * np.arange(44100) / 44100)).astype(
        np.int16
    )
    reader = MelReader(ConstantReader(wave), sensor)
    sample = reader.read()
    assert sample.value.shape == sensor.shape
    assert np.isfinite(sample.value).all()
    assert sample.value.max() > sample.value.min() + 20
    cfg = RobotConfig(
        robot="audio_mock",
        repo_id="local/audio",
        output=str(tmp_path / "data"),
        dataset_fps=10,
        followers={},
        sensors={"mic": sensor},
        max_age_ms={"mic": 1500},
        mode="mock",
    )
    recorder = EpisodeRecorder(cfg)
    t = sample.capture_ns
    recorder.start("audio", t)
    recorder.ingest(
        "mic",
        Envelope(
            "audio", "mic", "boot", 0, t, t, sensor.encode(sample), t_receive_ns=t
        ),
    )
    recorder.stop(t + 200_000_000)
    recorder.save()
    recorder.close()
    ds = LeRobotDataset(cfg.repo_id, root=cfg.output)
    np.testing.assert_allclose(ds[0]["observation.audio.mic"].numpy(), sample.value)
    resumed = EpisodeRecorder(cfg)
    resumed.open_dataset()
    resumed.close()
    cfg.sensors["mic"] = MelMono(
        "mic", {"device": "mock", "channels": 1, "fmax": 14000}
    )
    with pytest.raises(ValueError, match="audio processing"):
        EpisodeRecorder(cfg).open_dataset()


def test_session_propagates_audio_and_separate_observe(tmp_path):
    from roboloom.runtime.session import Session

    robot = mock_project(tmp_path)
    (robot / "nodes/audio.yaml").write_text(
        "type: mel_mono\ndevice: mock\nchannels: 1\n"
    )
    with Session.launch(
        robot / "config.yaml",
        options=["policy"],
        sensors=["audio"],
        observe=["audio"],
        screen=False,
        operator=None,
        log_dir=tmp_path / "logs",
    ) as session:
        session.wait_ready()
        result = session.record("hold", seconds=1)
        fields = session.status()["policy"]["fields"]
    assert result.saved
    assert "infer_ms" in fields and "error" not in fields
