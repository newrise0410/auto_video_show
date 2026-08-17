"""s3 — 씬 프롬프트로 클립을 생성한다.

여기가 파이프라인에서 가장 느리고 가장 잘 깨지는 구간이다(클립 1개당 1~4분).
그래서 씬 단위로 상태를 남기고, 이미 받아둔 클립은 절대 다시 만들지 않는다.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..backends import BackendError, VideoGenRequest, get_video_backend
from ..console import fail, info, ok, step
from ..media.probe import ProbeError, probe
from ..media.timeline import scene_length_for_narration
from ..models import Scene, StageStatus
from ..state import Run

MAX_ATTEMPTS = 3
RETRY_BACKOFF = 20.0

# xAI는 모델별로 초당 요청 수를 제한한다(grok-imagine-video 는 현재 2 RPS).
# 동시에 여러 개를 밀어 넣으면 첫 제출부터 429가 난다. 생성 자체는 몇 분씩
# 걸리므로, 제출 시각만 살짝 벌리면 처리량 손해 없이 한도를 피할 수 있다.
SUBMIT_INTERVAL = 0.75


class SubmitGate:
    """호출 시작 시각 사이에 최소 간격을 강제한다."""

    def __init__(self, min_interval: float) -> None:
        self._lock = threading.Lock()
        self._interval = min_interval
        self._next_slot = 0.0

    def wait(self) -> None:
        with self._lock:
            target = max(time.monotonic(), self._next_slot)
            self._next_slot = target + self._interval
        delay = target - time.monotonic()
        if delay > 0:
            time.sleep(delay)


def _needs_generation(run: Run, scene: Scene, *, force: bool) -> bool:
    artifact = run.manifest.scene_artifact(scene.index)
    if force:
        return True
    if artifact.status is not StageStatus.COMPLETED:
        return True
    if not artifact.clip_path:
        return True
    return not Path(artifact.clip_path).is_file()


def plan_scene_length(run: Run, scene: Scene) -> tuple[int, float]:
    """이 씬의 (요청할 클립 초, 타임라인 목표 길이).

    내레이션이 있으면 **합성된 목소리 길이가 화면 길이를 정한다**(2-pass).
    없으면 프로파일의 고정 길이를 쓴다.
    """
    profile = run.profile
    narration = run.manifest.narration_artifact(scene.index)

    if profile.narration.enabled and narration.duration:
        return scene_length_for_narration(
            narration.duration,
            head_pad=profile.narration.head_pad,
            tail_pad=profile.narration.tail_pad,
            max_seconds=profile.max_scene_duration,
        )

    seconds = profile.scene_duration
    return max(1, round(seconds)), float(seconds)


def _generate_one(
    run: Run, scene: Scene, backend, lock: threading.Lock, gate: SubmitGate
) -> None:
    profile = run.profile
    out_path = run.paths.clips / f"{scene.slug}.mp4"
    requested, target = plan_scene_length(run, scene)

    with lock:
        artifact = run.manifest.scene_artifact(scene.index)
        artifact.clip_request_seconds = requested
        artifact.target_seconds = target

    request = VideoGenRequest(
        prompt=scene.video_prompt,
        out_path=out_path,
        duration=float(requested),
        aspect_ratio=profile.aspect_ratio,
        resolution=profile.source_resolution,
    )

    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            gate.wait()
            backend.generate(request)
        except BackendError as exc:
            last_error = str(exc)
            if not exc.retryable or attempt == MAX_ATTEMPTS:
                break
            info(f"{scene.slug}: 재시도 {attempt}/{MAX_ATTEMPTS - 1} — {exc}")
            time.sleep(RETRY_BACKOFF * attempt)
            continue

        try:
            media = probe(out_path)
        except ProbeError as exc:
            last_error = f"생성된 클립을 읽을 수 없습니다: {exc}"
            break

        with lock:
            artifact = run.manifest.scene_artifact(scene.index)
            artifact.status = StageStatus.COMPLETED
            artifact.clip_path = str(out_path)
            artifact.duration = media.duration
            artifact.attempts += attempt
            artifact.backend = backend.name
            artifact.error = None
            run.save()
        ok(f"{scene.slug} — {media.size_label}, {media.duration:.1f}초 (요청 {requested}초)")
        return

    with lock:
        artifact = run.manifest.scene_artifact(scene.index)
        artifact.status = StageStatus.FAILED
        artifact.attempts += MAX_ATTEMPTS
        artifact.backend = backend.name
        artifact.error = last_error
        run.save()
    fail(f"{scene.slug} 실패 — {last_error}")


def _generate_all(run: Run, scenes, backend, concurrency: int) -> None:
    step(f"클립 {len(scenes)}개 생성 (백엔드: {backend.name}, 동시 {concurrency})")
    lock = threading.Lock()
    gate = SubmitGate(SUBMIT_INTERVAL)
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        list(pool.map(lambda s: _generate_one(run, s, backend, lock, gate), scenes))


def _incomplete(run: Run, scenes) -> list[int]:
    return [
        s.index
        for s in scenes
        if run.manifest.scene_artifact(s.index).status is not StageStatus.COMPLETED
    ]


def run_stage(
    run: Run,
    *,
    only: list[int] | None = None,
    force: bool = False,
    concurrency: int = 2,
) -> None:
    script = run.read_script()
    backend = get_video_backend(run.manifest.video_backend)

    targets = [s for s in script.scenes if not only or s.index in only]
    if only:
        force = True  # 특정 씬을 콕 집었다는 건 다시 만들라는 뜻이다
        missing = sorted(set(only) - {s.index for s in targets})
        if missing:
            raise RuntimeError(f"대본에 없는 씬입니다: {', '.join(str(i) for i in missing)}")

    pending = [s for s in targets if _needs_generation(run, s, force=force)]
    if skipped := len(targets) - len(pending):
        info(f"이미 받아둔 클립 {skipped}개는 건너뜁니다")

    # 일부 씬만 다시 만드는 경우, 스테이지 자체를 실패로 몰면 안 된다.
    # 손대지 않은 다른 씬이 아직 없는 건 정상적인 중간 상태다.
    if only:
        if pending:
            _generate_all(run, pending, backend, concurrency)
        if failed := _incomplete(run, targets):
            joined = ",".join(str(i) for i in failed)
            raise RuntimeError(f"씬 {joined} 클립 생성에 실패했습니다.")

        remaining = _incomplete(run, script.scenes)
        if remaining:
            info(f"아직 남은 씬: {', '.join(str(i) for i in remaining)}")
        else:
            with run.stage("s3") as state:
                state.outputs["clips"] = str(len(script.scenes))
                state.outputs["backend"] = backend.name
        return

    with run.stage("s3") as state:
        if pending:
            _generate_all(run, pending, backend, concurrency)

        if failed := _incomplete(run, script.scenes):
            joined = ",".join(str(i) for i in failed)
            raise RuntimeError(
                f"씬 {joined} 클립 생성에 실패했습니다. "
                f"원인을 확인한 뒤 `avs clips {run.id} --only {joined}` 로 다시 시도하세요."
            )

        state.outputs["clips"] = str(len(script.scenes))
        state.outputs["backend"] = backend.name
