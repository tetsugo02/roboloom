"""recorder.video_codec: H.264 (default) or AV1 through LeRobot's encoder settings, the
same choice in Python, the CLI, the launcher and the dora nodes, and one codec per dataset."""

from __future__ import annotations

import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path

import av
import numpy as np
import pytest
from conftest import mock_project

from roboloom.config import RobotConfig, load_config
from roboloom.core.protocol import Envelope
from roboloom.errors import ConfigError
from roboloom.recording import EpisodeRecorder
from roboloom.recording import video as video_module
from roboloom.recording.video import (
    VIDEO_CODECS,
    check_video_encoding,
    normalize_video_codec,
)
from roboloom.runtime.node import config_from_env
from roboloom.runtime.session import Session, config_env
from roboloom.sensors.vision.opencv import OpenCVRGB
from roboloom.ui.launcher import LauncherApp, LaunchPlan, load_last, save_last

FPS = 10
# solid colours, one per row, so a decoded frame shows which row it came from
COLOURS = [(220, 30, 30), (30, 200, 40), (30, 40, 220), (230, 220, 30), (200, 40, 200)]
CAMERA = "observation.images.camera"
STILL = "observation.images.still"


def _cfg(root: Path, codec: str | None = None) -> RobotConfig:
    """A camera stored as MP4 next to a still sensor stored as PNG."""
    sensors = {
        "camera": OpenCVRGB(
            "camera",
            {"height": 48, "width": 64, "fps": FPS, "device": 0, "storage": "video"},
        ),
        "still": OpenCVRGB(
            "still",
            {"height": 32, "width": 24, "fps": FPS, "device": 1, "storage": "image"},
        ),
    }
    return RobotConfig(
        robot="mock",
        repo_id="local/codec",
        output=str(root / "data"),
        dataset_fps=FPS,
        followers={},
        sensors=sensors,
        max_age_ms={name: 1000 for name in sensors},
        recorder={"video_codec": codec},
        mode="mock",
    )


def _frame(colour, shape) -> np.ndarray:
    return np.broadcast_to(np.asarray(colour, np.uint8), (*shape[:2], 3)).copy()


def _record(recorder: EpisodeRecorder, start_ns: int) -> None:
    """One episode of len(COLOURS) rows; row k carries COLOURS[k]."""
    period = int(1e9 / FPS)
    recorder.start("colours", start_ns)
    for k, colour in enumerate(COLOURS):
        t = start_ns + k * period
        for name, sensor in recorder.cfg.sensors.items():
            image = _frame(colour, sensor.shape)
            recorder.ingest(
                name,
                Envelope(
                    "image", name, "boot", k, t, t, {"image": image}, t_receive_ns=t
                ),
            )
    recorder.stop(start_ns + len(COLOURS) * period)
    assert recorder.save() == len(COLOURS)


def _streams(root: Path) -> list[tuple[str, int]]:
    """(codec, decoded frame count) of every saved camera MP4."""
    out = []
    for path in sorted((root / "videos" / CAMERA).rglob("*.mp4")):
        with av.open(str(path)) as container:
            stream = container.streams.video[0]
            frames = sum(1 for _ in container.decode(stream))
            out.append((stream.codec_context.codec.canonical_name, frames))
    return out


# -- names ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "name"),
    [(None, None), ("av1", "av1"), ("libsvtav1", "av1"), ("H264", "h264")],
)
def test_codec_names(value, name):
    assert normalize_video_codec(value) == name


@pytest.mark.parametrize("value", ["hevc", "x264", "", 264, ["h264"]])
def test_unknown_codec_is_refused(value):
    with pytest.raises(ConfigError, match="not a video codec.*av1, libsvtav1, h264"):
        normalize_video_codec(value)


# -- recording through LeRobot ---------------------------------------------------


@pytest.mark.parametrize(
    ("codec", "stream"), [(None, "h264"), ("av1", "av1"), ("h264", "h264")]
)
def test_recording_roundtrip(tmp_path, codec, stream):
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    cfg = _cfg(tmp_path, codec)
    recorder = EpisodeRecorder(cfg, **cfg.recorder)
    _record(recorder, 1_000_000_000)
    recorder.close()
    root = Path(cfg.output)
    assert _streams(root) == [(stream, len(COLOURS))]
    info = json.loads((root / "meta" / "info.json").read_text())
    assert info["features"][CAMERA]["dtype"] == "video"
    assert info["features"][CAMERA]["info"]["video.codec"] == stream
    assert info["features"][STILL]["dtype"] == "image"  # PNG, whatever the codec
    ds = LeRobotDataset(cfg.repo_id, root=root, video_backend="pyav")
    assert ds.meta.total_frames == len(COLOURS)
    for k, colour in enumerate(COLOURS):
        row = ds[k]
        assert float(row["timestamp"]) == pytest.approx(k / FPS, abs=1e-4)
        camera = row[CAMERA].numpy()
        assert camera.shape == (3, 48, 64)
        # lossy: compare the mean colour, not the pixels
        mean = camera.reshape(3, -1).mean(axis=1) * 255
        assert np.abs(mean - colour).max() < 25, (k, mean, colour)
        still = (row[STILL].numpy() * 255).round().astype(np.uint8)
        np.testing.assert_array_equal(  # PNG stays lossless
            still.transpose(1, 2, 0), _frame(colour, (32, 24))
        )


def test_resume_keeps_the_saved_codec_and_refuses_another(tmp_path):
    cfg = _cfg(tmp_path, "h264")
    first = EpisodeRecorder(cfg, **cfg.recorder)
    _record(first, 1_000_000_000)
    first.close()
    root = Path(cfg.output)
    unspecified = replace(cfg, recorder={"video_codec": None})
    assert check_video_encoding(unspecified) == "h264"
    resumed = EpisodeRecorder(unspecified, **unspecified.recorder)  # inherits H.264
    _record(resumed, 5_000_000_000)
    resumed.close()
    streams = _streams(root)  # resuming starts a new MP4 file
    assert {codec for codec, _ in streams} == {"h264"}
    assert sum(frames for _, frames in streams) == 2 * len(COLOURS)
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    ds = LeRobotDataset(cfg.repo_id, root=root, video_backend="pyav")
    assert ds.meta.total_episodes == 2 and ds.meta.total_frames == 2 * len(COLOURS)
    second = ds[len(COLOURS) + 2]  # the appended episode decodes from its own file
    assert int(second["episode_index"]) == 1
    mean = second[CAMERA].numpy().reshape(3, -1).mean(axis=1) * 255
    assert np.abs(mean - COLOURS[2]).max() < 25

    before = {p: p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}
    for codec in ("av1", "libsvtav1"):
        other = replace(cfg, recorder={"video_codec": normalize_video_codec(codec)})
        with pytest.raises(ConfigError, match=r"'h264' \(saved videos\) -> 'av1'"):
            check_video_encoding(other)
        recorder = EpisodeRecorder(other, **other.recorder)
        with pytest.raises(ValueError, match="repo_id and output"):
            recorder.open_dataset()
        assert recorder.dataset is None
    after = {p: p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}
    assert after == before  # nothing written, converted or moved


def test_existing_av1_dataset_resumes_as_av1(tmp_path):
    cfg = _cfg(tmp_path)  # unspecified: the saved videos' codec
    first = EpisodeRecorder(cfg, video_codec="av1")  # e.g. recorded before H.264
    _record(first, 1_000_000_000)
    first.close()
    with pytest.raises(ConfigError, match="'av1' \\(saved videos\\) -> 'h264'"):
        check_video_encoding(replace(cfg, recorder={"video_codec": "h264"}))
    resumed = EpisodeRecorder(cfg, video_codec="av1")
    _record(resumed, 5_000_000_000)
    resumed.close()
    streams = _streams(Path(cfg.output))  # resuming starts a new MP4 file
    assert {codec for codec, _ in streams} == {"av1"}
    assert sum(frames for _, frames in streams) == 2 * len(COLOURS)


def test_unavailable_encoder_is_refused_before_writing(tmp_path, monkeypatch):
    # an encoder this FFmpeg build lacks (macOS VideoToolbox on Linux)
    missing = replace(VIDEO_CODECS["h264"], encoder="h264_videotoolbox")
    if sys.platform == "darwin":
        pytest.skip("VideoToolbox exists on macOS")
    monkeypatch.setitem(VIDEO_CODECS, "h264", missing)
    cfg = _cfg(tmp_path, "h264")
    with pytest.raises(ConfigError, match="h264_videotoolbox.*unavailable"):
        check_video_encoding(cfg)
    with pytest.raises(ValueError, match="unavailable"):
        EpisodeRecorder(cfg, **cfg.recorder).open_dataset()
    assert not Path(cfg.output).exists()


def test_no_video_features_needs_no_codec(tmp_path):
    cfg = _cfg(tmp_path, "h264")
    cfg.sensors["camera"].storage = "image"
    assert video_module.video_keys(cfg) == []
    assert check_video_encoding(cfg) is None


# -- the same choice everywhere ----------------------------------------------------


def _project(tmp_path: Path, yaml_codec: str | None = None) -> Path:
    robot = mock_project(tmp_path)
    if yaml_codec is not None:
        recorder = robot / "nodes" / "recorder.yaml"
        recorder.write_text(recorder.read_text() + f"video_codec: {yaml_codec}\n")
    return robot / "config.yaml"


def test_load_config_and_yaml(tmp_path):
    path = _project(tmp_path)
    assert load_config(path).recorder["video_codec"] is None
    assert load_config(path, video_codec="libsvtav1").recorder["video_codec"] == "av1"
    with pytest.raises(ConfigError, match="not a video codec"):
        load_config(path, video_codec="vp9")
    path = _project(tmp_path / "yaml", "h264")
    assert load_config(path).recorder["video_codec"] == "h264"
    assert load_config(path, video_codec=None).recorder["video_codec"] == "h264"
    assert load_config(path, video_codec="av1").recorder["video_codec"] == "av1"
    bad = _project(tmp_path / "bad", "mpeg2")
    with pytest.raises(ConfigError, match="recorder.video_codec.*mpeg2"):
        load_config(bad)


@pytest.mark.parametrize(
    ("yaml_codec", "chosen", "expected"),
    [
        (None, None, None),
        (None, "h264", "h264"),
        ("h264", None, "h264"),
        ("h264", "av1", "av1"),
    ],
)
def test_nodes_reload_the_parents_choice(tmp_path, yaml_codec, chosen, expected):
    path = _project(tmp_path, yaml_codec)
    cfg = load_config(path, video_codec=chosen, sensors=["camera"])
    child = config_from_env(cfg.path, config_env(cfg))
    assert child.recorder == cfg.recorder
    assert child.recorder["video_codec"] == expected


def test_launch_refuses_a_codec_for_a_loaded_config(tmp_path):
    cfg = load_config(_project(tmp_path))
    with pytest.raises(ConfigError, match="video_codec in load_config"):
        Session.launch(cfg, video_codec="h264", screen=False, operator=None)


def test_cli_passes_the_codec(tmp_path, monkeypatch, capsys):
    from roboloom import cli

    _project(tmp_path / ".roboloom")
    monkeypatch.chdir(tmp_path)
    started: list[RobotConfig] = []
    monkeypatch.setattr(
        cli, "_start", lambda args, cfg, plan, **kw: started.append(cfg)
    )
    cli.main(["run", "--plain", "--video-codec", "h264"])
    cli.main(["run", "--plain"])
    assert [c.recorder["video_codec"] for c in started] == ["h264", None]
    with pytest.raises(SystemExit, match="not a video codec"):
        cli.main(["run", "--plain", "--video-codec", "vp9"])
    if shutil.which("dora") is not None:
        cli.main(["validate", "--video-codec", "h264"])
        assert "video codec: h264" in capsys.readouterr().out
        cli.main(["validate"])
        assert "video codec: h264" in capsys.readouterr().out


def test_last_launch_remembers_the_codec(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("{}\n")
    save_last(path, LaunchPlan(video_codec="h264"))
    assert load_last(path, {}).video_codec == "h264"
    save_last(path, LaunchPlan())
    assert load_last(path, {}).video_codec is None
    last = path.parent / "logs" / "last_launch.yaml"
    last.write_text(last.read_text().replace("video_codec: null", "video_codec: vp9"))
    assert load_last(path, {}).video_codec is None  # no longer accepted: the YAML's


@pytest.mark.asyncio
@pytest.mark.parametrize("initial", [None, "h264", "av1"])
async def test_launcher_chooses_the_codec(tmp_path, initial):
    from textual.widgets import RadioButton

    path = _project(tmp_path)
    app = LauncherApp(path, LaunchPlan(video_codec=initial))
    async with app.run_test(size=(100, 60)) as pilot:
        assert app._read().video_codec == initial
        app.query_one("#video-h264", RadioButton).value = True
        await pilot.pause()
        plan = app._read()
        assert plan.video_codec == "h264"
        assert "video codec: h264" in app._summary(plan)
        assert plan.options == ()  # the mode set's infer rule did not fire
        app.query_one("#video-yaml", RadioButton).value = True
        await pilot.pause()
        assert app._read().video_codec is None
    save_last(path, plan)
    assert load_last(path, app.options).video_codec == "h264"
    cfg = load_config(path, video_codec=plan.video_codec)
    assert config_from_env(cfg.path, config_env(cfg)).recorder["video_codec"] == "h264"


def test_session_records_with_the_chosen_codec(tmp_path):
    """The dora recorder node encodes with the codec chosen in the parent; a different
    codec for the same dataset is refused before the dataflow starts."""
    if shutil.which("dora") is None:
        pytest.skip("needs dora")
    path = _project(tmp_path)
    with Session.launch(
        path,
        video_codec="h264",
        screen=False,
        operator=None,
        log_dir=tmp_path / "logs",
    ) as session:
        session.wait_ready()
        assert session.record("hold", seconds=1).saved
    cfg = load_config(path)
    root = Path(cfg.output)
    videos = list((root / "videos").rglob("*.mp4"))
    assert videos
    for video in videos:
        with av.open(str(video)) as container:
            assert (
                container.streams.video[0].codec_context.codec.canonical_name == "h264"
            )
    with pytest.raises(ConfigError, match="'h264' \\(saved videos\\) -> 'av1'"):
        Session.launch(path, video_codec="av1", screen=False, operator=None)
    assert not (path.parent / "config.fifo").exists()
