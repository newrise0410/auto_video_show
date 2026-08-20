"""대본 문체 계측.

주관적인 질문("문장이 좋은가")에서 객관적으로 잴 수 있는 조각만 떼어낸다.
`docs/spike-local-tts.md` 가 "발음이 좋은가"를 ASR 왕복으로 바꾼 것과 같은
성격이다.

**여기서 나오는 수치는 한 방향 증거다.** 나쁘면 확실히 나쁘고, 좋다고 좋은
대본이라는 뜻은 아니다. 「저주가 걸렸습니다」가 「저주가 성립했습니다」보다
나은 이유는 사전 히트가 줄어서가 아니다.

순수 함수만 둔다 — 파일도 콘솔도 만지지 않는다. 그래야 고정 문자열로 테스트가
된다.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

DATA_DIR = Path(__file__).resolve().parent / "data"

# --------------------------------------------------------------------- 임계값

#: 씬이 이보다 적으면 문체를 재지 않는다. 비율이 통계가 아니라 잡음이 된다.
STYLE_MIN_SCENES = 8

#: 합쇼체(-습니다) 종결 비율 상한. 기본 레지스터에서 3분의 1쯤 벗어나게 한다.
#: 한국어 내레이션 참조 코퍼스가 없어서 이 값은 추측이다. 재시도가 계속 3회에
#: 닿으면 0.75로 풀되 FORMAL_RUN_MAX 는 건드리지 말 것 — 귀에 들리는 건 그쪽이다.
FORMAL_RATIO_MAX = 0.70

#: 같은 종결 유형이 연달아 나올 수 있는 최대 개수.
#: 실측 36씬 대본에서 40문장이 끊기지 않고 이어졌다. 비율은 뒤쪽에 변화를
#: 몰아넣어도 충족되지만, 귀가 듣는 건 연속이다.
FORMAL_RUN_MAX = 5

#: 앞 씬을 받아서 여는 씬의 최소 비율.
CONNECTIVE_RATIO_MIN = 0.25

#: 롱폼 실측 낭독 속도 (2718자 / 365.6초). 프로파일의 `chars_per_second` 는
#: 대본 작성용 목표치라 이것과 다르다.
MEASURED_CPS = 7.4

# ----------------------------------------------------------------- 문장 나누기

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_TRAIL = " \t.!?\"'“”‘’…"


def sentences(text: str) -> list[str]:
    """내레이션 한 덩어리를 문장으로 나눈다."""
    return [s.strip() for s in _SENT_SPLIT.split(text.strip()) if s.strip()]


# ------------------------------------------------------------------- 종결어미


def is_formal(sentence: str) -> bool:
    """합쇼체 평서·의문(-습니다 / -ㅂ니다 / -습니까)으로 끝나는가.

    단순히 '니다' 로 끝나는지 보면 인용된 해라체("아무도 아니다.")가 걸린다.
    합쇼체는 '니다' 앞 음절의 받침이 반드시 ㅂ이라는 점으로 가른다.
    (습니다·갑니다·아닙니다 ✓ / 아니다·지니다 ✗)
    """
    core = sentence.rstrip(_TRAIL)
    if len(core) < 3 or not core.endswith(("니다", "니까")):
        return False
    stem = core[-3]
    if not ("가" <= stem <= "힣"):
        return False
    return (ord(stem) - 0xAC00) % 28 == 17  # 받침 ㅂ


_POLITE_TAILS = ("어요", "아요", "에요", "예요", "세요", "죠", "네요", "군요", "거든요")


def ending_kind(sentence: str) -> str:
    """종결 유형. 연속 검사는 끝 3자가 아니라 이 유형으로 센다.

    끝 3자로 세면 했습니다/었습니다/갔습니다가 서로 다른 어미로 잡히는데,
    귀에는 전부 같은 소리다.
    """
    stripped = sentence.rstrip(" \t\"'”’")
    if stripped.endswith("?"):
        return "의문"
    core = sentence.rstrip(_TRAIL)
    if not core:
        return "기타"
    if is_formal(sentence):
        return "합쇼체"
    if core.endswith(_POLITE_TAILS):
        return "해요체"
    if core[-1] not in "다까":
        return "명사형"
    return "기타"


def longest_run(kinds: list[str], target: str = "합쇼체") -> int:
    """같은 종결 유형이 연달아 나온 최대 길이."""
    best = run = 0
    for k in kinds:
        run = run + 1 if k == target else 0
        best = max(best, run)
    return best


# --------------------------------------------------------------------- 접속

#: 앞 씬을 받아 여는 말. '그는/그가' 는 연결이 아니라 주어 반복이라 뺀다.
CONNECTIVES = (
    "그래서", "그러자", "그래도", "그러나", "그런데도", "그런데", "하지만",
    "그렇지만", "그럼에도", "따라서", "결국", "대신", "반면", "문제는",
    "그제야", "이제", "그 대가로", "덕분에", "그 뒤", "그때", "그 순간",
    "여기서", "여기까지", "그렇게", "이번엔", "이번에는", "다만", "드디어",
    "곧", "오히려",
)


def opens_with_connective(text: str) -> bool:
    return text.strip().startswith(CONNECTIVES)


# ------------------------------------------------------------- 나레이터 상투구

#: 나레이터가 이야기 대신 자기 얘기를 하는 표현. 챕터가 바뀌는 건 나레이터가
#: 선언하는 게 아니라 이야기 자체가 알린다.
NARRATOR_TICS = (
    # 「마지막 이야기입니다」는 '번째' 가 없어서 별도 갈래로 둔다.
    re.compile(r"(첫|두|세|네|다섯|여섯|일곱)\s*번째\s*이야기|마지막\s*이야기"),
    re.compile(r"이번\s*(챕터|장|편)"),
    re.compile(r"저는\s[^.]{0,14}(겠습니다)"),
    re.compile(r"이\s*(영상|편)에서는"),
    re.compile(r"(알아보겠습니다|살펴보겠습니다|정리해\s*보겠습니다|따라가겠습니다)"),
)


def narrator_tics(text: str) -> list[str]:
    return [m.group(0) for p in NARRATOR_TICS for m in p.finditer(text)]


# --------------------------------------------------------------------- 낱말


@lru_cache(maxsize=1)
def plain_korean() -> dict[str, str]:
    """분야가 어긋난 낱말 → 대안. 탐지용이지 치환용이 아니다.

    「저주가 성립했다」는 고쳐야 하고 「계약이 성립했다」는 옳다. 그래서
    자동 치환하지 않고 어디에 있는지만 알려준다.
    """
    path = DATA_DIR / "plain_korean.yaml"
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): str(v) for k, v in (data.get("words") or {}).items()}


def diction_hits(text: str) -> list[tuple[str, str]]:
    """(발견된 낱말, 대안) 목록."""
    return [(w, alt) for w, alt in plain_korean().items() if w in text]


# ------------------------------------------------------------------- 고유명사

#: 대본에만 있고 구성안에 없는 고유명사는 모델이 지어냈을 가능성이 있다.
#: 정밀하지 않다 — 전후 diff 용도로만 쓴다.
_PROPER = re.compile(r"([가-힣]{2,6})(?=(?:은|는|이|가|을|를|의|에게|와|과|도)[\s,.])")


def proper_nouns(text: str) -> set[str]:
    """고유명사 후보."""
    return {m.group(1) for m in _PROPER.finditer(text)}


# ------------------------------------------------------------------- 보고서


@dataclass
class Report:
    scenes: int = 0
    sentence_count: int = 0
    chars: int = 0
    formal_ratio: float = 0.0
    formal_run_max: int = 0
    adjacent_same: float = 0.0
    ending_mix: Counter = field(default_factory=Counter)
    connective_scenes: int = 0
    connective_ratio: float = 0.0
    short_ratio: float = 0.0
    len_min: int = 0
    len_med: int = 0
    len_max: int = 0
    subject_ratio: float = 0.0
    tics: list[str] = field(default_factory=list)
    diction: list[tuple[str, str, int]] = field(default_factory=list)
    mixed_tense_scenes: list[int] = field(default_factory=list)
    est_seconds: float = 0.0
    longest_scene_seconds: float = 0.0
    longest_scene_index: int = 0


_SUBJECT_START = re.compile(r"^(그는|그가|그를|그의)\b|^그\s")
_PAST = re.compile(r"(했|였|았|었)(습니다|죠|더군요|거든요|다)?$")


def measure(
    scene_texts: list[str],
    *,
    chars_per_second: float = MEASURED_CPS,
    pad: float = 1.0,
) -> Report:
    """씬별 내레이션 목록을 재서 보고서를 만든다."""
    r = Report(scenes=len(scene_texts))
    if not scene_texts:
        return r

    sents: list[str] = []
    for text in scene_texts:
        sents.extend(sentences(text))
    if not sents:
        return r

    joined = " ".join(scene_texts)
    kinds = [ending_kind(s) for s in sents]
    lengths = sorted(len(s) for s in sents)

    r.sentence_count = len(sents)
    r.chars = sum(len(t) for t in scene_texts)
    r.ending_mix = Counter(kinds)
    r.formal_ratio = r.ending_mix["합쇼체"] / len(sents)
    r.formal_run_max = longest_run(kinds)
    r.adjacent_same = (
        sum(1 for a, b in zip(kinds, kinds[1:]) if a == b) / (len(kinds) - 1)
        if len(kinds) > 1
        else 0.0
    )

    # 1번 씬은 받을 앞 씬이 없다.
    tail = scene_texts[1:]
    r.connective_scenes = sum(1 for t in tail if opens_with_connective(t))
    r.connective_ratio = r.connective_scenes / len(tail) if tail else 0.0

    r.short_ratio = sum(1 for n in lengths if n <= 15) / len(sents)
    r.len_min, r.len_max = lengths[0], lengths[-1]
    r.len_med = lengths[len(lengths) // 2]
    r.subject_ratio = sum(1 for s in sents if _SUBJECT_START.match(s)) / len(sents)
    r.tics = narrator_tics(joined)
    r.diction = [(w, alt, joined.count(w)) for w, alt in diction_hits(joined)]

    for i, text in enumerate(scene_texts, start=1):
        ends = [bool(_PAST.search(s.rstrip(_TRAIL))) for s in sentences(text)]
        if len(ends) > 1 and len(set(ends)) > 1:
            r.mixed_tense_scenes.append(i)

    per_scene = [len(t) / chars_per_second + pad for t in scene_texts]
    r.est_seconds = sum(per_scene)
    r.longest_scene_seconds = max(per_scene)
    r.longest_scene_index = per_scene.index(r.longest_scene_seconds) + 1
    return r


# ------------------------------------------------------- s2 재시도용 문제 목록


def style_problems(scene_texts: list[str]) -> list[str]:
    """s2가 재요청에 붙일 문체 지적.

    **이 목록은 대본을 반려시키지 않는다.** 고치면 좋은 문제지 못 쓸 이유가
    아니다 (`s2_script.validate` 의 소프트 실패 계약 참고).

    지적은 실행 가능해야 한다 — 몇 개를 어떻게 고치라는 건지, 지금 어느
    씬이 그런지까지 적는다. 모델은 재시도 때 새 프로세스라 이 문장이 가진
    정보가 전부다.
    """
    if len(scene_texts) < STYLE_MIN_SCENES:
        return []

    r = measure(scene_texts)
    if not r.sentence_count:
        return []

    problems: list[str] = []
    formal = r.ending_mix["합쇼체"]

    if r.formal_ratio > FORMAL_RATIO_MAX:
        need = formal - int(r.sentence_count * FORMAL_RATIO_MAX)
        problems.append(
            f"문장 {formal}/{r.sentence_count}개({r.formal_ratio:.0%})가 '-습니다'로 "
            f"끝납니다. 낭독하면 같은 박자만 반복됩니다. 최소 {need}개 문장의 끝을 "
            f"바꾸세요 (~죠 / ~더군요 / ~던 겁니다 / ~거든요 / 되묻기 / "
            f"인용을 그대로 두기)."
        )

    if r.formal_run_max > FORMAL_RUN_MAX:
        problems.append(
            f"'-습니다'로 끝나는 문장이 최대 {r.formal_run_max}개 연속입니다. "
            f"{FORMAL_RUN_MAX}개를 넘기지 마세요. 비율만 맞추고 변화를 뒤쪽에 "
            f"몰아넣으면 안 됩니다."
        )

    if r.connective_ratio < CONNECTIVE_RATIO_MIN:
        tail = len(scene_texts) - 1
        need = int(tail * CONNECTIVE_RATIO_MIN) + 1
        opening = [
            i for i, t in enumerate(scene_texts[1:], start=2) if opens_with_connective(t)
        ]
        problems.append(
            f"씬 {tail}개 중 {r.connective_scenes}개만 앞 씬을 받는 말로 시작합니다. "
            f"씬끼리 이어지는 느낌이 없습니다. 최소 {need}개 씬을 구성안 태그에 맞춰 "
            f"'그래서/그러자/결국/덕분에' 또는 '하지만/그런데/문제는/대신' 으로 "
            f"여세요. 지금 그렇게 여는 씬: {opening or '없음'}"
        )

    if r.tics:
        problems.append(
            f"나레이터가 이야기 대신 자기 얘기를 합니다: "
            f"{', '.join(sorted(set(r.tics)))}. 전부 지우세요. 챕터가 바뀌는 건 "
            f"나레이터가 선언하는 게 아니라 이야기 자체가 알립니다."
        )

    return problems
