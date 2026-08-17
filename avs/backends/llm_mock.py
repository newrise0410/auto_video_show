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
            "## 훅\n시청자의 통념을 뒤집는 한 문장으로 연다.\n\n"
            "## 전개\n1. 문제 제기\n2. 원인\n3. 해결\n\n"
            "## 마무리\n다음 행동을 유도한다.\n"
        )

    def _script(self, meta: dict[str, str]) -> str:
        topic = meta.get("topic", "테스트 주제")
        count = int(meta.get("scenes", "8"))
        limit = int(meta.get("max_chars", "26"))

        scenes = []
        for i in range(1, count + 1):
            narration = f"{i}번 장면 여기서 핵심을 한 문장으로 말합니다"[:limit].strip()
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
