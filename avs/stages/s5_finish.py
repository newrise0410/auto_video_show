"""s5 — 마감. Vrew로 넘기거나, ffmpeg로 자막을 구워 바로 완성한다.

Vrew는 CLI도 API도 없는 GUI 전용 앱이라 파이프라인 안에 넣을 수 없다.
그래서 여기서 자동 구간을 끝내고, Vrew가 필요로 하는 것들을 한 폴더에
모아준 뒤 사람에게 넘긴다. `--skip-vrew` 를 쓰면 Vrew를 건너뛰고 ffmpeg가
자막을 구워 완성본을 만든다.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ..console import info, ok, step, warn
from ..media.probe import SILENCE_THRESHOLD_DB, mean_volume
from ..media.subtitles import build_ass, build_srt, burn_subtitles
from ..media.timeline import narration_spans, total_duration
from ..state import Run
from .common import final_slug, scene_durations, write_metadata

VREW_README = """# Vrew 작업 안내 — {run_id}

이 폴더의 파일들로 Vrew에서 자막과 내레이션을 붙이고 내보내면 됩니다.

## 파일

- `roughcut.mp4` — 조립이 끝난 무자막 영상 ({width}x{height}, {duration:.1f}초)
- `script.srt` — 씬 타이밍에 맞춘 자막
- `narration.txt` — 씬별 내레이션 원문 (Vrew AI 목소리에 붙여넣기용)

{audio_note}

## 순서

1. Vrew에서 `roughcut.mp4` 를 불러옵니다.
2. 내레이션 — 위 안내를 보고 필요할 때만 손댑니다.
   - 이미 들어 있으면 건너뜁니다.
   - Vrew AI 목소리로 갈아끼우려면 `narration.txt` 의 문장을 씬 순서대로 붙여넣습니다.
3. 자막: `script.srt` 를 가져오거나, Vrew 음성인식 결과를 `script.srt` 와 대조해 다듬습니다.
4. 내보내기 설정
   - 해상도 {width}x{height}
   - 프레임레이트 {fps}fps
   - 파일명 `{slug}.mp4`
5. 내보낸 파일을 아래 폴더에 넣습니다.

   {vrew_out}

6. 마지막으로 회수 명령을 실행합니다.

   avs ingest {run_id}

## 대본

{scene_table}
"""


_AUDIO_NOTE_NARRATED = """> `roughcut.mp4` 에는 **이미 내레이션이 들어 있습니다** (평균 {level:.1f}dB,
> 환경음 처리 `{ambient}`). Vrew에서는 자막만 다듬으면 됩니다.
> 목소리를 갈아끼우려면 프로파일의 `narration` 블록을 고치고 `avs narrate --force`
> 부터 다시 돌리세요. `narration.txt` 는 대조용으로 함께 넣어뒀습니다."""

_AUDIO_NOTE_AUDIBLE = """> `roughcut.mp4` 에는 Grok이 장면에 맞춰 생성한 환경음이 들어 있습니다
> (평균 {level:.1f}dB). 내레이션과 겹쳐 지저분하면 Vrew에서 원본 소리를
> 줄이거나, 프로파일에 `source_audio: mute` 를 넣어 처음부터 무음으로 뽑으세요."""

_AUDIO_NOTE_SILENT = """> `roughcut.mp4` 는 무음입니다. 목소리는 Vrew에서 입히세요."""


def _audio_note(video: Path, profile) -> str:
    level = mean_volume(video)
    if level is None or level <= SILENCE_THRESHOLD_DB:
        return _AUDIO_NOTE_SILENT
    if profile.narration.enabled:
        return _AUDIO_NOTE_NARRATED.format(level=level, ambient=profile.ambient.value)
    return _AUDIO_NOTE_AUDIBLE.format(level=level)


def _narration_text(scenes, durations) -> str:
    lines = []
    cursor = 0.0
    for scene, duration in zip(scenes, durations, strict=False):
        lines.append(f"[씬 {scene.index:02d}] {cursor:.1f}s ~ {cursor + duration:.1f}s")
        lines.append(scene.narration)
        lines.append("")
        cursor += duration
    return "\n".join(lines)


def _scene_table(scenes) -> str:
    rows = ["| 씬 | 내레이션 | 화면 키워드 |", "|---|---|---|"]
    for scene in scenes:
        rows.append(f"| {scene.index} | {scene.narration} | {scene.on_screen_text} |")
    return "\n".join(rows)


def _finish_with_ffmpeg(
    run: Run, script, durations: list[float], spans: list[tuple[float, float]] | None
) -> Path:
    profile = run.profile
    step("자막을 구워 완성본 생성 (Vrew 건너뜀)")

    run.paths.ass.write_text(
        build_ass(script.scenes, durations, profile, spans), encoding="utf-8"
    )
    out = run.paths.final / f"{final_slug(run, script)}.mp4"
    burn_subtitles(
        run.paths.roughcut,
        run.paths.ass,
        out,
        profile,
        log_path=run.paths.logs / "burn.log",
    )
    write_metadata(run, script, out)

    level = mean_volume(out)
    if level is None or level <= SILENCE_THRESHOLD_DB:
        warn("이 완성본은 무음입니다. 목소리가 필요하면 내레이션을 켜거나 Vrew 경로를 쓰세요.")
    elif profile.narration.enabled:
        info(f"내레이션 + 환경음({profile.ambient.value}), 평균 {level:.1f}dB")
    else:
        info(f"오디오는 Grok이 만든 환경음입니다 (평균 {level:.1f}dB). 내레이션은 없습니다.")
    ok(f"완성: {out}")
    return out


def _stage_for_vrew(
    run: Run, script, durations: list[float], spans: list[tuple[float, float]] | None
) -> Path:
    profile = run.profile
    step("Vrew 작업 폴더 준비")

    staging = run.paths.vrew_in
    staging.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(run.paths.roughcut, staging / "roughcut.mp4")

    srt = build_srt(script.scenes, durations, profile.effective_transition, spans)
    (staging / "script.srt").write_text(srt, encoding="utf-8")
    run.paths.srt.write_text(srt, encoding="utf-8")

    (staging / "narration.txt").write_text(
        _narration_text(script.scenes, durations), encoding="utf-8"
    )

    total = total_duration(durations, profile.effective_transition)
    (staging / "README.md").write_text(
        VREW_README.format(
            run_id=run.id,
            width=profile.width,
            height=profile.height,
            fps=profile.fps,
            duration=total,
            slug=final_slug(run, script),
            vrew_out=run.paths.vrew_out,
            audio_note=_audio_note(run.paths.roughcut, profile),
            scene_table=_scene_table(script.scenes),
        ),
        encoding="utf-8",
    )

    info(f"작업 폴더: {staging}")
    info(f"작업이 끝나면 결과 mp4를 {run.paths.vrew_out} 에 넣고 `avs ingest {run.id}`")
    return staging


def subtitle_spans(run: Run, script) -> list[tuple[float, float]] | None:
    """자막 구간. 내레이션이 있으면 목소리가 나는 동안에만 띄운다.

    앞뒤 여유(pad) 구간까지 자막이 떠 있으면 화면과 어긋나 보인다.
    """
    profile = run.profile
    if not profile.narration.enabled:
        return None

    narration_durations = [
        run.manifest.narration_artifact(s.index).duration or 0.0 for s in script.scenes
    ]
    if not any(narration_durations):
        return None

    return narration_spans(
        scene_durations(run, script),
        narration_durations,
        head_pad=profile.narration.head_pad,
        transition=profile.effective_transition,
    )


def run_stage(run: Run, *, reveal_folder: bool = True) -> Path:
    script = run.read_script()
    durations = scene_durations(run, script)
    spans = subtitle_spans(run, script)

    with run.stage("s5") as state:
        if run.manifest.skip_vrew:
            out = _finish_with_ffmpeg(run, script, durations, spans)
            state.outputs["final"] = str(out)
            state.outputs["mode"] = "ffmpeg"
        else:
            staging = _stage_for_vrew(run, script, durations, spans)
            state.outputs["staging"] = str(staging)
            state.outputs["mode"] = "vrew"
            if reveal_folder:
                from .common import reveal

                reveal(staging)
            out = staging

    return out
