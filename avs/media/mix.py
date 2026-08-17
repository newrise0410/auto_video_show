"""내레이션을 클립 오디오에 얹는다.

Grok 클립에는 장면에 맞는 환경음이 들어 있다. 그냥 더하면 말과 겹쳐 지저분해
지고, 통째로 죽이면 영상이 밋밋해진다. 기본값은 **사이드체인 더킹** — 말하는
동안에만 환경음을 눌러준다.

필터 문자열을 만드는 부분은 순수 함수로 빼서 ffmpeg 없이 테스트한다.
"""

from __future__ import annotations

from pathlib import Path

from .. import config
from ..models import AmbientMode, Profile
from ..proc import CommandFailed, run
from .normalize import encode_args


def mix_filter(profile: Profile, head_pad: float) -> str:
    """입력 0=영상(환경음 포함), 입력 1=내레이션 → `[aout]`.

    내레이션은 `head_pad` 만큼 밀어서 시작한다. 클립이 시작하자마자 말이
    나오면 급하게 들린다.
    """
    delay_ms = int(round(head_pad * 1000))
    delayed = f"[1:a]adelay={delay_ms}|{delay_ms}"

    if profile.ambient is AmbientMode.MUTE:
        # 환경음을 아예 버리고 내레이션만 남긴다. 길이는 영상에 맞춘다.
        return f"{delayed},apad[aout]"

    if profile.ambient is AmbientMode.ATTENUATE:
        return (
            f"{delayed}[nar];"
            f"[0:a]volume={profile.ambient_gain_db}dB[amb];"
            f"[amb][nar]amix=inputs=2:duration=first:normalize=0[aout]"
        )

    # duck: 내레이션을 키(sidechain)로 써서 말할 때만 환경음을 누른다.
    # 같은 스트림을 두 번 쓰므로 asplit 으로 복제한다.
    #
    # `apad` 가 반드시 있어야 한다. sidechaincompress 는 두 입력 중 **먼저
    # 끝나는 쪽**에서 멈추는데, 내레이션은 클립보다 짧다. 패딩이 없으면
    # 합성 결과가 내레이션 길이에서 잘려서 씬 끝부분의 환경음이 통째로
    # 사라진다(영상은 그대로인데 소리만 뚝 끊긴다).
    return (
        f"{delayed},apad,asplit=2[nar][key];"
        f"[0:a][key]sidechaincompress="
        f"threshold=0.03:ratio=8:attack=20:release=400:makeup=1[ducked];"
        f"[ducked][nar]amix=inputs=2:duration=first:normalize=0[aout]"
    )


def mix_narration(
    video: Path,
    narration: Path,
    out_path: Path,
    profile: Profile,
    *,
    head_pad: float,
    duration: float | None = None,
    log_path: Path | None = None,
) -> Path:
    """정규화된 클립에 내레이션을 얹는다. 영상 스트림은 그대로 복사한다."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        config.ffmpeg(), "-y", "-nostdin", "-loglevel", "error",
        "-i", str(video),
        "-i", str(narration),
        "-filter_complex", mix_filter(profile, head_pad),
        "-map", "0:v:0", "-map", "[aout]",
        "-c:v", "copy",  # 영상은 이미 캔버스 규격이다. 다시 인코딩할 이유가 없다
        "-c:a", profile.audio_codec,
        "-b:a", profile.audio_bitrate,
        "-ar", str(profile.audio_sample_rate),
        "-ac", "2",
    ]
    if duration is not None:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-movflags", "+faststart", str(out_path)]

    try:
        run(cmd, timeout=1800, log_path=log_path)
    except CommandFailed as exc:
        raise RuntimeError(f"내레이션 믹스 실패 ({video.name}): {exc}") from exc
    return out_path


def loudnorm_filter(target_lufs: float) -> str:
    """유튜브 업로드 기준으로 라우드니스를 맞춘다.

    너무 조용하면 묻히고, 너무 크면 플랫폼이 자동으로 깎아서 다이내믹이 죽는다.
    """
    return f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11"


def apply_loudness(
    video: Path, out_path: Path, profile: Profile, *, log_path: Path | None = None
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        config.ffmpeg(), "-y", "-nostdin", "-loglevel", "error",
        "-i", str(video),
        "-af", loudnorm_filter(profile.loudness_target or -14.0),
        "-c:v", "copy",
        "-c:a", profile.audio_codec,
        "-b:a", profile.audio_bitrate,
        "-ar", str(profile.audio_sample_rate),
        "-ac", "2",
        "-movflags", "+faststart",
        str(out_path),
    ]
    try:
        run(cmd, timeout=1800, log_path=log_path)
    except CommandFailed as exc:
        raise RuntimeError(f"라우드니스 정규화 실패: {exc}") from exc
    return out_path


__all__ = [
    "apply_loudness",
    "encode_args",
    "loudnorm_filter",
    "mix_filter",
    "mix_narration",
]
