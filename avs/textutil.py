"""LLM 출력에서 구조화된 값을 꺼내기 위한 헬퍼."""

from __future__ import annotations

import json
from typing import Any


def strip_code_fence(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def extract_json_object(text: str) -> dict[str, Any]:
    """JSON만 달라고 해도 앞뒤에 말을 붙이는 경우가 있어서 관대하게 파싱한다."""
    cleaned = strip_code_fence(text)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(cleaned[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    preview = cleaned[:300].replace("\n", " ")
    raise ValueError(f"응답에서 JSON 객체를 찾지 못했습니다: {preview}")
