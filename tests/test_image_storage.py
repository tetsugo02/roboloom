import numpy as np
import pytest
import yaml

from roboloom.config import RobotConfig, load_config
from roboloom.core.protocol import Envelope
from roboloom.recording import EpisodeRecorder
from roboloom.sensors.tactile.digit import DigitSensor
from roboloom.sensors.vision.base import ImageSensor
from roboloom.sensors.vision.realsense import RealSenseRGB
from roboloom.sensors.vision.v4l2 import V4l2RGB


@pytest.mark.parametrize("cls", [ImageSensor, RealSenseRGB, DigitSensor, V4l2RGB])
@pytest.mark.parametrize("storage", [None, "video", "image"])
def test_sensor_storage(cls, storage):
    cfg = {
        "height": 320,
        "width": 240,
        "fps": 30,
        "serial": "test",
        "device": "/dev/mock",
    }
    if storage is not None:
        cfg["storage"] = storage
    sensor = cls("sensor", cfg)
    assert sensor.features(10)["observation.images.sensor"]["dtype"] == (
        storage or "video"
    )
    reader = sensor.open(mock=True, dataset_fps=10)
    assert reader.read().value.dtype == np.uint8
    reader.close()


@pytest.mark.parametrize("storage", ["png", None, 1, [], {}])
def test_invalid_storage_at_config_load(tmp_path, storage):
    (tmp_path / "camera.yaml").write_text(
        yaml.safe_dump(
            {
                "type": "realsense_rgb",
                "height": 48,
                "width": 64,
                "fps": 10,
                "serial": "mock",
                "storage": storage,
            }
        )
    )
    (tmp_path / "recorder.yaml").write_text("max_age_ms: {camera: 1000}\n")
    (tmp_path / "session.yaml").write_text("{}\n")
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "repo_id": "local/storage",
                "output": "data",
                "mode": "mock",
                "dataset_fps": 10,
                "followers": {},
                "sensors": {"camera": "camera.yaml"},
                "recorder": "recorder.yaml",
                "session": "session.yaml",
            }
        )
    )
    with pytest.raises(ValueError, match="camera.storage.*video.*image"):
        load_config(path)


@pytest.mark.parametrize(
    "storages", [("image", "video"), ("image", "image"), ("video", "video")]
)
def test_recording_roundtrip(tmp_path, storages):
    import torch
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    sensors = {
        "digit": DigitSensor(
            "digit",
            {
                "height": 320,
                "width": 240,
                "fps": 10,
                "serial": "mock",
                "storage": storages[0],
            },
        ),
        "camera": RealSenseRGB(
            "camera",
            {
                "height": 48,
                "width": 64,
                "fps": 10,
                "serial": "mock2",
                "storage": storages[1],
            },
        ),
    }
    cfg = RobotConfig(
        robot="mock",
        repo_id="local/storage",
        output=str(tmp_path / "data"),
        dataset_fps=10,
        followers={},
        sensors=sensors,
        max_age_ms={name: 1000 for name in sensors},
        mode="mock",
    )
    recorder = EpisodeRecorder(cfg)
    rng = np.random.default_rng(42)
    frames = {
        name: rng.integers(0, 256, sensor.shape, dtype=np.uint8)
        for name, sensor in sensors.items()
    }
    t = 1_000_000_000
    recorder.start("storage", t)
    for name, frame in frames.items():
        recorder.ingest(
            name,
            Envelope("image", name, "boot", 0, t, t, {"image": frame}, t_receive_ns=t),
        )
    recorder.stop(t + 300_000_000)
    assert recorder.save() == 3
    recorder.close()
    ds = LeRobotDataset(cfg.repo_id, root=cfg.output, video_backend="pyav")
    for name, storage in zip(sensors, storages, strict=True):
        key = f"observation.images.{name}"
        assert ds.features[key]["dtype"] == storage
        value = ds[0][key]
        assert value.dtype == torch.float32
        assert value.shape == (3, *sensors[name].shape[:2])
        assert 0 <= value.min() <= value.max() <= 1
        if storage == "image":
            for index in range(3):
                np.testing.assert_array_equal(
                    (ds[index][key].numpy().transpose(1, 2, 0) * 255)
                    .round()
                    .astype(np.uint8),
                    frames[name],
                )
        else:
            assert list((tmp_path / "data" / "videos" / key).rglob("*.mp4"))
    sensors["digit"].storage = "video" if storages[0] == "image" else "image"
    resumed = EpisodeRecorder(cfg)
    with pytest.raises(ValueError, match="storage changes require a separate dataset"):
        resumed.open_dataset()
    resumed.close()
