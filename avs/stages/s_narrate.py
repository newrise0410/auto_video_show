"""narrate — 대본을 목소리로 만든다. 클립을 뽑기 전에 돈다.

이 단계가 s3(클립 생성)보다 **앞에** 있는 게 2-pass의 핵심이다. 합성된
내레이션의 실측 길이가 각 씬의 클립 길이를 정하기 때문에, 순서를 바꾸면
말이 잘리거나 어색한 공백이 생긴다.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..backends.tts_local import LocalTTSBackend, SynthItem, VoiceConfig
from ..console import info, ok, step, warn
from ..media.silence import trim_edges
from ..models import Scene, StageStatus, utcnow
from ..state import Run
from ..tts.normalize_text import normalize


def text_sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _needs_synthesis(run: Run, scene: Scene, spoken: str, *, force: bool) -> bool:
    artifact = run.manifest.narration_artifact(scene.index)
    if force:
        return True
    if artifact.status is not StageStatus.COMPLETED:
        return True
    if artifact.text_sha != text_sha(spoken):
        return True  # 대본이 바뀌었다
    if not artifact.path or not Path(artifact.path).is_file():
        return True
    if artifact.raw_duration is None:
        # 무음 다듬기가 생기기 전에 만들어진 산출물이다. 그대로 두면 자막이
        # 목소리보다 먼저 뜨므로 다시 합성한다.
        return True
    return False


def build_voice_config(run: Run) -> VoiceConfig:
    cfg = run.profile.narration
    return VoiceConfig(
        model=cfg.model,
        voice=cfg.voice,
        reference_audio=cfg.reference_audio,
        speed=cfg.speed,
        language=cfg.language,
    )


def run_stage(
    run: Run,
    *,
    only: list[int] | None = None,
    force: bool = False,
) -> None:
    profile = run.profile
    cfg = profile.narration

    if not cfg.enabled:
        run.mark_skipped("narrate", "narration.backend = none")
        info("내레이션이 꺼져 있습니다 (씬 길이는 프로파일 고정값을 씁니다)")
        return

    script = run.read_script()
    targets = [s for s in script.scenes if not only or s.index in only]
    if only:
        force = True
        missing = sorted(set(only) - {s.index for s in targets})
        if missing:
            raise RuntimeError(f"대본에 없는 씬입니다: {', '.join(str(i) for i in missing)}")

    # 합성 직전에 낭독형으로 바꾼다. 숫자에 조사가 붙으면 모델이 무너진다.
    spoken = {s.index: normalize(s.narration) for s in targets}

    pending = [s for s in targets if _needs_synthesis(run, s, spoken[s.index], force=force)]
    if skipped := len(targets) - len(pending):
        info(f"이미 합성된 내레이션 {skipped}개는 건너뜁니다")

    backend = LocalTTSBackend(build_voice_config(run))

    def synthesize() -> None:
        if not pending:
            return
        step(f"내레이션 {len(pending)}개 합성 ({backend.model}, 보이스 {cfg.voice})")
        items = [
            SynthItem(
                id=str(s.index),
                text=spoken[s.index],
                out_path=run.paths.narration / f"{s.slug}.wav",
                language=cfg.language,
            )
            for s in pending
        ]
        results = {r.get("id"): r for r in backend.synthesize_batch(items)}
        info(f"모델 로딩 {backend.last_load_seconds:.1f}초")

        for scene in pending:
            result = results.get(str(scene.index), {})
            artifact = run.manifest.narration_artifact(scene.index)
            artifact.model = backend.model
            artifact.voice = cfg.voice
            artifact.attempts += 1
            artifact.updated_at = utcnow()

            if not result.get("success"):
                artifact.status = StageStatus.FAILED
                artifact.error = result.get("error") or "결과가 비어 있습니다"
                continue

            raw_duration = float(result.get("duration") or 0.0)
            path = Path(str(result.get("path")))

            # TTS는 앞뒤에 1초가 넘는 무음을 붙여서 낸다. 그대로 두면 자막이
            # 목소리보다 먼저 뜨고, 2-pass가 그 무음까지 화면 길이로 잡는다.
            lead, duration = trim_edges(path, raw_duration)

            artifact.status = StageStatus.COMPLETED
            artifact.path = str(path)
            artifact.duration = round(duration, 3)
            artifact.raw_duration = round(raw_duration, 3)
            artifact.lead_trimmed = round(lead, 3)
            artifact.text_sha = text_sha(spoken[scene.index])
            artifact.spoken_text = spoken[scene.index]
            artifact.error = None

            saved = raw_duration - duration
            if saved > 0.05:
                ok(f"{scene.slug} — {duration:.2f}초 (무음 {saved:.2f}초 제거)")
            else:
                ok(f"{scene.slug} — {duration:.2f}초")
        run.save()

    def finish() -> None:
        failed = [
            s.index
            for s in targets
            if run.manifest.narration_artifact(s.index).status is not StageStatus.COMPLETED
        ]
        if failed:
            joined = ",".join(str(i) for i in failed)
            raise RuntimeError(
                f"씬 {joined} 내레이션 합성에 실패했습니다. "
                f"`avs narrate {run.id} --only {joined}` 로 다시 시도하세요."
            )
        _warn_on_overlong(run, script.scenes)

    # 일부 씬만 다시 만드는 경우, 손대지 않은 씬이 아직 없는 건 정상이다.
    if only:
        synthesize()
        finish()
        remaining = [
            s.index
            for s in script.scenes
            if run.manifest.narration_artifact(s.index).status is not StageStatus.COMPLETED
        ]
        if remaining:
            info(f"아직 남은 씬: {', '.join(str(i) for i in remaining)}")
        else:
            with run.stage("narrate") as state:
                state.outputs["clips"] = str(len(script.scenes))
                state.outputs["model"] = backend.model
        return

    with run.stage("narrate") as state:
        synthesize()
        finish()
        state.outputs["clips"] = str(len(script.scenes))
        state.outputs["model"] = backend.model
        state.outputs["voice"] = cfg.voice or ""
        total = sum(
            run.manifest.narration_artifact(s.index).duration or 0.0 for s in script.scenes
        )
        state.outputs["speech_seconds"] = f"{total:.1f}"
        ok(f"내레이션 총 {total:.1f}초")


def _warn_on_overlong(run: Run, scenes: list[Scene]) -> None:
    """클립 상한을 넘긴 내레이션을 알린다.

    영상은 상한까지밖에 못 만드는데 말이 그보다 길면 뒷부분이 잘린다.
    자동으로 줄이지 않고 사람이 대본을 손보게 한다 — 문장을 기계가 자르면
    뜻이 망가진다.
    """
    profile = run.profile
    budget = profile.max_scene_duration - profile.narration.pad
    overlong = [
        (s.index, run.manifest.narration_artifact(s.index).duration or 0.0)
        for s in scenes
        if (run.manifest.narration_artifact(s.index).duration or 0.0) > budget
    ]
    if not overlong:
        return
    warn(f"내레이션이 클립 상한({profile.max_scene_duration:g}초)을 넘는 씬이 있습니다:")
    for index, duration in overlong:
        warn(f"  씬 {index}: {duration:.1f}초 (여유 포함 상한 {budget:.1f}초)")
    warn(f"대본을 줄이고 `avs script {run.id}` 부터 다시 돌리세요.")
