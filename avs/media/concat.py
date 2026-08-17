"""정규화된 클립들을 하나로 잇는다."""

from __future__ import annotations

from pathlib import Path

from .. import config
from ..models import Profile, Transition
from ..proc import CommandFailed, run
from .normalize import encode_args
from .timeline import xfade_offsets


def _concat_list_body(clips: list[Path]) -> str:
    # concat demuxer 형식. 작은따옴표는 '\'' 로 이스케이프한다.
    lines = []
    for clip in clips:
        escaped = str(clip.resolve()).replace("'", r"'\''")
        lines.append(f"file '{escaped}'")
    return "\n".join(lines) + "\n"


def concat_simple(
    clips: list[Path], out_path: Path, *, list_path: Path, log_path: Path | None = None
) -> Path:
    """전환 없이 잇는다.

    클립이 이미 동일 파라미터로 정규화되어 있으므로 재인코딩 없이 붙인다.
    빠르고 화질 손실이 없다.
    """
    list_path.parent.mkdir(parents=True, exist_ok=True)
    list_path.write_text(_concat_list_body(clips), encoding="utf-8")

    cmd = [
        config.ffmpeg(), "-y", "-nostdin", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(list_path),
        "-c", "copy", "-movflags", "+faststart",
        str(out_path),
    ]
    try:
        run(cmd, timeout=1800, log_path=log_path)
    except CommandFailed as exc:
        raise RuntimeError(f"클립 이어붙이기 실패: {exc}") from exc
    return out_path


def build_xfade_graph(
    durations: list[float], transition: float, *, transition_name: str = "fade"
) -> str:
    """xfade/acrossfade 체인 filter_complex 문자열을 만든다."""
    n = len(durations)
    offsets = xfade_offsets(durations, transition)

    parts: list[str] = []
    v_prev, a_prev = "0:v", "0:a"
    for i in range(1, n):
        v_out = f"v{i}" if i < n - 1 else "vout"
        a_out = f"a{i}" if i < n - 1 else "aout"
        parts.append(
            f"[{v_prev}][{i}:v]xfade=transition={transition_name}"
            f":duration={transition:.3f}:offset={offsets[i - 1]:.3f}[{v_out}]"
        )
        parts.append(
            f"[{a_prev}][{i}:a]acrossfade=d={transition:.3f}:c1=tri:c2=tri[{a_out}]"
        )
        v_prev, a_prev = v_out, a_out
    return ";".join(parts)


def concat_xfade(
    clips: list[Path],
    durations: list[float],
    out_path: Path,
    profile: Profile,
    *,
    log_path: Path | None = None,
) -> Path:
    """겹침 전환을 넣어 잇는다. 전 구간 재인코딩이 필요하다."""
    cmd = [config.ffmpeg(), "-y", "-nostdin", "-loglevel", "error"]
    for clip in clips:
        cmd += ["-i", str(clip)]
    cmd += [
        "-filter_complex", build_xfade_graph(durations, profile.transition_duration),
        "-map", "[vout]", "-map", "[aout]",
    ]
    cmd += encode_args(profile)
    cmd += [str(out_path)]

    try:
        run(cmd, timeout=3600, log_path=log_path)
    except CommandFailed as exc:
        raise RuntimeError(f"전환 합성 실패: {exc}") from exc
    return out_path


def concat_clips(
    clips: list[Path],
    durations: list[float],
    out_path: Path,
    profile: Profile,
    *,
    work_dir: Path,
    log_path: Path | None = None,
) -> Path:
    if not clips:
        raise ValueError("이어붙일 클립이 없습니다")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    use_xfade = (
        profile.transition is Transition.XFADE
        and len(clips) > 1
        and profile.transition_duration > 0
    )
    if use_xfade:
        return concat_xfade(clips, durations, out_path, profile, log_path=log_path)
    return concat_simple(
        clips, out_path, list_path=work_dir / "concat.txt", log_path=log_path
    )
