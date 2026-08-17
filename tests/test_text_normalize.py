from avs.tts.normalize_text import native_korean, normalize, sino_korean


def test_sino_reading():
    assert sino_korean(1) == "일"
    assert sino_korean(15) == "십오"  # 일십오 아님
    assert sino_korean(92) == "구십이"
    assert sino_korean(30) == "삼십"
    assert sino_korean(100) == "백"
    assert sino_korean(1000) == "천"
    assert sino_korean(2026) == "이천이십육"
    assert sino_korean(10000) == "만"
    assert sino_korean(0) == "영"


def test_native_reading_uses_determiner_forms():
    assert native_korean(1) == "한"
    assert native_korean(3) == "세"
    assert native_korean(10) == "열"
    assert native_korean(12) == "열두"
    assert native_korean(20) == "스무"  # 스물 아님
    assert native_korean(21) == "스물한"
    # 100 이상은 고유어를 쓰지 않는다
    assert native_korean(100) == "백"


def test_counter_decides_which_number_system():
    # 배는 고유어
    assert normalize("3배 빠릅니다") == "세 배 빠릅니다"
    # 도는 한자어
    assert normalize("92도") == "구십이 도"
    # 개는 고유어
    assert normalize("2개") == "두 개"
    # 초는 한자어
    assert normalize("30초") == "삼십 초"


def test_ratio_is_always_sino():
    """베이크오프에서 실제로 틀렸던 문장. 「1 대 15가」→「1대18소가」로 들렸다."""
    assert "일 대 십오" in normalize("원두 대 물 비율은 1 대 15가 기본값입니다")
    assert "일 대 십오" in normalize("비율은 1:15입니다")


def test_ratio_beats_the_native_counter_meaning_of_대():
    # 「대」는 수량 단위(차 두 대)로도 쓰이지만, 숫자에 끼면 비율이다
    assert normalize("1 대 15") == "일 대 십오"


def test_range_expands_and_keeps_counter_once():
    assert normalize("30~60초") == "삼십에서 육십 초"
    assert normalize("30초에서 1분") == "삼십 초에서 일 분"


def test_decimal_reads_digit_by_digit():
    assert normalize("3.5배") == "삼 점 오배" or normalize("3.5배").startswith("삼 점 오")


def test_symbols_become_words():
    assert "오십 퍼센트" in normalize("50%")
    assert "구십이 도" in normalize("92℃")


def test_particles_survive():
    assert normalize("15가 기본값") == "십오가 기본값"
    assert normalize("30초에서") == "삼십 초에서"


def test_longer_counter_wins_over_shorter_prefix():
    # 「킬로미터」가 「미터」로 잘리면 안 된다
    assert normalize("5킬로미터") == "오 킬로미터"


def test_plain_korean_is_untouched():
    text = "원두를 바꿔도 커피가 쓰다면 원인은 대개 추출에 있습니다"
    assert normalize(text) == text


def test_english_tokens_are_left_alone():
    # 영어 고유명사는 모델이 잘 읽었다. 손대면 오히려 나빠진다.
    assert normalize("GitHub Actions에서 CI를 돌립니다") == "GitHub Actions에서 CI를 돌립니다"


def test_empty_and_whitespace():
    assert normalize("") == ""
    assert normalize("   ") == ""
