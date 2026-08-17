"""s6 — Vrew에서 내보낸 결과를 회수해 최종본으로 정리한다."""

from __future__ import annotations

import shutil
from pathlib import Path

from ..console import info, ok, warn
from ..media.probe import probe
from ..state import Run
from .common import final_slug, write_metadata

_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm"}


def find_export(run: Run) -> Path | None:
    """`vrew_out/` 에서 가장 최근에 들어온 영상 파일을 고른다."""
    candidates = [
        p
        for p in run.paths.vrew_out.glob("*")
        if p.is_file() and p.suffix.lower() in _VIDEO_SUFFIXES
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def run_stage(run: Run, *, source: Path | None = None) -> Path:
    script = run.read_script()

    with run.stage("s6") as state:
        export = source or find_export(run)
        if export is None:
            raise RuntimeError(
                f"{run.paths.vrew_out} 에서 영상 파일을 찾지 못했습니다.\n"
                "Vrew에서 내보낸 mp4를 이 폴더에 넣고 다시 실행하세요."
            )

        media = probe(export)
        profile = run.profile

        if not media.has_video:
            raise RuntimeError(f"영상 스트림이 없습니다: {export}")
        if (media.width, media.height) != (profile.width, profile.height):
            warn(
                f"해상도가 프로파일과 다릅니다: {media.size_label} "
                f"(기대 {profile.aspect_label})"
            )
        if not media.has_audio:
            warn("오디오 트랙이 없습니다. Vrew에서 내레이션이 빠졌는지 확인하세요.")

        target = run.paths.final / f"{final_slug(run, script)}{export.suffix.lower()}"
        shutil.copyfile(export, target)
        meta = write_metadata(run, script, target)

        info(f"{media.size_label}, {media.duration:.1f}초, 오디오 {'있음' if media.has_audio else '없음'}")
        ok(f"최종본: {target}")

        state.outputs["final"] = str(target)
        state.outputs["metadata"] = str(meta)
        state.outputs["source"] = str(export)

    return target
