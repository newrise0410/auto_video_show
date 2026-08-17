"""s1 — 주제를 구성안으로."""

from __future__ import annotations

from ..backends import get_llm_backend
from ..prompts import outline_system, outline_user
from ..state import Run


def run_stage(run: Run) -> str:
    profile = run.profile
    topic = run.manifest.topic
    llm = get_llm_backend(run.manifest.llm_backend)

    with run.stage("s1") as state:
        outline = llm.complete(
            outline_user(topic),
            system=outline_system(profile, topic),
            timeout=600,
        ).strip()
        if not outline:
            raise RuntimeError("구성안이 비어 있습니다")

        run.paths.outline.write_text(outline, encoding="utf-8")
        state.outputs["outline"] = str(run.paths.outline)
        state.outputs["chars"] = str(len(outline))

    return outline
