"""로컬 TTS 백엔드 — 별도 가상환경의 파이썬으로 브리지 스크립트를 실행한다.

`video_hermes.py` 와 같은 구조다. 다른 점은 **배치**로 부른다는 것: 모델
로딩이 합성보다 훨씬 비싸서(수십 초) 씬 하나마다 프로세스를 띄우면 로딩
비용이 씬 수만큼 곱해진다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from ..proc import CommandFailed, run
from ..tts.runner import SENTINEL
from .base import BackendError

RUNNER = Path(__file__).resolve().parent.parent / "tts" / "runner.py"

# 모델 로딩(수십 초) + 배치 합성까지 넉넉하게. 씬 수에 따라 늘려 잡는다.
BASE_TIMEOUT = 300.0
PER_ITEM_TIMEOUT = 60.0


@dataclass
class VoiceConfig:
    """프로파일의 `narration` 블록이 그대로 들어온다."""

    model: str = "supertonic"
    voice: str | None = None
    reference_audio: str | None = None
    speed: float = 1.0
    language: str | None = None
    device: str = "auto"
    extra: dict = field(default_factory=dict)

    def to_payload(self) -> dict:
        payload = {
            "voice": self.voice,
            "reference_audio": self.reference_audio,
            "speed": self.speed,
            "language": self.language,
            "device": self.device,
        }
        payload.update(self.extra)
        return payload


@dataclass
class SynthItem:
    id: str
    text: str
    out_path: Path
    language: str | None = None

    def to_payload(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "out_path": str(self.out_path),
            "language": self.language,
        }


def _call_runner(model: str, payload: dict, *, timeout: float) -> dict:
    try:
        python = config.tts_python(model)
    except config.ToolNotFound as exc:
        raise BackendError(str(exc), retryable=False) from exc

    try:
        result = run(
            [str(python), str(RUNNER)],
            stdin=json.dumps(payload, ensure_ascii=False),
            timeout=timeout,
        )
    except CommandFailed as exc:
        raise BackendError(f"TTS 브리지 실행 실패: {exc}") from exc

    _, sep, tail = result.stdout.rpartition(SENTINEL)
    if not sep:
        raise BackendError(
            "TTS 브리지가 결과를 돌려주지 않았습니다.\n"
            f"stdout: {result.stdout[-1000:]}\nstderr: {result.stderr[-1000:]}"
        )
    try:
        return json.loads(tail.strip())
    except json.JSONDecodeError as exc:
        raise BackendError(f"브리지 응답을 파싱할 수 없습니다: {tail[:500]}") from exc


def probe(model: str) -> dict:
    """설치·기능 확인. 모델을 메모리에 올리지 않는다 (`avs doctor` 용)."""
    return _call_runner(model, {"action": "probe", "model": model}, timeout=180)


class LocalTTSBackend:
    name = "local"

    def __init__(self, voice: VoiceConfig) -> None:
        self.voice = voice
        #: 직전 배치에서 모델을 올리는 데 걸린 시간. 배치가 클수록 무시할 만해진다.
        self.last_load_seconds = 0.0

    @property
    def model(self) -> str:
        return self.voice.model

    def synthesize_batch(self, items: list[SynthItem]) -> list[dict]:
        """여러 문장을 한 프로세스에서 합성한다.

        개별 문장 실패는 결과 항목의 `success: False` 로 돌아온다. 배치 전체가
        죽는 건 모델 로딩 실패나 브리지 오류일 때뿐이다.
        """
        if not items:
            return []

        payload = {
            "action": "synthesize",
            "model": self.model,
            "config": self.voice.to_payload(),
            "items": [item.to_payload() for item in items],
        }
        timeout = BASE_TIMEOUT + PER_ITEM_TIMEOUT * len(items)
        response = _call_runner(self.model, payload, timeout=timeout)

        if not response.get("success"):
            raise BackendError(
                f"TTS 실패 [{response.get('error_type', 'unknown')}]: {response.get('error')}",
                retryable=response.get("error_type") not in {"adapter_load_failed"},
            )
        self.last_load_seconds = float(response.get("load_seconds") or 0.0)
        return response.get("results") or []

    def synthesize(self, text: str, out_path: Path) -> Path:
        """`TTSBackend` Protocol 호환용 단건 합성."""
        results = self.synthesize_batch([SynthItem(id="0", text=text, out_path=out_path)])
        if not results or not results[0].get("success"):
            error = results[0].get("error") if results else "결과가 비어 있습니다"
            raise BackendError(f"합성 실패: {error}")
        return out_path
