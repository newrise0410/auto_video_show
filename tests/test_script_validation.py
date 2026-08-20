import pytest

from avs.config import load_profile
from avs.prompts import script_retry_user
from avs.quality import STYLE_MIN_SCENES
from avs.stages.s2_script import validate
from avs.textutil import extract_json_object


@pytest.fixture
def profile():
    return load_profile("shorts")


def filler(profile) -> str:
    """하한을 만족하는 채움용 내레이션.

    길이가 아닌 규칙(인덱스 복구, 키워드 절단 등)을 검사하는 테스트가
    내레이션 하한에 걸려 실패하지 않도록 한다.
    """
    return "가" * profile.narration_limit


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
    script, problems = validate(payload([filler(profile)] * 3), profile, 3)
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
    data = payload([filler(profile), filler(profile)])
    data["scenes"][0]["index"] = 7
    data["scenes"][1]["index"] = 9
    script, problems = validate(data, profile, 2)
    assert problems == []
    assert [s.index for s in script.scenes] == [1, 2]


def test_on_screen_text_is_truncated_not_rejected(profile):
    data = payload([filler(profile)])
    data["scenes"][0]["on_screen_text"] = "아주아주아주아주아주아주긴키워드"
    script, problems = validate(data, profile, 1)
    assert problems == []
    assert len(script.scenes[0].on_screen_text) <= 12


def test_narration_far_under_limit_is_rejected(profile):
    """상한만 지키고 예산을 안 쓰면 영상이 반토막 난다. 하한이 이걸 막는다."""
    script, problems = validate(payload(["짧다"] * 3), profile, 3)
    assert script is None
    assert any("평균" in p for p in problems)


def test_one_short_line_among_full_ones_is_allowed(profile):
    """하한은 씬별이 아니라 평균에 걸린다 — 짧고 강한 한 줄은 정당한 연출이다."""
    texts = [filler(profile)] * 3 + ["나는 아무도 아니다"]
    script, problems = validate(payload(texts), profile, 4)
    assert problems == []
    assert script is not None


def test_json_is_extracted_from_chatty_output():
    raw = '설명을 좀 붙이면요:\n```json\n{"title": "가"}\n```\n끝!'
    assert extract_json_object(raw) == {"title": "가"}


def test_json_extraction_failure_is_explicit():
    with pytest.raises(ValueError):
        extract_json_object("JSON은 없고 말만 있습니다")


# ------------------------------------------------- 소프트 실패 계약 (문체 지적)


def test_style_problems_come_with_a_usable_script(profile):
    """계약: `script is None` 이면 못 씀, script 가 있는데 problems 가 있으면 고치면 좋음.

    문체 때문에 36씬짜리 실행이 죽으면 안 된다.
    """
    monotone = ["그는 새벽에 배를 띄웠습니다. 바다는 그날부터 그를 막아섰습니다. 노를 저어도 섬은 멀어지기만 했습니다."] * (STYLE_MIN_SCENES + 2)
    script, problems = validate(
        payload(monotone), profile, STYLE_MIN_SCENES + 2
    )
    assert script is not None, "문체 지적은 대본을 반려시키면 안 된다"
    assert problems, "단조로운 어미는 지적돼야 한다"


def test_style_check_skipped_below_minimum_scenes(profile):
    """씬이 적으면 비율이 잡음이다. 기존 filler 기반 테스트도 이 게이트가 지킨다."""
    few = ["그는 새벽에 배를 띄웠습니다. 바다는 그날부터 그를 막아섰습니다. 노를 저어도 섬은 멀어지기만 했습니다."] * (STYLE_MIN_SCENES - 1)
    script, problems = validate(payload(few), profile, STYLE_MIN_SCENES - 1)
    assert script is not None
    assert problems == []


def test_hard_failure_still_returns_none(profile):
    """길이 위반은 여전히 반려다 — 소프트 계약이 하드 검사를 무르게 하면 안 된다."""
    long_text = "가" * (profile.narration_limit + 5)
    script, problems = validate(payload([long_text]), profile, 1)
    assert script is None
    assert problems


# ------------------------------------------------------------------- 재시도


def test_retry_carries_outline_and_previous_output():
    """백엔드에 대화 기록이 없어서 재시도 메시지가 맥락 전부다."""
    message = script_retry_user(
        "오디세우스",
        "## 전개\n- [핵심][전환] 목마를 만들었다",
        8,
        '{"scenes": [{"index": 1}]}',
        ["씬 3의 어미를 바꾸세요."],
    )
    assert "목마를 만들었다" in message, "구성안이 들어가야 한다"
    assert '"index": 1' in message, "직전 출력이 들어가야 한다"
    assert "씬 3의 어미를 바꾸세요." in message
    assert "video_prompt" in message, "손대지 말라는 지시가 있어야 한다"


def test_retry_without_previous_output_still_works():
    """JSON 파싱이 깨지면 직전 출력이 없다."""
    message = script_retry_user("주제", "## 전개\n- 항목", 5, None, ["JSON이 아닙니다."])
    assert "JSON이 아닙니다." in message
    assert "직전에 당신이 낸 출력입니다" not in message
