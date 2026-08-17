"""s4 — 클립을 캔버스 규격으로 정규화하고, 내레이션을 얹고, 하나로 잇는다."""

from __future__ import annotations

from pathlib import Path

from ..console import info, ok, step, warn
from ..media.concat import concat_clips
from ..media.mix import apply_loudness, mix_narration
from ..media.normalize import normalize_clip
from ..media.probe import probe
from ..media.timeline import total_duration
from ..state import Run


def _normalized_path(run: Run, index: int) -> Path:
    return run.paths.build / f"norm_{index:02d}.mp4"


def _mixed_path(run: Run, index: int) -> Path:
    return run.paths.build / f"mix_{index:02d}.mp4"


def run_stage(run: Run, *, force: bool = False) -> Path:
    script = run.read_script()
    profile = run.profile
    use_narration = profile.narration.enabled

    with run.stage("s4") as state:
        step(f"클립 {len(script.scenes)}개 정규화 → {profile.aspect_label} @ {profile.fps}fps")

        segments: list[Path] = []
        durations: list[float] = []

        for scene in script.scenes:
            artifact = run.manifest.scene_artifact(scene.index)
            if not artifact.clip_path:
                raise RuntimeError(f"{scene.slug} 클립이 없습니다. 먼저 `avs clips` 를 실행하세요.")

            source = Path(artifact.clip_path)
            target = _normalized_path(run, scene.index)
            # 2-pass에서는 씬마다 길이가 다르다. 목표 길이가 없으면(내레이션을
            # 끈 경우) 프로파일 고정값으로 돌아간다.
            want = artifact.target_seconds or profile.scene_duration

            if target.is_file() and not force and artifact.normalized_path == str(target):
                media = probe(target)
            else:
                media = normalize_clip(
                    source,
                    target,
                    profile,
                    duration=want,
                    log_path=run.paths.logs / f"normalize_{scene.index:02d}.log",
                )

            if media.duration < want - 0.15:
                warn(
                    f"{scene.slug}: 클립이 목표보다 짧습니다 "
                    f"({media.duration:.2f}초 < {want:.2f}초). 내레이션 끝이 잘릴 수 있습니다."
                )

            artifact.normalized_path = str(target)
            artifact.duration = media.duration
            segment = target

            if use_narration:
                narration = run.manifest.narration_artifact(scene.index)
                if not narration.path or not Path(narration.path).is_file():
                    raise RuntimeError(
                        f"{scene.slug} 내레이션이 없습니다. 먼저 `avs narrate` 를 실행하세요."
                    )
                segment = mix_narration(
                    target,
                    Path(narration.path),
                    _mixed_path(run, scene.index),
                    profile,
                    head_pad=profile.narration.head_pad,
                    duration=media.duration,
                    log_path=run.paths.logs / f"mix_{scene.index:02d}.log",
                )

            info(f"{scene.slug}: {media.size_label}, {media.duration:.2f}초")
            segments.append(segment)
            durations.append(media.duration)

        run.save()

        if use_narration:
            info(f"환경음 처리: {profile.ambient.value}")

        step("이어붙이는 중")
        concat_clips(
            segments,
            durations,
            run.paths.roughcut,
            profile,
            work_dir=run.paths.build,
            log_path=run.paths.logs / "concat.log",
        )

        if profile.loudness_target is not None:
            step(f"라우드니스 {profile.loudness_target:g} LUFS 로 정규화")
            leveled = run.paths.build / "roughcut_leveled.mp4"
            apply_loudness(
                run.paths.roughcut,
                leveled,
                profile,
                log_path=run.paths.logs / "loudnorm.log",
            )
            leveled.replace(run.paths.roughcut)

        result = probe(run.paths.roughcut)
        expected = total_duration(durations, profile.effective_transition)
        ok(f"조립본 {result.size_label}, {result.duration:.1f}초 (예상 {expected:.1f}초)")

        state.outputs["roughcut"] = str(run.paths.roughcut)
        state.outputs["duration"] = f"{result.duration:.2f}"
        state.outputs["narration"] = "on" if use_narration else "off"

    return run.paths.roughcut
