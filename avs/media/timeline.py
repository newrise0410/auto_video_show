"""씬 길이 목록으로부터 타임라인을 계산한다.

자막 타이밍과 xfade 오프셋이 같은 계산에서 나와야 자막이 화면과 어긋나지
않는다. ffmpeg 없이 검증할 수 있도록 전부 순수 함수로 둔다.
"""

from __future__ import annotations

from math import ceil


def total_duration(durations: list[float], transition: float = 0.0) -> float:
    """전환으로 겹치는 만큼을 뺀 최종 길이."""
    if not durations:
        return 0.0
    return sum(durations) - transition * (len(durations) - 1)


def scene_timings(
    durations: list[float], transition: float = 0.0
) -> list[tuple[float, float]]:
    """각 씬의 (시작, 끝)을 최종 타임라인 기준으로 계산한다.

    전환이 있으면 앞뒤 클립이 `transition`초씩 겹치므로 i번째 클립의 시작이
    그만큼 앞당겨진다. 자막이 서로 겹치지 않도록 각 씬의 끝은 다음 씬의
    시작에 붙인다.
    """
    if not durations:
        return []

    starts: list[float] = []
    acc = 0.0
    for i, d in enumerate(durations):
        starts.append(max(0.0, acc - transition * i))
        acc += d

    timings: list[tuple[float, float]] = []
    for i, start in enumerate(starts):
        if i + 1 < len(starts):
            end = starts[i + 1]
        else:
            end = start + durations[i]
        timings.append((start, max(start, end)))
    return timings


def scene_length_for_narration(
    narration_duration: float,
    *,
    head_pad: float,
    tail_pad: float,
    max_seconds: float,
    min_seconds: float = 1.0,
) -> tuple[int, float]:
    """내레이션 길이로부터 (요청할 클립 초, 타임라인 목표 길이)를 계산한다.

    영상 백엔드는 정수 초만 받으므로 올림해서 요청하고, 조립할 때는 실제로
    필요한 만큼만 잘라 쓴다. 이렇게 하면 올림 때문에 생기는 최대 1초의
    빈 화면이 사라진다.

    내레이션이 상한을 넘으면 잘라내지 않고 상한까지만 쓴다. 말이 잘리는 건
    화면이 짧은 것보다 나쁘므로, 호출 쪽에서 이 경우를 따로 경고한다.
    """
    target = narration_duration + head_pad + tail_pad
    target = max(min_seconds, min(target, max_seconds))
    requested = min(int(max_seconds), max(int(min_seconds), ceil(target)))
    return requested, round(target, 3)


def narration_spans(
    scene_durations: list[float],
    narration_durations: list[float],
    *,
    head_pad: float,
    transition: float = 0.0,
) -> list[tuple[float, float]]:
    """자막을 씬 전체가 아니라 **목소리가 나는 구간**에 맞춘다.

    앞뒤 여유(pad) 동안 자막이 떠 있으면 화면과 어긋나 보인다.
    """
    starts = [start for start, _ in scene_timings(scene_durations, transition)]
    spans = []
    for i, start in enumerate(starts):
        spoken = narration_durations[i] if i < len(narration_durations) else 0.0
        scene_end = start + (scene_durations[i] if i < len(scene_durations) else 0.0)
        begin = start + head_pad
        spans.append((begin, min(begin + spoken, scene_end)))
    return spans


def xfade_offsets(durations: list[float], transition: float) -> list[float]:
    """xfade 체인의 각 단계 offset.

    k번째 xfade(= k+1번째 클립을 붙이는 단계)의 offset은 그 시점까지 만들어진
    출력 길이에서 전환 길이를 뺀 값이다.
    """
    if len(durations) < 2:
        return []
    offsets: list[float] = []
    acc = durations[0]
    for d in durations[1:]:
        offsets.append(max(0.0, acc - transition))
        acc = acc + d - transition
    return offsets
