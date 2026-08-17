import pytest

from avs.config import load_profile
from avs.stages.s2_script import validate
from avs.textutil import extract_json_object


@pytest.fixture
def profile():
    return load_profile("shorts")


def payload(narrations: list[str]) -> dict:
    return {
        "title": "제목",
        "description": "설명",
        "hashtags": ["#태그"],
        "scenes": [
            {
                "index": i,
                "narration": text,
                "video_prompt": "a cinematic wide shot of a quiet street at dawn",
                "on_screen_text": "키워드",
            }
            for i, text in enumerate(narrations, start=1)
        ],
    }


def test_valid_script_passes(profile):
    script, problems = validate(payload(["짧은 내레이션"] * 3), profile, 3)
    assert problems == []
    assert script is not None
    assert [s.index for s in script.scenes] == [1, 2, 3]


def test_narration_over_limit_is_rejected_with_a_useful_message(profile):
    long_text = "가" * (profile.narration_limit + 5)
    script, problems = validate(payload([long_text]), profile, 1)
    assert script is None
    assert any(str(profile.narration_limit) in p for p in problems)
    assert any(long_text in p for p in problems)


def test_scene_count_mismatch_is_rejected(profile):
    script, problems = validate(payload(["가나다"] * 2), profile, 5)
    assert script is None
    assert any("5개" in p for p in problems)


def test_short_video_prompt_is_rejected(profile):
    data = payload(["가나다"])
    data["scenes"][0]["video_prompt"] = "too short"
    script, problems = validate(data, profile, 1)
    assert script is None
    assert any("video_prompt" in p for p in problems)


def test_wrong_index_is_repaired_silently(profile):
    data = payload(["가나다", "라마바"])
    data["scenes"][0]["index"] = 7
    data["scenes"][1]["index"] = 9
    script, problems = validate(data, profile, 2)
    assert problems == []
    assert [s.index for s in script.scenes] == [1, 2]


def test_on_screen_text_is_truncated_not_rejected(profile):
    data = payload(["가나다"])
    data["scenes"][0]["on_screen_text"] = "아주아주아주아주아주아주긴키워드"
    script, problems = validate(data, profile, 1)
    assert problems == []
    assert len(script.scenes[0].on_screen_text) <= 12


def test_json_is_extracted_from_chatty_output():
    raw = '설명을 좀 붙이면요:\n```json\n{"title": "가"}\n```\n끝!'
    assert extract_json_object(raw) == {"title": "가"}


def test_json_extraction_failure_is_explicit():
    with pytest.raises(ValueError):
        extract_json_object("JSON은 없고 말만 있습니다")
