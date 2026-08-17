"""외부 도구를 감싸는 백엔드 인터페이스.

파이프라인 스테이지는 구체 구현이 아니라 이 Protocol에만 의존한다. 덕분에
계정·구독·네트워크 없이도 mock 백엔드로 전체 파이프라인을 관통시킬 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


class BackendError(RuntimeError):
    """백엔드 호출 실패. 재시도 가능 여부를 `retryable` 로 구분한다."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class VideoGenRequest:
    prompt: str
    out_path: Path
    duration: float
    #: "9:16" / "16:9" 등. 백엔드가 지원하면 네이티브로 그 비율을 받는다.
    aspect_ratio: str = "16:9"
    #: "480p" / "720p". 최종 캔버스 크기가 아니라 소스 해상도 요청값이다.
    #: 캔버스 맞춤과 업스케일은 뒤의 정규화 단계가 책임진다.
    resolution: str = "720p"


@runtime_checkable
class VideoGenBackend(Protocol):
    name: str

    def generate(self, request: VideoGenRequest) -> Path:
        """클립을 만들고 실제로 저장된 파일 경로를 돌려준다."""
        ...


@runtime_checkable
class LLMBackend(Protocol):
    name: str

    def complete(self, prompt: str, *, system: str | None = None, timeout: float = 300) -> str:
        """프롬프트를 넣고 모델의 최종 텍스트만 돌려준다."""
        ...


@runtime_checkable
class TTSBackend(Protocol):
    name: str

    def synthesize(self, text: str, out_path: Path) -> Path:
        ...


# ------------------------------------------------------------------ 레지스트리


def get_video_backend(name: str) -> VideoGenBackend:
    if name == "mock":
        from .video_mock import MockVideoBackend

        return MockVideoBackend()
    if name == "hermes":
        from .video_hermes import HermesVideoBackend

        return HermesVideoBackend()
    raise ValueError(f"알 수 없는 영상 백엔드: {name} (가능: mock, hermes)")


def get_llm_backend(name: str) -> LLMBackend:
    if name == "claude":
        from .llm_claude import ClaudeCliBackend

        return ClaudeCliBackend()
    if name == "codex":
        from .llm_codex import CodexCliBackend

        return CodexCliBackend()
    if name == "mock":
        from .llm_mock import MockLLMBackend

        return MockLLMBackend()
    raise ValueError(f"알 수 없는 LLM 백엔드: {name} (가능: claude, codex, mock)")
