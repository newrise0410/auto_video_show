"""ffprobe 래퍼."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .. import config
from ..proc import CommandFailed, run

_MEAN_VOLUME = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")

# 이보다 조용하면 사실상 무음으로 본다 (anullsrc는 -91dB 근처로 나온다).
SILENCE_THRESHOLD_DB = -60.0


class ProbeError(RuntimeError):
    pass


@dataclass(frozen=True)
class MediaInfo:
    path: Path
    width: int
    height: int
    duration: float
    fps: float
    has_audio: bool
    has_video: bool
    codec: str

    @property
    def size_label(self) -> str:
        return f"{self.width}x{self.height}"


def _parse_fps(value: str | None) -> float:
    if not value or value == "0/0":
        return 0.0
    if "/" in value:
        num, _, den = value.partition("/")
        try:
            d = float(den)
            return float(num) / d if d else 0.0
        except ValueError:
            return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def mean_volume(path: Path) -> float | None:
    """오디오 평균 레벨(dB). 트랙이 없거나 측정에 실패하면 None.

    "오디오 트랙이 있다"와 "소리가 난다"는 다르다. 무음 트랙을 채워 넣는
    경로가 있어서, 사용자에게 안내할 때는 레벨까지 봐야 정확하다.
    """
    cmd = [
        config.ffmpeg(), "-nostdin", "-hide_banner",
        "-i", str(path),
        "-map", "0:a:0", "-af", "volumedetect",
        "-f", "null", "-",
    ]
    try:
        result = run(cmd, timeout=180, check=False)
    except CommandFailed:
        return None
    match = _MEAN_VOLUME.search(result.stderr)
    return float(match.group(1)) if match else None


def probe(path: Path) -> MediaInfo:
    if not path.is_file():
        raise ProbeError(f"파일이 없습니다: {path}")

    cmd = [
        config.ffprobe(),
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        result = run(cmd, timeout=60)
    except CommandFailed as exc:
        raise ProbeError(f"ffprobe 실패: {exc}") from exc

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError(f"ffprobe 출력을 파싱할 수 없습니다: {path}") from exc

    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = 0.0
    for source in (video or {}, data.get("format") or {}):
        raw = source.get("duration")
        if raw:
            try:
                duration = float(raw)
                break
            except (TypeError, ValueError):
                continue

    return MediaInfo(
        path=path,
        width=int((video or {}).get("width") or 0),
        height=int((video or {}).get("height") or 0),
        duration=duration,
        fps=_parse_fps((video or {}).get("avg_frame_rate")),
        has_audio=audio is not None,
        has_video=video is not None,
        codec=str((video or {}).get("codec_name") or ""),
    )
