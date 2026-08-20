"""문체 계측(`avs/quality.py`) 단위 테스트.

지표 함수는 고정 문자열로만 검사한다 — 실행 산출물에 기대면 대본이 바뀔 때마다
테스트가 깨진다.
"""

import pytest

from avs.quality import (
    FORMAL_RUN_MAX,
    STYLE_MIN_SCENES,
    ending_kind,
    is_formal,
    longest_run,
    measure,
    narrator_tics,
    opens_with_connective,
    proper_nouns,
    sentences,
    style_problems,
)


# --------------------------------------------------------------- 합쇼체 판별


@pytest.mark.parametrize(
    "sentence",
    [
        "돌아갔습니다.",
        "그는 배를 띄웁니다.",
        "아닙니다.",
        "왜 그랬습니까?",
        "이름을 숨겼습니다",  # 마침표가 없어도 같다
    ],
)
def test_formal_endings_are_detected(sentence):
    assert is_formal(sentence)


@pytest.mark.parametrize(
    "sentence",
    [
        "아무도 아니다.",  # 인용된 해라체 — 여기가 핵심이다
        "그런 뜻을 지니다.",
        "값을 치렀죠.",
        "그랬더군요.",
        "남은 건 배 한 척.",
        "",
    ],
)
def test_non_formal_endings_are_not_mistaken(sentence):
    assert not is_formal(sentence)


def test_ending_kind_classifies_registers():
    assert ending_kind("돌아갔습니다.") == "합쇼체"
    assert ending_kind("값을 치렀죠.") == "해요체"
    assert ending_kind("그랬더군요.") == "해요체"
    assert ending_kind("왜 그랬을까요?") == "의문"
    assert ending_kind("남은 건 배 한 척.") == "명사형"
    assert ending_kind("아무도 아니다.") == "기타"


def test_ending_kind_counts_by_type_not_by_tail():
    """했습니다/었습니다/갔습니다는 귀에 같은 소리다. 같은 유형으로 세야 한다."""
    kinds = [ending_kind(s) for s in ("갔습니다.", "했습니다.", "먹었습니다.")]
    assert kinds == ["합쇼체"] * 3
    assert longest_run(kinds) == 3


def test_longest_run_measures_consecutive_not_ratio():
    """비율은 뒤쪽에 변화를 몰아넣어도 충족된다. 연속은 그렇지 않다."""
    clustered = ["합쇼체"] * 6 + ["해요체"] * 4
    spread = ["합쇼체", "해요체"] * 3 + ["합쇼체"] * 3 + ["해요체"]
    assert clustered.count("합쇼체") == spread.count("합쇼체")
    assert longest_run(clustered) == 6
    assert longest_run(spread) == 3


# ------------------------------------------------------------------ 접속·상투구


def test_connective_openers():
    assert opens_with_connective("그래서 배를 띄웠습니다.")
    assert opens_with_connective("하지만 바다가 막았습니다.")
    # 주어 반복은 연결이 아니다
    assert not opens_with_connective("그는 배를 띄웠습니다.")
    assert not opens_with_connective("오디세우스가 떠났습니다.")


@pytest.mark.parametrize(
    "text",
    [
        "첫 번째 이야기입니다.",
        "마지막 이야기입니다.",
        "저는 순서대로 나열하지 않겠습니다.",
        "이 영상에서는 두 가지만 봅니다.",
        "지금부터 살펴보겠습니다.",
    ],
)
def test_narrator_tics_are_caught(text):
    assert narrator_tics(text)


def test_ordinary_narration_has_no_tics():
    assert not narrator_tics("그는 포도주를 먹였습니다. 괴물이 이름을 묻자 답했습니다.")


# --------------------------------------------------------------------- 측정


def test_sentences_split_on_terminators():
    assert sentences("하나입니다. 둘입니다! 셋일까요?") == [
        "하나입니다.",
        "둘입니다!",
        "셋일까요?",
    ]


def test_measure_reports_shape():
    texts = ["그는 떠났습니다. 바다가 막았습니다.", "그래서 돌아왔죠."]
    r = measure(texts)
    assert r.scenes == 2
    assert r.sentence_count == 3
    assert r.formal_ratio == pytest.approx(2 / 3)
    assert r.connective_scenes == 1  # 1번 씬은 받을 앞 씬이 없어 세지 않는다
    assert r.connective_ratio == 1.0


def test_measure_ignores_first_scene_for_connectives():
    r = measure(["그래서 시작합니다.", "끝났습니다."])
    assert r.connective_scenes == 0


def test_proper_nouns_diff_catches_new_names():
    before = proper_nouns("폴리페모스가 소리쳤습니다.")
    after = proper_nouns("폴리페모스가 소리쳤습니다. 텔레마코스는 기다렸습니다.")
    assert "텔레마코스" in after - before


# ------------------------------------------------- style_problems 소프트 계약


def _formal_scene(i: int) -> str:
    return f"{i}번 씬에서 그는 배를 띄웠습니다. 바다가 그를 막았습니다."


def test_style_problems_skipped_below_minimum_scenes():
    """씬이 적으면 비율이 통계가 아니라 잡음이다."""
    few = [_formal_scene(i) for i in range(STYLE_MIN_SCENES - 1)]
    assert style_problems(few) == []


def test_style_problems_flags_monotone_endings():
    many = [_formal_scene(i) for i in range(STYLE_MIN_SCENES + 4)]
    problems = style_problems(many)
    assert problems
    assert any("연속" in p for p in problems)
    assert any("-습니다" in p for p in problems)


def test_style_problems_run_check_names_the_limit():
    many = [_formal_scene(i) for i in range(STYLE_MIN_SCENES + 4)]
    run_problem = next(p for p in style_problems(many) if "연속" in p)
    assert str(FORMAL_RUN_MAX) in run_problem


def test_style_problems_quiet_on_varied_script():
    """어미가 돌고 접속이 있으면 지적이 없어야 한다 — 정상을 잡으면 안 된다."""
    scenes = [
        "그는 배를 띄웠습니다.",
        "그래서 바다가 막았죠.",
        "하지만 그는 멈추지 않았습니다.",
        "결국 혼자 남았더군요.",
        "그런데 왜 그랬을까요?",
        "그 이름이 그를 잡았던 겁니다.",
        "대신 그는 이름을 숨겼습니다.",
        "그러자 길이 열렸거든요.",
        "덕분에 집에 닿았습니다.",
    ]
    assert style_problems(scenes) == []
