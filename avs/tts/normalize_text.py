"""내레이션을 TTS가 제대로 읽을 수 있는 낭독형으로 바꾼다.

베이크오프에서 확인된 실제 실패 사례:

    「원두 대 물 비율은 1 대 15가 기본값입니다」
      → 합성 결과를 다시 받아 적으면 「1대18소가」

숫자에 조사가 붙으면 모델이 자주 무너진다. 아라비아 숫자를 미리 한글
낭독형으로 바꿔 놓으면 이 문제가 사라진다.

한국어 수사는 세는 단위에 따라 갈린다:

    한자어  일 이 삼 …   도, 분, 초, 년, 원, 퍼센트, 비율의 「대」
    고유어  한 두 세 …   개, 명, 번, 배, 살, 시, 잔, 마리

「3배」는 「세 배」지 「삼 배」가 아니고, 「92도」는 「구십이 도」지
「아흔둘 도」가 아니다. 이 구분이 이 모듈의 존재 이유다.

의존성 없이 표준 라이브러리만 쓴다 (TTS venv 쪽에서도 쓸 수 있게).
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------- 수사

_SINO_DIGITS = ["", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]
_SINO_SMALL_UNITS = ["", "십", "백", "천"]
_SINO_BIG_UNITS = ["", "만", "억", "조", "경"]

_NATIVE_ONES = [
    "", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉",
]
_NATIVE_TENS = [
    "", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔",
]


def sino_korean(n: int) -> str:
    """한자어 수사. 92 → 구십이, 15 → 십오, 1000 → 천"""
    if n == 0:
        return "영"
    if n < 0:
        return "마이너스 " + sino_korean(-n)

    chunks: list[str] = []
    big_index = 0
    while n > 0:
        n, chunk = divmod(n, 10000)
        if chunk:
            # 10000은 「만」이라고 읽지 「일만」이라고 읽지 않는다.
            # 억·조는 반대로 「일억」「일조」가 표준이라 여기만 예외다.
            if chunk == 1 and big_index == 1 and n == 0:
                chunks.append(_SINO_BIG_UNITS[big_index])
            else:
                chunks.append(_sino_chunk(chunk) + _SINO_BIG_UNITS[big_index])
        big_index += 1
    return "".join(reversed(chunks))


def _sino_chunk(chunk: int) -> str:
    """0~9999 한 덩어리. 십·백·천 앞의 1은 읽지 않는다 (십오, 일십오 아님)."""
    out = ""
    for position in range(3, -1, -1):
        digit = (chunk // (10**position)) % 10
        if not digit:
            continue
        if digit == 1 and position > 0:
            out += _SINO_SMALL_UNITS[position]
        else:
            out += _SINO_DIGITS[digit] + _SINO_SMALL_UNITS[position]
    return out


def native_korean(n: int) -> str:
    """고유어 수사의 관형형. 3 → 세, 20 → 스무, 21 → 스물한

    100 이상은 고유어를 쓰지 않으므로 한자어로 넘긴다.
    """
    if n <= 0 or n > 99:
        return sino_korean(n)
    tens, ones = divmod(n, 10)
    if tens == 2 and ones == 0:
        return "스무"  # 스물이 아니라 스무 (스무 개)
    return _NATIVE_TENS[tens] + _NATIVE_ONES[ones]


# --------------------------------------------------------------------- 단위

#: 고유어 수사를 쓰는 단위.
NATIVE_COUNTERS = {
    "개", "명", "번", "살", "시", "시간", "배", "잔", "그릇", "마리", "가지",
    "켤레", "송이", "장", "권, ", "권", "대", "통", "벌", "채", "자루", "병",
    "판", "줄", "컵", "숟가락", "스푼", "방울", "조각", "군데", "달", "쪽",
}

#: 한자어 수사를 쓰는 단위.
SINO_COUNTERS = {
    "도", "분", "초", "년", "월", "일", "주", "원", "달러", "퍼센트", "미터",
    "킬로미터", "센티미터", "밀리미터", "그램", "킬로그램", "리터", "밀리리터",
    "인분", "회", "위", "호", "차", "세기", "층", "인치", "픽셀", "볼트", "와트",
    "헤르츠", "바이트", "기가", "메가", "킬로", "배속", "프레임", "칼로리",
}

#: 기호를 읽는 말로.
SYMBOL_WORDS = {
    "%": "퍼센트",
    "℃": "도",
    "°C": "도",
    "°": "도",
    "&": "그리고",
    "+": "플러스",
    "=": "는",
}

# 「대」는 비율(1 대 15, 한자어)과 수량(차 두 대, 고유어) 양쪽으로 쓰인다.
# 비율 쪽을 먼저 처리해서 충돌을 없앤다.
_RATIO = re.compile(r"(?<![\d.])(\d+)\s*(?::|대)\s*(\d+)(?![\d.])")
_RANGE = re.compile(r"(?<![\d.])(\d+)\s*[~∼-]\s*(\d+)\s*([가-힣]*)")
_DECIMAL = re.compile(r"(?<![\d.])(\d+)\.(\d+)")
_NUMBER_WITH_COUNTER = re.compile(r"(?<![\d.])(\d{1,12})\s*([가-힣]+)?")

# 정렬 순서상 긴 단위를 먼저 봐야 「킬로미터」가 「미터」로 잘리지 않는다.
_ALL_COUNTERS = sorted(NATIVE_COUNTERS | SINO_COUNTERS, key=len, reverse=True)


def _split_counter(tail: str) -> tuple[str, str]:
    """단위 뒤에 붙은 조사를 떼어낸다. 「도,」 「초에서」 → (단위, 나머지)"""
    for counter in _ALL_COUNTERS:
        if tail.startswith(counter):
            return counter, tail[len(counter) :]
    return "", tail


def _read_number(value: int, counter: str) -> str:
    if counter in NATIVE_COUNTERS:
        return native_korean(value)
    return sino_korean(value)


def _expand_numbers(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        digits, tail = match.group(1), match.group(2) or ""
        counter, rest = _split_counter(tail)
        value = int(digits)
        spoken = _read_number(value, counter)
        if counter:
            return f"{spoken} {counter}{rest}"
        return f"{spoken}{rest}"

    return _NUMBER_WITH_COUNTER.sub(replace, text)


def normalize(text: str) -> str:
    """내레이션 한 줄을 낭독형으로.

    순서가 중요하다. 비율·범위·소수처럼 숫자가 둘 이상 엮인 형태를 먼저
    풀어야, 마지막의 일반 숫자 규칙이 그것들을 잘못 건드리지 않는다.
    """
    out = text.strip()
    if not out:
        return out

    # 「1 대 15」 「1:15」 → 「일 대 십오」 (비율은 언제나 한자어)
    out = _RATIO.sub(lambda m: f"{sino_korean(int(m.group(1)))} 대 {sino_korean(int(m.group(2)))}", out)

    # 「30~60초」 → 「삼십에서 육십 초」 — 단위는 뒤쪽 숫자에만 붙는다
    def _range(match: re.Match[str]) -> str:
        low, high, tail = int(match.group(1)), int(match.group(2)), match.group(3)
        counter, rest = _split_counter(tail)
        spoken_low = _read_number(low, counter)
        spoken_high = _read_number(high, counter)
        if counter:
            return f"{spoken_low}에서 {spoken_high} {counter}{rest}"
        return f"{spoken_low}에서 {spoken_high}{rest}"

    out = _RANGE.sub(_range, out)

    # 「3.5」 → 「삼 점 오」 — 소수점 아래는 한 자리씩 읽는다
    out = _DECIMAL.sub(
        lambda m: sino_korean(int(m.group(1)))
        + " 점 "
        + " ".join(_SINO_DIGITS[int(d)] or "영" for d in m.group(2)),
        out,
    )

    # 기호를 먼저 말로 바꿔야 「50%」의 단위가 「퍼센트」로 인식된다
    for symbol, word in SYMBOL_WORDS.items():
        out = out.replace(symbol, word)

    out = _expand_numbers(out)

    # 기호 치환·숫자 확장 과정에서 생긴 공백 정리
    return re.sub(r"\s{2,}", " ", out).strip()
