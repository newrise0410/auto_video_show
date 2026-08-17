"""TTS 전용 가상환경 안에서 실행되는 브리지 스크립트.

이 파일과 `models/` 아래 모듈들만은 **TTS venv의 파이썬**이 실행한다.
`avs` 패키지의 어떤 것도 임포트하면 안 된다 — 프로젝트 venv(3.14)에는
PyTorch CUDA 휠이 없어서 모델을 같은 인터프리터에 올릴 수 없기 때문이다.

`avs/backends/hermes_runner.py` 와 같은 규약을 쓴다.

stdin  : 요청 JSON 한 덩어리
stdout : 모델 로딩 로그 뒤에 `<<<AVS_TTS_RESULT>>>` 센티널 + 결과 JSON

요청은 **배치**다. 모델 로딩이 합성보다 훨씬 비싸서(수십 초) 프로세스 하나가
여러 문장을 처리해야 의미가 있다.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

SENTINEL = "<<<AVS_TTS_RESULT>>>"


def _emit(payload: dict) -> int:
    sys.stdout.write("\n" + SENTINEL + json.dumps(payload, ensure_ascii=False, default=str))
    sys.stdout.flush()
    return 0


def main() -> int:
    try:
        # PowerShell 파이프로 직접 넣어 손으로 시험할 때 BOM이 붙는다.
        request = json.loads(sys.stdin.read().lstrip("﻿"))
    except json.JSONDecodeError as exc:
        return _emit({"success": False, "error": f"요청 JSON 파싱 실패: {exc}"})

    # 모델 어댑터는 이 파일 옆의 `models/` 패키지에 있다. `avs` 를 거치지 않고
    # 직접 임포트할 수 있도록 이 디렉터리를 경로에 얹는다.
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    model_name = request.get("model", "")
    try:
        import models

        adapter = models.load_adapter(model_name)
    except Exception as exc:  # noqa: BLE001 - 실패도 구조화해서 돌려준다
        return _emit(
            {
                "success": False,
                "error": f"{type(exc).__name__}: {exc}",
                "error_type": "adapter_load_failed",
                "traceback": traceback.format_exc()[-2000:],
            }
        )

    action = request.get("action", "synthesize")
    config = request.get("config") or {}

    if action == "probe":
        try:
            return _emit({"success": True, **adapter.probe()})
        except Exception as exc:  # noqa: BLE001
            return _emit(
                {
                    "success": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "error_type": "probe_failed",
                    "traceback": traceback.format_exc()[-2000:],
                }
            )

    try:
        started = time.monotonic()
        engine = adapter.load(config)
        load_seconds = time.monotonic() - started
    except Exception as exc:  # noqa: BLE001
        return _emit(
            {
                "success": False,
                "error": f"모델 로딩 실패: {type(exc).__name__}: {exc}",
                "error_type": "model_load_failed",
                "traceback": traceback.format_exc()[-2000:],
            }
        )

    results = []
    for item in request.get("items") or []:
        started = time.monotonic()
        try:
            out = adapter.synthesize(engine, item, config)
        except Exception as exc:  # noqa: BLE001 - 한 문장이 실패해도 나머지는 계속
            results.append(
                {
                    "id": item.get("id"),
                    "success": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc()[-1200:],
                }
            )
            continue
        results.append(
            {
                "id": item.get("id"),
                "success": True,
                "synth_seconds": round(time.monotonic() - started, 3),
                **out,
            }
        )

    return _emit(
        {
            "success": True,
            "model": model_name,
            "load_seconds": round(load_seconds, 3),
            "results": results,
        }
    )


if __name__ == "__main__":
    raise SystemExit(main())
