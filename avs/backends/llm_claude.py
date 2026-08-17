"""`claude -p` (Claude Code 헤드리스)를 텍스트 생성기로 쓰는 백엔드."""

from __future__ import annotations

import json

from .. import config
from ..proc import CommandFailed, run
from .base import BackendError

# 순수 텍스트 생성만 시킨다. 파일을 뒤지거나 셸을 돌릴 이유가 없고,
# 도구 호출이 끼면 출력이 오염되고 느려진다.
_DISALLOWED = "Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,Task,NotebookEdit"


class ClaudeCliBackend:
    name = "claude"

    def __init__(self, model: str | None = None) -> None:
        self.model = model

    def complete(self, prompt: str, *, system: str | None = None, timeout: float = 300) -> str:
        cmd = [
            config.find_tool("claude"),
            "-p",
            "--output-format", "json",
            "--disallowed-tools", _DISALLOWED,
        ]
        if system:
            cmd += ["--system-prompt", system]
        if self.model:
            cmd += ["--model", self.model]

        try:
            result = run(cmd, stdin=prompt, timeout=timeout)
        except CommandFailed as exc:
            raise BackendError(f"claude 호출 실패: {exc}") from exc

        return _extract_result(result.stdout)


def _extract_result(stdout: str) -> str:
    """`--output-format json` 응답에서 최종 텍스트만 꺼낸다."""
    stdout = stdout.strip()
    if not stdout:
        raise BackendError("claude 가 빈 응답을 돌려줬습니다")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        # 포맷이 바뀌었거나 경고가 섞인 경우. 텍스트 그대로 쓴다.
        return stdout

    if isinstance(payload, dict):
        if payload.get("is_error"):
            raise BackendError(f"claude 오류 응답: {payload.get('result') or payload}")
        text = payload.get("result")
        if isinstance(text, str):
            return text
    return stdout
