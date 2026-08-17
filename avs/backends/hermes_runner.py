"""Hermes 가상환경 안에서 실행되는 브리지 스크립트.

이 파일만은 **Hermes 쪽 파이썬(3.11)** 이 실행한다. `avs` 패키지의 어떤
것도 임포트하면 안 되고 표준 라이브러리만 쓴다.

에이전트 루프(`hermes -z`)를 태우지 않고 xAI video_gen 프로바이더 함수를
직접 부른다. 토큰을 쓰지 않고, 응답이 구조화되어 있으며, 모델이 도구를
쓸지 말지 마음을 바꿀 여지가 없다.

stdin  : 요청 JSON 한 덩어리
stdout : 잡다한 임포트 로그 뒤에 `<<<AVS_RESULT>>>` 센티널 + 결과 JSON
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SENTINEL = "<<<AVS_RESULT>>>"


def _load_xai_provider(root: Path):
    # 프로바이더가 `agent.*`, `tools.*` 를 임포트하므로 루트를 경로에 얹는다.
    sys.path.insert(0, str(root))
    plugin = root / "plugins" / "video_gen" / "xai" / "__init__.py"
    if not plugin.is_file():
        raise FileNotFoundError(f"xAI video_gen 플러그인을 찾을 수 없습니다: {plugin}")
    spec = importlib.util.spec_from_file_location("avs_xai_video_gen", plugin)
    if spec is None or spec.loader is None:
        raise ImportError(f"플러그인을 로드할 수 없습니다: {plugin}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    request = json.loads(sys.stdin.read())
    root = Path(request["hermes_root"])

    try:
        provider = _load_xai_provider(root)
    except Exception as exc:  # noqa: BLE001 - 실패도 구조화해서 돌려준다
        result = {
            "success": False,
            "error": f"{type(exc).__name__}: {exc}",
            "error_type": "plugin_load_failed",
        }
    else:
        action = request.get("action", "generate")
        if action == "probe":
            result = {
                "success": True,
                "has_credentials": bool(provider.has_xai_video_credentials()),
                "capabilities": provider.XAIVideoGenProvider().capabilities(),
                "models": provider.XAIVideoGenProvider().list_models(),
            }
        else:
            model = request.get("model") or None
            result = provider.run_xai_video_generation(
                prompt=request["prompt"],
                model=model,
                explicit_model=bool(model),
                image_url=None,
                reference_image_urls=None,
                duration=int(request["duration"]),
                aspect_ratio=request["aspect_ratio"],
                resolution=request["resolution"],
            )

    sys.stdout.write("\n" + SENTINEL + json.dumps(result, ensure_ascii=False, default=str))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
