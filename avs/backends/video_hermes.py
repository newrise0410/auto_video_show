"""Hermes의 xAI(Grok Imagine) video_gen 프로바이더를 쓰는 영상 백엔드.

Hermes 에이전트 루프를 경유하지 않고, Hermes 가상환경의 파이썬으로
`hermes_runner.py` 를 돌려 프로바이더 함수를 직접 호출한다. 자격증명은
Hermes가 이미 갖고 있는 것(슈퍼그록 / X Premium+ OAuth 토큰, 또는
`XAI_API_KEY`)을 그대로 쓴다.

프로바이더는 파일이 아니라 **URL**(files-cdn 저장본 또는 만료되는 임시
링크)을 돌려주므로, 받은 즉시 실행 디렉터리로 내려받아 보관한다.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import httpx

from ..proc import CommandFailed, run
from .base import BackendError, VideoGenRequest
from .hermes_runner import SENTINEL

RUNNER = Path(__file__).with_name("hermes_runner.py")

# 프로바이더가 이 사유들로 실패하면 다시 시도해봐야 결과가 같다.
_FATAL_ERROR_TYPES = {
    "auth_required",
    "missing_prompt",
    "invalid_image_url",
    "invalid_reference_image_urls",
    "unsupported_model",
    "conflicting_inputs",
    "too_many_references",
    "plugin_load_failed",
}

# 프로바이더 자체가 최대 240초까지 폴링한다. 넉넉하게 잡는다.
DEFAULT_TIMEOUT = 420.0


def hermes_root() -> Path:
    """Hermes 설치 루트를 찾는다."""
    override = os.environ.get("AVS_HERMES_ROOT")
    if override:
        return Path(override)

    exe = shutil.which("hermes")
    if exe:
        # .../hermes-agent/venv/Scripts/hermes  →  .../hermes-agent
        candidate = Path(exe).resolve().parents[2]
        if (candidate / "plugins" / "video_gen" / "xai").is_dir():
            return candidate

    default = Path.home() / "AppData" / "Local" / "hermes" / "hermes-agent"
    if (default / "plugins" / "video_gen" / "xai").is_dir():
        return default

    raise BackendError(
        "Hermes 설치 위치를 찾을 수 없습니다. 환경변수 AVS_HERMES_ROOT 에 "
        "hermes-agent 디렉터리 경로를 지정하세요.",
        retryable=False,
    )


def hermes_python(root: Path) -> Path:
    """Hermes 가상환경의 파이썬. 우리 인터프리터와 버전이 다를 수 있다."""
    override = os.environ.get("AVS_HERMES_PYTHON")
    if override:
        return Path(override)
    for rel in ("venv/Scripts/python.exe", "venv/bin/python", "venv/bin/python3"):
        candidate = root / rel
        if candidate.is_file():
            return candidate
    raise BackendError(
        f"Hermes 가상환경 파이썬을 찾을 수 없습니다 ({root}). "
        "환경변수 AVS_HERMES_PYTHON 으로 지정하세요.",
        retryable=False,
    )


def _call_runner(payload: dict, *, timeout: float) -> dict:
    root = hermes_root()
    python = hermes_python(root)
    payload = {**payload, "hermes_root": str(root)}

    try:
        result = run(
            [str(python), str(RUNNER)],
            stdin=json.dumps(payload, ensure_ascii=False),
            timeout=timeout,
            cwd=root,
        )
    except CommandFailed as exc:
        raise BackendError(f"Hermes 브리지 실행 실패: {exc}") from exc

    _, sep, tail = result.stdout.rpartition(SENTINEL)
    if not sep:
        raise BackendError(
            "Hermes 브리지가 결과를 돌려주지 않았습니다.\n"
            f"stdout: {result.stdout[-1000:]}\nstderr: {result.stderr[-1000:]}"
        )
    try:
        return json.loads(tail.strip())
    except json.JSONDecodeError as exc:
        raise BackendError(f"브리지 응답을 파싱할 수 없습니다: {tail[:500]}") from exc


def probe() -> dict:
    """자격증명·기능을 확인한다. 영상은 만들지 않는다 (`avs doctor` 용)."""
    return _call_runner({"action": "probe"}, timeout=120)


class HermesVideoBackend:
    name = "hermes"

    def __init__(self, model: str | None = None, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.model = model
        self.timeout = timeout

    def generate(self, request: VideoGenRequest) -> Path:
        # 프로바이더는 정수 초만 받고 1~15로 클램프한다.
        duration = max(1, min(15, round(request.duration)))

        result = _call_runner(
            {
                "action": "generate",
                "prompt": request.prompt,
                "model": self.model,
                "duration": duration,
                "aspect_ratio": request.aspect_ratio,
                "resolution": request.resolution,
            },
            timeout=self.timeout,
        )

        if not result.get("success"):
            error_type = str(result.get("error_type") or "provider_error")
            raise BackendError(
                f"Grok Imagine 실패 [{error_type}]: {result.get('error')}",
                retryable=error_type not in _FATAL_ERROR_TYPES,
            )

        source = str(result.get("video") or "").strip()
        if not source:
            raise BackendError("응답에 영상 위치가 없습니다")

        request.out_path.parent.mkdir(parents=True, exist_ok=True)
        if source.lower().startswith(("http://", "https://")):
            _download(source, request.out_path)
        else:
            local = Path(source)
            if not local.is_file():
                raise BackendError(f"프로바이더가 알려준 경로에 파일이 없습니다: {local}")
            shutil.copyfile(local, request.out_path)

        if request.out_path.stat().st_size == 0:
            raise BackendError("내려받은 클립이 비어 있습니다")
        return request.out_path


def _download(url: str, out_path: Path) -> None:
    """임시 링크는 금방 만료되므로 받자마자 디스크에 고정한다."""
    tmp = out_path.with_suffix(out_path.suffix + ".part")
    try:
        with httpx.stream("GET", url, timeout=120, follow_redirects=True) as response:
            response.raise_for_status()
            with tmp.open("wb") as fh:
                for chunk in response.iter_bytes(chunk_size=1 << 16):
                    fh.write(chunk)
    except httpx.HTTPError as exc:
        tmp.unlink(missing_ok=True)
        raise BackendError(f"클립 다운로드 실패: {exc}") from exc
    tmp.replace(out_path)
