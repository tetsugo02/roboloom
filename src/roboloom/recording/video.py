"""Video codec of `storage: video` image features, chosen with `recorder.video_codec`.

Encoding stays LeRobot's: the choice becomes a `lerobot.configs.video.RGBEncoderConfig`
passed to `LeRobotDataset.create/resume` (its defaults otherwise: CRF, GOP, preset).
To add a codec LeRobot supports, add a `VideoCodec` to `VIDEO_CODECS`.

A dataset keeps one codec: LeRobot appends each episode's video to the current MP4 file
without checking that the codecs match, so resuming reuses the stored encoder settings
and an explicit choice that differs from them is refused before anything is written.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..errors import ConfigError

if TYPE_CHECKING:
    from ..config import RobotConfig


@dataclass(frozen=True)
class VideoCodec:
    """`name` is the value of `video_codec`; `encoder` is LeRobot's `vcodec`; `stream`
    is the codec name FFmpeg reports for the stream (`video.codec` in info.json);
    `label` is shown by the launcher."""

    name: str
    encoder: str
    stream: str
    label: str
    aliases: tuple[str, ...] = ()


VIDEO_CODECS: dict[str, VideoCodec] = {
    codec.name: codec
    for codec in (
        VideoCodec("av1", "libsvtav1", "av1", "AV1", aliases=("libsvtav1",)),
        VideoCodec("h264", "h264", "h264", "H.264"),
    )
}
DEFAULT_VIDEO_CODEC = "h264"  # plays almost everywhere (LeRobot's own default: AV1)
_NAMES = {
    alias: codec.name
    for codec in VIDEO_CODECS.values()
    for alias in (codec.name, *codec.aliases)
}


def video_codec_names() -> list[str]:
    """Accepted `video_codec` values, aliases included."""
    return list(_NAMES)


def normalize_video_codec(value: object, where: str = "video_codec") -> str | None:
    """The codec's name for a `video_codec` value (None: not given)."""
    if value is None:
        return None
    name = _NAMES.get(value.strip().lower()) if isinstance(value, str) else None
    if name is None:
        raise ConfigError(
            f"{where}: {value!r} is not a video codec; use one of "
            f"{', '.join(video_codec_names())}"
        )
    return name


def video_keys(cfg: RobotConfig) -> list[str]:
    """The dataset features LeRobot stores as MP4 (`storage: video` image sensors)."""
    from .schema import features

    return [k for k, v in features(cfg).items() if v.get("dtype") == "video"]


def _stored(root: Path, keys: list[str]) -> tuple[str | None, dict]:
    """The stream codec and `info` block of the videos already saved under `root`
    (None when no episode has a video yet)."""
    info_path = root / "meta" / "info.json"
    if not info_path.exists():
        return None, {}
    stored = json.loads(info_path.read_text()).get("features", {})
    found = {
        key: stored[key]["info"]
        for key in keys
        if (stored.get(key) or {}).get("info", {}).get("video.codec")
    }
    codecs = {key: info["video.codec"] for key, info in found.items()}
    if len(set(codecs.values())) > 1:
        raise ValueError(
            f"existing dataset mixes video codecs: {root}\n"
            + "\n".join(f"{key}: {codec}" for key, codec in sorted(codecs.items()))
        )
    if not found:
        return None, {}
    key = next(iter(found))
    return codecs[key], found[key]


def video_encoder(cfg: RobotConfig, codec: str | None) -> Any:
    """The `RGBEncoderConfig` for this configuration's dataset with `codec` requested
    (None: the saved videos' settings, else H.264), or None without video features.
    Raises ValueError, before anything is written, when the requested codec cannot be
    encoded here or differs from the videos already in the dataset."""
    keys = video_keys(cfg)
    if not keys:
        return None
    requested = normalize_video_codec(codec)
    video = import_module("lerobot.configs.video")
    root = Path(cfg.output).resolve()
    existing, info = _stored(root, keys)
    if existing is not None:
        if requested is not None and VIDEO_CODECS[requested].stream != existing:
            raise ValueError(
                f"existing dataset video codec differs: {root}\n"
                f"video_codec: {existing!r} (saved videos) -> {requested!r} "
                f"(requested)\nOmit video_codec to append with {existing!r}, or set "
                "another repo_id and output; existing data was not changed."
            )
        try:  # LeRobot's own reading of the stored settings (codec, CRF, GOP, ...)
            return video.encoder_config_from_video_info(info)
        except ValueError as exc:
            raise ValueError(
                f"existing dataset videos use {existing!r}, which cannot be encoded "
                f"here: {exc}"
            ) from exc
    chosen = VIDEO_CODECS[requested or DEFAULT_VIDEO_CODEC]
    try:
        return video.RGBEncoderConfig(vcodec=chosen.encoder)
    except ValueError as exc:
        raise ValueError(
            f"video_codec {chosen.name!r}: LeRobot encoder {chosen.encoder!r} is "
            f"unavailable ({exc}); choose another video_codec. Nothing was recorded."
        ) from exc


def check_video_encoding(cfg: RobotConfig) -> str | None:
    """Refuse a launch whose videos could not be recorded as configured (see
    `video_encoder`); return the codec the videos will use (None without video
    features, or without LeRobot when no codec was requested)."""
    if not video_keys(cfg):
        return None
    requested = cfg.recorder.get("video_codec")
    try:
        import_module("lerobot.configs.video")
    except ImportError as exc:
        if requested is None:
            return None  # the recorder reports the missing extra as before
        raise ConfigError(
            "recorder.video_codec needs LeRobot (install roboloom[record])"
        ) from exc
    try:
        encoder = video_encoder(cfg, requested)
    except ValueError as exc:
        raise ConfigError(f"{cfg.path}: {exc}") from exc
    return _NAMES.get(encoder.vcodec, encoder.vcodec)
