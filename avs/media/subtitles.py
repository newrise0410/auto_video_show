"""자막 파일 생성과 굽기.

SRT는 Vrew로 넘길 때 쓰고, ASS는 `--skip-vrew` 경로에서 ffmpeg가 직접
구울 때 쓴다. 두 포맷 모두 같은 타임라인 계산(`timeline.scene_timings`)에서
나온다.
"""

from __future__ import annotations

from pathlib import Path

from .. import config
from ..models import Profile, Scene
from ..proc import CommandFailed, run
from .timeline import scene_timings

# 한 줄에 이 정도가 넘어가면 두 줄로 접는다.
_WRAP_AT = 16


def wrap_narration(text: str, limit: int = _WRAP_AT) -> list[str]:
    """내레이션을 최대 두 줄로 접는다.

    한국어는 어절 단위로 끊어야 읽기 편해서, 가운데에 가장 가까운 공백을
    찾아 자른다. 공백이 없으면 글자 수 중간에서 자른다.
    """
    text = text.strip()
    if len(text) <= limit:
        return [text]

    mid = len(text) // 2
    best = -1
    for i, ch in enumerate(text):
        if ch == " " and (best < 0 or abs(i - mid) < abs(best - mid)):
            best = i
    if best <= 0:
        best = mid
    return [text[:best].strip(), text[best:].strip()]


def _srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ass_time(seconds: float) -> str:
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6_000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def build_srt(
    scenes: list[Scene],
    durations: list[float],
    transition: float = 0.0,
    spans: list[tuple[float, float]] | None = None,
) -> str:
    """`spans` 를 주면 그 구간을 쓴다 (내레이션이 있을 때 목소리 구간).

    없으면 씬 전체를 자막 구간으로 삼는다.
    """
    timings = spans or scene_timings(durations, transition)
    blocks: list[str] = []
    for i, (scene, (start, end)) in enumerate(zip(scenes, timings, strict=False), start=1):
        text = "\n".join(wrap_narration(scene.narration))
        blocks.append(f"{i}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}\n")
    return "\n".join(blocks)


def build_ass(
    scenes: list[Scene],
    durations: list[float],
    profile: Profile,
    spans: list[tuple[float, float]] | None = None,
) -> str:
    st = profile.subtitles
    timings = spans or scene_timings(durations, profile.effective_transition)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {profile.width}
PlayResY: {profile.height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{st.font_name},{st.font_size},{st.primary_colour},{st.primary_colour},{st.outline_colour},{st.back_colour},{-1 if st.bold else 0},0,0,0,100,100,0,0,{st.border_style},{st.outline},{st.shadow},{st.alignment},60,60,{st.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = []
    for scene, (start, end) in zip(scenes, timings, strict=False):
        text = r"\N".join(wrap_narration(scene.narration))
        lines.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{text}"
        )
    return header + "\n".join(lines) + "\n"


def burn_subtitles(
    video: Path, ass_path: Path, out_path: Path, profile: Profile, *, log_path: Path | None = None
) -> Path:
    """ASS 자막을 영상에 굽는다.

    필터 인자에서 Windows 경로(드라이브 콜론, 역슬래시)를 이스케이프하는 건
    함정이 많아서, 자막 파일이 있는 디렉터리로 cwd를 옮기고 파일명만 넘긴다.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        config.ffmpeg(), "-y", "-nostdin", "-loglevel", "error",
        "-i", str(video.resolve()),
        "-vf", f"subtitles={ass_path.name}",
        "-c:v", profile.video_codec,
        "-crf", str(profile.crf),
        "-preset", profile.preset,
        "-pix_fmt", profile.pixel_format,
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(out_path.resolve()),
    ]
    try:
        run(cmd, cwd=ass_path.parent, timeout=3600, log_path=log_path)
    except CommandFailed as exc:
        raise RuntimeError(f"자막 굽기 실패: {exc}") from exc
    return out_path
