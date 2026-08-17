"""TTS 결과물의 앞뒤 무음을 재고 잘라낸다.

Supertonic이 만드는 wav에는 앞에 0.5~0.6초, 뒤에 0.6~0.8초의 무음이 들어 있다.
3.7초짜리 클립에서 실제 발화는 2.4초뿐이다. 이걸 그대로 두면 두 가지가 어긋난다:

1. **자막이 목소리보다 먼저 뜬다.** 타임라인은 `head_pad` 만큼만 밀어서 자막
   시작을 잡는데, 실제 목소리는 그보다 0.6초 뒤에 나온다.
2. **씬마다 죽은 화면이 생긴다.** 2-pass가 클립 길이를 내레이션 길이로 정하므로,
   무음까지 길이에 포함되어 그만큼 화면이 늘어난다. 생성 비용도 같이 늘어난다.

앞뒤를 잘라내면 `head_pad` / `tail_pad` 가 원래 의도대로 "말 앞뒤의 여유"만
의미하게 되고, 기록되는 길이가 실제 발화 길이가 된다.

`silencedetect` 출력 파싱과 자를 구간 계산은 순수 함수로 빼서 ffmpeg 없이 테스트한다.
"""

from __future__ import annotations

import re
from pathlib import Path

from .. import config
from ..proc import CommandFailed, run

#: 이보다 조용하면 무음으로 본다. TTS 출력은 진짜 디지털 묵음에 가까워서
#: 넉넉하게 잡아도 발화를 깎지 않는다.
NOISE_FLOOR_DB = -45.0

#: 이 길이 이상 이어져야 무음 구간으로 인정한다. 어절 사이의 짧은 끊김을
#: 무음으로 세면 문장 중간이 잘린다.
MIN_SILENCE = 0.10

#: 잘라낸 경계에 남겨두는 여유. 파형이 뚝 끊겨 클릭이 나는 걸 막는다.
GUARD = 0.03

_SILENCE_START = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_SILENCE_END = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")


def parse_silence_ranges(stderr: str) -> list[tuple[float, float | None]]:
    """`silencedetect` 로그에서 (시작, 끝) 목록을 뽑는다.

    마지막 구간은 파일 끝까지 이어져 `silence_end` 가 없을 수 있다. 그때 끝은
    `None` 이다.
    """
    starts = [float(m) for m in _SILENCE_START.findall(stderr)]
    ends = [float(m) for m in _SILENCE_END.findall(stderr)]
    ranges: list[tuple[float, float | None]] = []
    for i, start in enumerate(starts):
        ranges.append((start, ends[i] if i < len(ends) else None))
    return ranges


def edge_silence(
    ranges: list[tuple[float, float | None]], total: float, *, epsilon: float = 0.05
) -> tuple[float, float]:
    """앞뒤에 붙은 무음 길이 (lead, trail).

    파일 맨 앞에서 시작하는 구간만 선행 무음이고, 파일 끝까지 이어지는 구간만
    후행 무음이다. 문장 중간의 끊김은 세지 않는다.
    """
    lead = 0.0
    trail = 0.0
    for start, end in ranges:
        if start <= epsilon and end is not None:
            lead = max(lead, end)
        if end is None or end >= total - epsilon:
            trail = max(trail, total - start)
    return lead, min(trail, total)


def trim_bounds(
    lead: float, trail: float, total: float, *, guard: float = GUARD
) -> tuple[float, float] | None:
    """실제로 잘라낼 (시작 오프셋, 남길 길이). 자를 게 없으면 None.

    발화가 통째로 사라지는 걸 막는다 — 남는 길이가 너무 짧으면 손대지 않는다.
    """
    start = max(0.0, lead - guard)
    end = min(total, total - trail + guard)
    duration = end - start

    if duration < 0.2 or duration >= total - 0.02:
        return None  # 자를 게 없거나, 잘랐다가는 말이 남지 않는다
    return round(start, 3), round(duration, 3)


def measure(path: Path, total: float) -> tuple[float, float]:
    """파일의 앞뒤 무음 길이를 잰다."""
    cmd = [
        config.ffmpeg(), "-nostdin", "-hide_banner",
        "-i", str(path),
        "-af", f"silencedetect=noise={NOISE_FLOOR_DB}dB:d={MIN_SILENCE}",
        "-f", "null", "-",
    ]
    try:
        result = run(cmd, timeout=180, check=False)
    except CommandFailed:
        return 0.0, 0.0
    return edge_silence(parse_silence_ranges(result.stderr), total)


def trim_edges(path: Path, total: float) -> tuple[float, float]:
    """앞뒤 무음을 제자리에서 잘라낸다.

    돌려주는 값은 (잘라낸 선행 무음, 새 길이). 자를 게 없으면 (0.0, total).
    """
    lead, trail = measure(path, total)
    bounds = trim_bounds(lead, trail, total)
    if bounds is None:
        return 0.0, total

    start, duration = bounds
    tmp = path.with_suffix(".trim.wav")
    cmd = [
        config.ffmpeg(), "-y", "-nostdin", "-loglevel", "error",
        "-ss", f"{start:.3f}",
        "-t", f"{duration:.3f}",
        "-i", str(path),
        "-c:a", "pcm_s16le",
        str(tmp),
    ]
    try:
        run(cmd, timeout=180)
    except CommandFailed:
        tmp.unlink(missing_ok=True)
        return 0.0, total

    tmp.replace(path)
    return start, duration
