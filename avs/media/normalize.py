"""클립을 프로파일 캔버스 규격으로 통일한다.

소스 클립을 그대로 이어붙이면 해상도·프레임레이트·SAR·오디오 유무가 제각각
이라 concat이 깨지거나 소리 없이 붙는다. 그래서 붙이기 전에 모든 클립을
동일한 파라미터로 한 번 다시 인코딩한다.

필터 문자열 계산은 순수 함수로 빼서 ffmpeg 없이 테스트할 수 있게 했다.
"""

from __future__ import annotations

from pathlib import Path

from .. import config
from ..models import FitMode, Profile, SourceAudio
from ..proc import CommandFailed, run
from .probe import MediaInfo, probe


def video_filter(profile: Profile) -> str:
    """캔버스 맞춤 + fps/SAR 통일 필터.

    cover  : 캔버스를 채우고 넘치는 부분을 잘라낸다 (여백 없음, 화면 일부 손실)
    contain: 전체를 보존하고 남는 영역을 검게 채운다 (여백 생김)

    720p 소스를 1080 캔버스로 올리는 경우가 기본이라 lanczos로 업스케일한다.
    """
    w, h = profile.width, profile.height
    if profile.fit is FitMode.CONTAIN:
        fit = (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
    else:
        fit = (
            f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={w}:{h}"
        )
    return f"{fit},setsar=1,fps={profile.fps},format={profile.pixel_format}"


def wants_silent_track(profile: Profile, info: MediaInfo) -> bool:
    """무음 트랙을 새로 만들어 붙여야 하는가."""
    return not info.has_audio or profile.source_audio is SourceAudio.MUTE


def encode_args(profile: Profile) -> list[str]:
    return [
        "-c:v", profile.video_codec,
        "-crf", str(profile.crf),
        "-preset", profile.preset,
        "-pix_fmt", profile.pixel_format,
        "-c:a", profile.audio_codec,
        "-b:a", profile.audio_bitrate,
        "-ar", str(profile.audio_sample_rate),
        "-ac", "2",
        "-movflags", "+faststart",
    ]


def normalize_clip(
    source: Path,
    out_path: Path,
    profile: Profile,
    *,
    duration: float | None = None,
    info: MediaInfo | None = None,
    log_path: Path | None = None,
) -> MediaInfo:
    """클립 하나를 캔버스 규격으로 다시 인코딩하고 결과 정보를 돌려준다.

    소스에 오디오가 없거나 프로파일이 음소거를 지시하면 무음 트랙을 붙인다.
    클립마다 트랙 구성이 다르면 concat 단계에서 오디오가 통째로 사라진다.
    """
    info = info or probe(source)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    silence = wants_silent_track(profile, info)

    cmd = [config.ffmpeg(), "-y", "-nostdin", "-loglevel", "error", "-i", str(source)]
    if silence:
        cmd += [
            "-f", "lavfi",
            "-i", f"anullsrc=channel_layout=stereo:sample_rate={profile.audio_sample_rate}",
            "-shortest",
        ]
    cmd += ["-vf", video_filter(profile)]
    if duration is not None:
        # 요청보다 길게 나온 클립만 잘라낸다. 짧게 나온 건 늘리지 않고,
        # 자막 타이밍이 실제 길이를 따라가게 둔다.
        cmd += ["-t", f"{duration:.3f}"]
    cmd += encode_args(profile)
    # Grok 클립에는 h264 본편 외에 mjpeg 썸네일 스트림이 붙어 있어서
    # 반드시 첫 번째 비디오 스트림만 집어야 한다.
    cmd += ["-map", "0:v:0", "-map", "1:a:0" if silence else "0:a:0"]
    cmd += [str(out_path)]

    try:
        run(cmd, timeout=1800, log_path=log_path)
    except CommandFailed as exc:
        raise RuntimeError(f"클립 정규화 실패 ({source.name}): {exc}") from exc

    return probe(out_path)
