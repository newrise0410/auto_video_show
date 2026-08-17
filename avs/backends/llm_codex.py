"""`codex exec` 를 텍스트 생성기로 쓰는 백엔드 (claude 폴백)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from .. import config
from ..proc import CommandFailed, run
from .base import BackendError


class CodexCliBackend:
    name = "codex"

    def __init__(self, model: str | None = None) -> None:
        self.model = model

    def complete(self, prompt: str, *, system: str | None = None, timeout: float = 300) -> str:
        # codex 에는 별도 시스템 프롬프트 인자가 없어서 앞에 붙인다.
        full = f"{system}\n\n---\n\n{prompt}" if system else prompt

        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "last_message.txt"
            cmd = [
                config.find_tool("codex"),
                "exec",
                "--skip-git-repo-check",
                "--sandbox", "read-only",
                "--output-last-message", str(out_file),
            ]
            if self.model:
                cmd += ["--model", self.model]
            cmd.append("-")  # 프롬프트는 stdin 으로

            try:
                run(cmd, stdin=full, timeout=timeout)
            except CommandFailed as exc:
                raise BackendError(f"codex 호출 실패: {exc}") from exc

            if not out_file.is_file():
                raise BackendError("codex 가 최종 메시지를 남기지 않았습니다")
            text = out_file.read_text(encoding="utf-8", errors="replace").strip()

        if not text:
            raise BackendError("codex 가 빈 응답을 돌려줬습니다")
        return text
