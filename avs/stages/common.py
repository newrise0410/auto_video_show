"""스테이지들이 공유하는 마무리 로직."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from ..config import slugify
from ..media.probe import probe
from ..models import Script
from ..state import Run


def final_slug(run: Run, script: Script) -> str:
    return slugify(script.title or run.manifest.topic, max_len=48)


def write_metadata(run: Run, script: Script, video: Path) -> Path:
    """업로드에 필요한 정보를 영상 옆에 같이 남긴다."""
    media = probe(video)
    payload = {
        "run_id": run.id,
        "topic": run.manifest.topic,
        "profile": run.manifest.profile_name,
        "title": script.title,
        "description": script.description,
        "hashtags": script.hashtags,
        "video": str(video),
        "width": media.width,
        "height": media.height,
        "duration": round(media.duration, 2),
        "has_audio": media.has_audio,
        "scenes": [
            {
                "index": s.index,
                "narration": s.narration,
                "on_screen_text": s.on_screen_text,
            }
            for s in script.scenes
        ],
    }
    out = video.with_suffix(".json")
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def scene_durations(run: Run, script: Script) -> list[float]:
    """정규화 결과에 기록된 실제 길이. 없으면 프로파일 기준값으로 대체한다."""
    durations: list[float] = []
    for scene in script.scenes:
        artifact = run.manifest.scene_artifact(scene.index)
        durations.append(artifact.duration or run.profile.scene_duration)
    return durations


def reveal(path: Path) -> None:
    """탐색기/파인더로 폴더를 연다. 실패해도 파이프라인을 막지 않는다."""
    if os.environ.get("AVS_NO_REVEAL"):
        return
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # noqa: S606 - 사용자에게 폴더를 보여주는 용도
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')  # noqa: S605
        else:
            os.system(f'xdg-open "{path}"')  # noqa: S605
    except Exception:  # noqa: BLE001 - 부가 기능
        pass
