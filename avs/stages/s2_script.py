"""s2 — 구성안을 씬 단위 대본으로.

검증은 두 종류다.

**하드 검사**(길이·씬 개수·`video_prompt`)는 대본을 못 쓰게 만드는 문제라
`script=None` 으로 반려한다. 내레이션 길이에는 상한과 하한이 둘 다 있다 —
상한만 걸어두면 모델이 예산의 절반만 쓰고, 2-pass에서는 그게 곧 영상 길이가
반토막 나는 결과가 된다.

**문체 검사**(`avs/quality.py`)는 고치면 좋은 문제지 못 쓸 이유가 아니다.
대본과 지적을 함께 돌려주고, 마지막 시도에서는 경고만 남기고 받아들인다.
문체 때문에 36씬짜리 실행이 죽으면 안 된다.
"""

from __future__ import annotations

import json

from ..backends import get_llm_backend
from ..console import warn
from ..quality import STYLE_MIN_SCENES, style_problems
from ..models import Profile, Scene, Script
from ..prompts import narration_floor, script_retry_user, script_system, script_user
from ..state import Run
from ..textutil import extract_json_object

MAX_ATTEMPTS = 3
_ON_SCREEN_LIMIT = 12


def validate(data: dict, profile: Profile, scene_count: int) -> tuple[Script | None, list[str]]:
    """대본 JSON을 검사한다. 고칠 수 있는 건 고치고, 아니면 문제를 모아 돌려준다."""
    problems: list[str] = []

    title = str(data.get("title") or "").strip()
    if not title:
        problems.append("`title` 이 비어 있습니다.")

    raw_scenes = data.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        return None, problems + ["`scenes` 배열이 없습니다."]

    if len(raw_scenes) != scene_count:
        problems.append(f"씬이 {len(raw_scenes)}개입니다. 정확히 {scene_count}개여야 합니다.")

    limit = profile.narration_limit
    scenes: list[Scene] = []
    for position, raw in enumerate(raw_scenes, start=1):
        if not isinstance(raw, dict):
            problems.append(f"{position}번째 씬이 객체가 아닙니다.")
            continue

        index = raw.get("index")
        if index != position:
            # 순서만 맞으면 되는 문제라 조용히 바로잡는다.
            index = position

        narration = str(raw.get("narration") or "").strip()
        if not narration:
            problems.append(f"씬 {position}: `narration` 이 비어 있습니다.")
        elif len(narration) > limit:
            problems.append(
                f"씬 {position}: 내레이션이 {len(narration)}자입니다. "
                f"{limit}자 이하로 줄이세요 → \"{narration}\""
            )

        video_prompt = str(raw.get("video_prompt") or "").strip()
        if len(video_prompt) < 20:
            problems.append(f"씬 {position}: `video_prompt` 가 너무 짧거나 비었습니다.")

        # 화면 키워드는 길면 잘라 쓴다. 재요청할 만한 문제가 아니다.
        on_screen = str(raw.get("on_screen_text") or "").strip()[:_ON_SCREEN_LIMIT]

        scenes.append(
            Scene(
                index=index,
                narration=narration,
                video_prompt=video_prompt,
                on_screen_text=on_screen,
            )
        )

    # 하한은 씬별이 아니라 평균에 건다. 짧고 강한 한 줄은 정당한 연출이고,
    # 실제로 관측된 실패는 개별 씬이 아니라 대본 전체가 눌리는 형태였다.
    if scenes and not problems:
        floor = narration_floor(limit)
        average = sum(len(s.narration) for s in scenes) / len(scenes)
        if average < floor:
            problems.append(
                f"내레이션이 평균 {average:.0f}자입니다. 상한 {limit}자의 절반도 "
                f"쓰지 않으면 영상이 그만큼 짧아지고 구성안 내용이 사라집니다. "
                f"평균 {floor}자 이상이 되도록 각 씬을 더 충실하게 쓰세요."
            )

    if problems:
        return None, problems

    hashtags = [str(h).strip() for h in (data.get("hashtags") or []) if str(h).strip()]
    script = Script(
        title=title,
        description=str(data.get("description") or "").strip(),
        hashtags=hashtags,
        scenes=scenes,
    )

    # 여기서부터는 문체 지적이다. script 를 함께 돌려주는 것이 계약의 핵심 —
    # 호출부는 `script is None` 으로 '못 씀'을, `problems` 로 '고치면 좋음'을
    # 구분한다. 씬이 적으면 비율이 통계가 아니라 잡음이라 재지 않는다.
    if len(scenes) >= STYLE_MIN_SCENES:
        return script, style_problems([s.narration for s in scenes])
    return script, []


def run_stage(run: Run, *, scene_count: int | None = None) -> Script:
    profile = run.profile
    topic = run.manifest.topic
    outline = run.paths.outline.read_text(encoding="utf-8")
    count = scene_count or profile.max_scenes
    llm = get_llm_backend(run.manifest.llm_backend)

    system = script_system(profile, topic, count)

    with run.stage("s2") as state:
        message = script_user(topic, outline, count)
        problems: list[str] = []
        previous: str | None = None

        # 하드 검사를 통과한 마지막 대본과 그때 남아 있던 문체 지적을 함께 들고
        # 간다. 재시도 중 JSON 파싱이 깨져도 앞서 받아둔 멀쩡한 대본을 잃지
        # 않고, 파싱 오류를 문체 경고로 잘못 보고하지도 않는다.
        best: Script | None = None
        best_problems: list[str] = []

        for attempt in range(1, MAX_ATTEMPTS + 1):
            raw = llm.complete(message, system=system, timeout=900)
            script: Script | None = None
            try:
                data = extract_json_object(raw)
            except ValueError as exc:
                problems, previous = [str(exc)], None
            else:
                # 파싱된 쪽을 다시 직렬화한다. 코드펜스와 군말이 공짜로 벗겨진다.
                previous = json.dumps(data, ensure_ascii=False)
                script, problems = validate(data, profile, count)

            if script is not None:
                best, best_problems = script, problems
                if not problems:
                    state.outputs["attempts"] = str(attempt)
                    break

            if attempt < MAX_ATTEMPTS:
                message = script_retry_user(topic, outline, count, previous, problems)
                continue

            if best is None:
                raise RuntimeError(
                    f"{MAX_ATTEMPTS}번 시도했지만 대본이 규칙을 만족하지 못했습니다:\n"
                    + "\n".join(f"- {p}" for p in problems)
                )

            # 하드 검사는 통과했고 문체 지적만 남았다. 세 번 시도했으면
            # 받아들이고 무엇이 남았는지만 기록한다 — 문체 때문에 36씬짜리
            # 실행이 죽으면 안 된다.
            state.outputs["attempts"] = str(attempt)
            state.outputs["style_warnings"] = " / ".join(best_problems)
            warn("문체 지적이 남았지만 대본을 그대로 씁니다:")
            for p in best_problems:
                warn(f"  {p}")

        script = best
        assert script is not None
        run.write_script(script)
        state.outputs["script"] = str(run.paths.script)
        state.outputs["scenes"] = str(len(script.scenes))
        state.outputs["title"] = script.title

        for scene in script.scenes:
            run.manifest.scene_artifact(scene.index)

    return script
