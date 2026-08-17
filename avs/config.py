"""경로 해석, 프로파일 로딩, 외부 실행 파일 탐색."""

from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path

import yaml

from .models import Profile

PACKAGE_DIR = Path(__file__).resolve().parent
BUILTIN_PROFILE_DIR = PACKAGE_DIR / "profiles"


def project_root() -> Path:
    """산출물을 쌓을 루트. 기본은 현재 작업 디렉터리."""
    return Path(os.environ.get("AVS_ROOT", Path.cwd())).resolve()


def runs_dir() -> Path:
    return project_root() / "runs"


class ToolNotFound(RuntimeError):
    pass


def find_tool(name: str, *, env_var: str | None = None, required: bool = True) -> str:
    """외부 CLI 경로를 찾는다. 환경변수 오버라이드를 먼저 본다."""
    env_var = env_var or f"AVS_{name.upper().replace('-', '_')}"
    override = os.environ.get(env_var)
    if override:
        return override
    found = shutil.which(name)
    if found:
        return found
    if required:
        raise ToolNotFound(
            f"'{name}' 을(를) PATH에서 찾을 수 없습니다. "
            f"설치하거나 환경변수 {env_var} 에 절대경로를 지정하세요."
        )
    return name


def ffmpeg() -> str:
    return find_tool("ffmpeg")


def ffprobe() -> str:
    return find_tool("ffprobe")


# ------------------------------------------------------------------- TTS 가상환경

TTS_VENV_DIRNAME = ".venv-tts"


def tts_venv_root() -> Path:
    override = os.environ.get("AVS_TTS_VENV_ROOT")
    return Path(override) if override else project_root() / TTS_VENV_DIRNAME


def tts_python(model: str) -> Path:
    """모델별 TTS 가상환경의 파이썬.

    PyTorch CUDA 휠이 Python 3.14(Windows)에 올라오지 않아서 TTS 모델은
    프로젝트 venv에 넣을 수 없다. 후보 모델끼리도 의존성이 충돌하므로
    모델마다 venv를 따로 둔다.
    """
    override = os.environ.get(f"AVS_TTS_PYTHON_{model.upper()}") or os.environ.get(
        "AVS_TTS_PYTHON"
    )
    if override:
        return Path(override)

    base = tts_venv_root() / model
    for rel in ("Scripts/python.exe", "bin/python", "bin/python3"):
        candidate = base / rel
        if candidate.is_file():
            return candidate
    raise ToolNotFound(
        f"'{model}' TTS 가상환경을 찾을 수 없습니다 ({base}).\n"
        f"docs/tts-setup.md 를 따라 만들거나 환경변수 "
        f"AVS_TTS_PYTHON_{model.upper()} 로 파이썬 경로를 지정하세요."
    )


def installed_tts_models() -> list[str]:
    root = tts_venv_root()
    if not root.is_dir():
        return []
    names = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        if (d / "Scripts" / "python.exe").is_file() or (d / "bin" / "python").is_file():
            names.append(d.name)
    return names


# --------------------------------------------------------------------------- 프로파일


def profile_search_paths() -> list[Path]:
    """프로젝트 로컬 프로파일이 패키지 내장 프로파일보다 우선한다."""
    return [project_root() / "profiles", BUILTIN_PROFILE_DIR]


def available_profiles() -> list[str]:
    names: list[str] = []
    for d in profile_search_paths():
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.yaml")):
            if f.stem not in names:
                names.append(f.stem)
    return names


def load_profile(name: str) -> Profile:
    for d in profile_search_paths():
        path = d / f"{name}.yaml"
        if path.is_file():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            data.setdefault("name", name)
            return Profile.model_validate(data)
    raise FileNotFoundError(
        f"프로파일 '{name}' 을(를) 찾을 수 없습니다. "
        f"사용 가능: {', '.join(available_profiles()) or '(없음)'}"
    )


# --------------------------------------------------------------------------- run id

_SLUG_STRIP = re.compile(r"[^\w가-힣ㄱ-ㅎㅏ-ㅣ-]", re.UNICODE)
_SLUG_DASH = re.compile(r"-{2,}")


def slugify(text: str, *, max_len: int = 40) -> str:
    s = text.strip().replace(" ", "-")
    s = _SLUG_STRIP.sub("", s)
    s = _SLUG_DASH.sub("-", s).strip("-")
    return (s[:max_len] or "untitled").strip("-")


def new_run_id(topic: str, *, now: datetime | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{slugify(topic, max_len=32)}"


def run_dir(run_id: str) -> Path:
    return runs_dir() / run_id


def resolve_run_id(run_id: str | None) -> str:
    """run_id 생략 시 가장 최근 실행을 고른다."""
    if run_id:
        return run_id
    root = runs_dir()
    if not root.is_dir():
        raise FileNotFoundError("아직 실행 기록이 없습니다.")
    candidates = [d for d in root.iterdir() if (d / "manifest.json").is_file()]
    if not candidates:
        raise FileNotFoundError("아직 실행 기록이 없습니다.")
    return max(candidates, key=lambda d: d.stat().st_mtime).name
