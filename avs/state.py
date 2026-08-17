"""실행 상태(매니페스트) 관리와 스테이지 실행 규약.

파이프라인의 재개 가능성은 전부 여기서 나온다. 스테이지는 `Run.stage()`
컨텍스트 안에서만 돌고, 진입/종료 시점에 매니페스트가 디스크로 내려간다.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from . import config
from .models import (
    Profile,
    RunManifest,
    RunPaths,
    Script,
    StageState,
    StageStatus,
    utcnow,
)

# 파이프라인 순서. `--from` 옵션이 이 순서를 기준으로 자른다.
#
# 스테이지 id는 이 리스트가 순서를 정하는 불투명 키다(사전순 정렬이 아님).
# 그래서 s2와 s3 사이에 "narrate" 를 끼워도 안전하고, 이 단계가 없던 시절의
# 매니페스트도 그대로 읽힌다.
#
# narrate 가 s3 앞에 있는 게 2-pass의 핵심이다 — 합성된 내레이션 길이가
# 각 씬의 클립 길이를 정한다.
STAGE_ORDER = ["s1", "s2", "narrate", "s3", "s4", "s5", "s6"]

STAGE_LABELS = {
    "s1": "기획 (주제 → 아웃라인)",
    "s2": "대본 (아웃라인 → 씬)",
    "narrate": "내레이션 (TTS)",
    "s3": "클립 생성",
    "s4": "조립 (정규화 → concat)",
    "s5": "마감 (자막 굽기 / Vrew 스테이징)",
    "s6": "회수 (Vrew 결과 → final)",
}


class StageFailed(RuntimeError):
    pass


class Run:
    def __init__(self, manifest: RunManifest, root: Path) -> None:
        self.manifest = manifest
        self.paths = RunPaths(root)

    # ----------------------------------------------------------------- 생성/로드

    @classmethod
    def create(
        cls,
        *,
        topic: str,
        profile: Profile,
        video_backend: str,
        llm_backend: str,
        skip_vrew: bool,
        run_id: str | None = None,
    ) -> Run:
        rid = run_id or config.new_run_id(topic)
        manifest = RunManifest(
            run_id=rid,
            topic=topic,
            profile_name=profile.name,
            profile=profile,
            video_backend=video_backend,
            llm_backend=llm_backend,
            skip_vrew=skip_vrew,
        )
        run = cls(manifest, config.run_dir(rid))
        run.paths.ensure()
        run.save()
        return run

    @classmethod
    def load(cls, run_id: str) -> Run:
        root = config.run_dir(run_id)
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"매니페스트를 찾을 수 없습니다: {manifest_path}")
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return cls(RunManifest.model_validate(data), root)

    def save(self) -> None:
        self.manifest.updated_at = utcnow()
        payload = self.manifest.model_dump(mode="json")
        target = self.paths.manifest
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(target)

    # ----------------------------------------------------------------- 편의 접근자

    @property
    def id(self) -> str:
        return self.manifest.run_id

    @property
    def profile(self) -> Profile:
        return self.manifest.profile

    def is_done(self, name: str) -> bool:
        """다시 돌 필요가 없는 상태인가. 건너뛴 단계도 여기 포함된다."""
        return self.manifest.stage(name).status in (
            StageStatus.COMPLETED,
            StageStatus.SKIPPED,
        )

    def mark_skipped(self, name: str, reason: str) -> None:
        """단계를 건너뛴 것으로 표시한다 (실패가 아니라 해당 없음)."""
        st = self.manifest.stage(name)
        st.status = StageStatus.SKIPPED
        st.started_at = st.started_at or utcnow()
        st.finished_at = utcnow()
        st.outputs["reason"] = reason
        self.save()

    @contextmanager
    def stage(self, name: str) -> Iterator[StageState]:
        st = self.manifest.stage(name)
        st.status = StageStatus.RUNNING
        st.started_at = utcnow()
        st.error = None
        self.save()
        try:
            yield st
        except Exception as exc:  # noqa: BLE001 - 상태를 남기고 그대로 올린다
            st.status = StageStatus.FAILED
            st.finished_at = utcnow()
            st.error = f"{type(exc).__name__}: {exc}"
            self.save()
            raise
        else:
            st.status = StageStatus.COMPLETED
            st.finished_at = utcnow()
            self.save()

    # ----------------------------------------------------------------- 대본 I/O

    def write_script(self, script: Script) -> None:
        self.paths.script.write_text(
            json.dumps(script.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def read_script(self) -> Script:
        path = self.paths.script
        if not path.is_file():
            raise StageFailed(
                f"대본이 없습니다: {path}\n먼저 `avs script {self.id}` 를 실행하세요."
            )
        return Script.model_validate(json.loads(path.read_text(encoding="utf-8")))


def stages_from(start: str | None) -> list[str]:
    """`--from s3` → ['s3','s4','s5','s6']"""
    if not start:
        return list(STAGE_ORDER)
    if start not in STAGE_ORDER:
        raise ValueError(f"알 수 없는 스테이지: {start} (가능: {', '.join(STAGE_ORDER)})")
    return STAGE_ORDER[STAGE_ORDER.index(start) :]


def list_runs() -> list[str]:
    root = config.runs_dir()
    if not root.is_dir():
        return []
    dirs = [d for d in root.iterdir() if (d / "manifest.json").is_file()]
    return [d.name for d in sorted(dirs, key=lambda d: d.stat().st_mtime, reverse=True)]
