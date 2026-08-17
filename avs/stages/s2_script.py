"""s2 — 구성안을 씬 단위 대본으로.

씬 하나의 길이가 고정이므로 내레이션 길이도 상한이 있다. 모델이 이 상한을
자주 넘기기 때문에, 검증에서 걸러 문제 목록을 붙여 다시 요청한다.
"""

from __future__ import annotations

from ..backends import get_llm_backend
from ..models import Profile, Scene, Script
from ..prompts import script_retry_user, script_system, script_user
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

    if problems:
        return None, problems

    hashtags = [str(h).strip() for h in (data.get("hashtags") or []) if str(h).strip()]
    script = Script(
        title=title,
        description=str(data.get("description") or "").strip(),
        hashtags=hashtags,
        scenes=scenes,
    )
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
        script: Script | None = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            raw = llm.complete(message, system=system, timeout=900)
            try:
                data = extract_json_object(raw)
            except ValueError as exc:
                problems = [str(exc)]
            else:
                script, problems = validate(data, profile, count)

            if script is not None:
                state.outputs["attempts"] = str(attempt)
                break

            if attempt == MAX_ATTEMPTS:
                raise RuntimeError(
                    f"{MAX_ATTEMPTS}번 시도했지만 대본이 규칙을 만족하지 못했습니다:\n"
                    + "\n".join(f"- {p}" for p in problems)
                )
            message = script_retry_user(problems)

        assert script is not None
        run.write_script(script)
        state.outputs["script"] = str(run.paths.script)
        state.outputs["scenes"] = str(len(script.scenes))
        state.outputs["title"] = script.title

        for scene in script.scenes:
            run.manifest.scene_artifact(scene.index)

    return script
