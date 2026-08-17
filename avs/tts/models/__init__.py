"""TTS 모델 어댑터 레지스트리.

이 패키지는 **TTS venv 안에서** `runner.py` 가 임포트한다. `avs` 를 참조하면
안 된다.

어댑터 하나는 세 함수만 노출한다:

    probe() -> dict                        설치·기능 확인 (모델 로딩 없이 가볍게)
    load(config: dict) -> engine           모델을 메모리에 올린다 (비쌈, 1회)
    synthesize(engine, item, config) -> dict   {path, duration, sample_rate}
"""

from __future__ import annotations

import importlib

ADAPTERS = ("supertonic", "chatterbox")


def load_adapter(name: str):
    if name not in ADAPTERS:
        raise ValueError(f"알 수 없는 TTS 모델: {name} (가능: {', '.join(ADAPTERS)})")
    return importlib.import_module(f"models.{name}")
