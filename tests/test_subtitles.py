from avs.config import load_profile
from avs.media.subtitles import build_ass, build_srt, wrap_narration
from avs.models import Scene


def scenes(n: int) -> list[Scene]:
    return [
        Scene(index=i, narration=f"{i}번 장면 내레이션", video_prompt="a cinematic test shot")
        for i in range(1, n + 1)
    ]


def test_short_text_stays_on_one_line():
    assert wrap_narration("짧은 문장") == ["짧은 문장"]


def test_long_text_splits_near_the_middle_space():
    lines = wrap_narration("여기서 핵심을 한 문장으로 정리해 봅니다")
    assert len(lines) == 2
    assert "".join(lines).replace(" ", "") == "여기서핵심을한문장으로정리해봅니다"


def test_split_without_spaces_falls_back_to_midpoint():
    text = "가" * 30
    lines = wrap_narration(text)
    assert len(lines) == 2
    assert "".join(lines) == text


def test_srt_blocks_are_sequential_and_contiguous():
    srt = build_srt(scenes(3), [8.0, 8.0, 8.0], 0.0)
    assert "1\n00:00:00,000 --> 00:00:08,000" in srt
    assert "2\n00:00:08,000 --> 00:00:16,000" in srt
    assert "3\n00:00:16,000 --> 00:00:24,000" in srt


def test_ass_uses_profile_canvas_and_style():
    profile = load_profile("shorts")
    ass = build_ass(scenes(2), [8.0, 8.0], profile)
    assert "PlayResX: 1080" in ass
    assert "PlayResY: 1920" in ass
    style = next(line for line in ass.splitlines() if line.startswith("Style: Default"))
    assert f",{profile.subtitles.font_size}," in style
    assert style.endswith(f",{profile.subtitles.margin_v},1")
    assert ass.count("Dialogue:") == 2


def test_ass_ignores_transition_duration_when_transition_is_none():
    profile = load_profile("shorts")
    assert profile.effective_transition == 0.0
    ass = build_ass(scenes(2), [8.0, 8.0], profile)
    # 두 번째 자막은 정확히 8초에 시작해야 한다 (0.4초 당겨지면 안 됨).
    assert "0:00:08.00" in ass
