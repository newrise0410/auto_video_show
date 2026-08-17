"""LLM 스테이지가 쓰는 프롬프트와, 백엔드가 읽는 작업 헤더.

시스템 프롬프트 앞에 `AVS-TASK` / `AVS-META` 두 줄을 붙인다. 실제 모델은 이걸
그냥 맥락으로 받고, mock 백엔드는 여기서 무엇을 흉내 낼지 읽는다.
"""

from __future__ import annotations

import json

from .models import Profile

TASK_LINE = "AVS-TASK:"
META_LINE = "AVS-META:"


def task_header(task: str, meta: dict[str, object] | None = None) -> str:
    payload = json.dumps(meta or {}, ensure_ascii=False)
    return f"{TASK_LINE} {task}\n{META_LINE} {payload}"


def parse_task_header(system: str) -> tuple[str, dict[str, str]]:
    task = ""
    meta: dict[str, str] = {}
    for line in system.splitlines()[:4]:
        line = line.strip()
        if line.startswith(TASK_LINE):
            task = line[len(TASK_LINE) :].strip()
        elif line.startswith(META_LINE):
            try:
                raw = json.loads(line[len(META_LINE) :].strip())
            except json.JSONDecodeError:
                raw = {}
            meta = {str(k): str(v) for k, v in raw.items()}
    return task, meta


# --------------------------------------------------------------------- s1 기획


def outline_system(profile: Profile, topic: str) -> str:
    return task_header("outline", {"topic": topic, "profile": profile.name}) + f"""

당신은 한국어 영상 기획자입니다. 주제 하나를 받아 {profile.name} 포맷
({profile.aspect_label}, 약 {int(profile.target_duration)}초) 영상의 구성안을 씁니다.

출력은 마크다운 한 편입니다. 다른 설명이나 인사말을 붙이지 마세요.
다음 항목을 포함하세요:

- `# 제목` — 클릭을 부르되 과장하지 않는 제목
- `## 훅` — 첫 3초에 쓸 문장 후보 2개
- `## 전개` — 다룰 논점을 순서대로 나열. 각 항목은 한 줄
- `## 마무리` — 마지막에 남길 메시지
- `## 참고` — 사실 확인이 필요한 지점이 있으면 명시

{profile.style_notes}"""


def outline_user(topic: str) -> str:
    return f"주제: {topic}\n\n이 주제로 구성안을 작성하세요."


# --------------------------------------------------------------------- s2 대본


def script_system(profile: Profile, topic: str, scene_count: int) -> str:
    limit = profile.narration_limit
    return task_header(
        "script",
        {
            "topic": topic,
            "profile": profile.name,
            "scenes": scene_count,
            "max_chars": limit,
        },
    ) + f"""

당신은 한국어 영상 대본 작가입니다. 구성안을 받아 씬 단위 대본을 JSON으로 씁니다.

절대 규칙:
1. 출력은 JSON 객체 **하나뿐**입니다. 코드펜스, 주석, 설명을 붙이지 마세요.
2. 씬은 정확히 {scene_count}개입니다. `index`는 1부터 {scene_count}까지 연속입니다.
3. 각 씬의 `narration`은 공백 포함 {limit}자 이하입니다. 이 상한은 씬 하나가
   {profile.scene_duration:g}초 고정이기 때문이며, 초과하면 대본이 반려됩니다.
4. `video_prompt`는 **영어**로 씁니다. 영상 생성 모델에 그대로 들어갑니다.
   피사체, 동작, 카메라 워크, 조명, 분위기를 담고 화면에 글자가 나오지 않게 합니다.
   실존 인물의 이름이나 상표를 쓰지 마세요.
5. `on_screen_text`는 화면에 띄울 짧은 한국어 키워드입니다. 12자 이하.

스키마:
{{
  "title": "문자열",
  "description": "문자열 (2~3문장)",
  "hashtags": ["#태그", ...],
  "scenes": [
    {{"index": 1, "narration": "…", "video_prompt": "…", "on_screen_text": "…"}}
  ]
}}

포맷: {profile.name} ({profile.aspect_label})
{profile.style_notes}"""


def script_user(topic: str, outline: str, scene_count: int) -> str:
    return (
        f"주제: {topic}\n\n"
        f"구성안:\n{outline}\n\n"
        f"위 구성안을 {scene_count}개 씬 대본으로 옮기세요. JSON만 출력하세요."
    )


def script_retry_user(problems: list[str]) -> str:
    joined = "\n".join(f"- {p}" for p in problems)
    return (
        "직전 출력이 규칙을 어겼습니다. 아래 문제를 모두 고쳐서 "
        "JSON 객체 하나만 다시 출력하세요.\n\n" + joined
    )
