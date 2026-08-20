"""LLM 없이 파이프라인을 돌리기 위한 가짜 백엔드.

시스템 프롬프트 첫 줄의 `AVS-TASK:` 헤더(`prompts.task_header`)를 읽어서
어떤 산출물을 흉내 낼지 정한다. 실제 백엔드는 이 헤더를 그냥 지시문의
일부로 받는다.
"""

from __future__ import annotations

import json

from ..prompts import parse_task_header


class MockLLMBackend:
    name = "mock"

    def complete(self, prompt: str, *, system: str | None = None, timeout: float = 300) -> str:
        task, meta = parse_task_header(system or "")
        if task == "script":
            return self._script(meta)
        return self._outline(meta)

    # ------------------------------------------------------------------

    def _outline(self, meta: dict[str, str]) -> str:
        topic = meta.get("topic", "테스트 주제")
        return (
            f"# {topic}\n\n"
            "## 논지\n통념과 달리 이 주제의 핵심은 하나뿐이다.\n\n"
            "## 훅\n시청자의 통념을 뒤집는 한 문장으로 연다.\n\n"
            "## 전개\n"
            "- [핵심][전환] 문제를 눈에 보이게 제기한다\n"
            "- [핵심][그래서] 그래서 이런 원인이 드러난다\n"
            "- [선택][하지만] 그런데 통념은 반대로 말한다\n"
            "- [핵심][그래서] 결국 이렇게 풀린다\n\n"
            "## 마무리\n보여준 장면 위에서 닫는다.\n"
        )

    #: 씬별 내레이션 틀. 어미를 돌려 둔다 — mock 이 문체 검사(`avs/quality.py`)에
    #: 걸리면 mock 실행이 매번 재시도 3회를 태우고, 스모크 테스트가 아니라
    #: 노이즈가 된다. 접속으로 여는 씬도 4분의 1을 넘긴다.
    _NARRATION_FORMS = (
        "{i}번 장면입니다. 여기서 핵심을 한 문장으로 말합니다.",
        "그래서 {i}번 장면에서는 앞의 결과가 드러나죠.",
        "하지만 {i}번 장면은 그 기대를 뒤집던 겁니다.",
        "결국 {i}번 장면까지 오면 답이 보이거든요.",
        "{i}번 장면, 여기서 무엇이 달라졌을까요?",
    )

    #: 하한을 채울 때 **앞에** 덧붙이는 문장. 뒤에 붙이면 위 어미가 전부
    #: 덮여서 문체 검사에 걸린다 — mock 이 검사를 통과해야 재시도 3회를
    #: 태우지 않는다.
    _LEAD_FORMS = (
        "앞에서 본 것을 잠깐 짚고 가죠.",
        "여기서 흐름이 한 번 꺾입니다.",
        "이 대목이 왜 중요할까요?",
        "배경을 조금만 더 보태던 겁니다.",
    )

    def _script(self, meta: dict[str, str]) -> str:
        topic = meta.get("topic", "테스트 주제")
        count = int(meta.get("scenes", "8"))
        limit = int(meta.get("max_chars", "26"))
        floor = int(meta.get("min_avg_chars", "0"))

        scenes = []
        for i in range(1, count + 1):
            narration = self._NARRATION_FORMS[(i - 1) % len(self._NARRATION_FORMS)].format(i=i)
            lead = 0
            while floor and len(narration) < floor:
                prefix = self._LEAD_FORMS[(i + lead) % len(self._LEAD_FORMS)]
                if len(prefix) + 1 + len(narration) > limit:
                    break
                narration = f"{prefix} {narration}"
                lead += 1
            # 세 씬에 하나는 앞 씬을 받는 말로 연다 (`quality.CONNECTIVE_RATIO_MIN`).
            # 접속은 맨 바깥에 붙여야 씬의 첫 낱말이 된다.
            if i % 3 == 0:
                opener = ("그래서", "하지만", "결국")[(i // 3) % 3]
                if len(opener) + 1 + len(narration) <= limit:
                    narration = f"{opener} {narration}"
            narration = narration[:limit].strip()
            scenes.append(
                {
                    "index": i,
                    "narration": narration,
                    "video_prompt": (
                        f"cinematic shot number {i} illustrating {topic}, "
                        "soft natural light, shallow depth of field, slow camera push in"
                    ),
                    "on_screen_text": f"포인트 {i}",
                }
            )

        return json.dumps(
            {
                "title": f"{topic} — 목 실행",
                "description": f"{topic}에 대한 mock 대본입니다.",
                "hashtags": ["#테스트", "#자동화", "#mock"],
                "scenes": scenes,
            },
            ensure_ascii=False,
            indent=2,
        )
