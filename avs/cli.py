"""avs — 주제 하나로 영상을 만드는 CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from . import config
from .console import console, fail, info, ok, step, warn
from .state import STAGE_LABELS, STAGE_ORDER, Run, list_runs, stages_from
from .stages import (
    s1_ideate,
    s2_script,
    s3_clips,
    s4_assemble,
    s5_finish,
    s6_ingest,
    s_narrate,
)

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="주제 → 대본 → 클립 → 조립 → 마감까지 도는 영상 자동화 파이프라인.",
)

RunIdArg = Annotated[
    str | None,
    typer.Argument(help="실행 ID. 생략하면 가장 최근 실행을 씁니다."),
]


def _load(run_id: str | None) -> Run:
    try:
        return Run.load(config.resolve_run_id(run_id))
    except FileNotFoundError as exc:
        fail(str(exc))
        raise typer.Exit(code=1) from exc


def _parse_only(value: str | None) -> list[int] | None:
    if not value:
        return None
    try:
        return [int(part) for part in value.replace(" ", "").split(",") if part]
    except ValueError as exc:
        fail(f"--only 값을 읽을 수 없습니다: {value} (예: 3,7)")
        raise typer.Exit(code=1) from exc


# --------------------------------------------------------------------- 환경 점검


@app.command()
def doctor() -> None:
    """필요한 외부 도구와 자격증명을 점검합니다."""
    table = Table(show_header=True, header_style="bold")
    table.add_column("항목")
    table.add_column("상태")
    table.add_column("비고", overflow="fold")

    for name in ("ffmpeg", "ffprobe", "claude", "codex", "hermes"):
        try:
            path = config.find_tool(name)
            table.add_row(name, "[green]OK[/]", path)
        except config.ToolNotFound as exc:
            required = name in {"ffmpeg", "ffprobe"}
            table.add_row(name, "[red]없음[/]" if required else "[yellow]없음[/]", str(exc))

    try:
        from .backends.video_hermes import probe as hermes_probe

        result = hermes_probe()
        if result.get("success") and result.get("has_credentials"):
            caps = result.get("capabilities", {})
            table.add_row(
                "Grok Imagine",
                "[green]OK[/]",
                f"비율 {', '.join(caps.get('aspect_ratios', []))} / "
                f"해상도 {', '.join(caps.get('resolutions', []))} / "
                f"길이 {caps.get('min_duration')}~{caps.get('max_duration')}초"
                # 프로바이더는 supports_audio=False 라고 보고하지만 실제
                # 클립에는 환경음이 들어 있다 (docs/spike-hermes-video-gen.md).
                + (" / 오디오 있음(환경음)" if not caps.get("supports_audio") else ""),
            )
        elif result.get("success"):
            table.add_row(
                "Grok Imagine",
                "[yellow]자격증명 없음[/]",
                "`hermes auth add xai-oauth` 로 슈퍼그록 계정을 연결하세요.",
            )
        else:
            table.add_row("Grok Imagine", "[red]실패[/]", str(result.get("error")))
    except Exception as exc:  # noqa: BLE001 - 점검 명령은 뭐가 나오든 표에 담는다
        table.add_row("Grok Imagine", "[red]실패[/]", f"{type(exc).__name__}: {exc}")

    installed = config.installed_tts_models()
    if not installed:
        table.add_row(
            "로컬 TTS", "[yellow]없음[/]", "docs/tts-setup.md 를 따라 가상환경을 만드세요."
        )
    for model in installed:
        try:
            from .backends.tts_local import probe as tts_probe

            result = tts_probe(model)
            if result.get("success"):
                table.add_row(
                    f"TTS: {model}",
                    "[green]OK[/]",
                    f"{result.get('device', '?')} / "
                    f"클로닝 {'가능' if result.get('supports_cloning') else '불가'} / "
                    f"{result.get('license', '?')}",
                )
            else:
                table.add_row(f"TTS: {model}", "[red]실패[/]", str(result.get("error"))[:200])
        except Exception as exc:  # noqa: BLE001 - 점검 명령은 뭐가 나오든 표에 담는다
            table.add_row(f"TTS: {model}", "[red]실패[/]", f"{type(exc).__name__}: {exc}"[:200])

    console.print(table)
    console.print(f"\n프로파일: {', '.join(config.available_profiles()) or '(없음)'}")
    console.print(f"작업 루트: {config.runs_dir()}")


@app.command(name="profiles")
def profiles_cmd() -> None:
    """사용 가능한 출력 프로파일을 보여줍니다."""
    names = config.available_profiles()
    if not names:
        warn("프로파일이 없습니다.")
        return

    table = Table(show_header=True, header_style="bold")
    for column in ("이름", "캔버스", "비율", "씬", "목표", "상한", "보이스", "환경음", "전환"):
        table.add_column(column)

    limits, models = set(), set()
    for name in names:
        p = config.load_profile(name)
        limits.add(p.max_scene_duration)
        if p.narration.enabled:
            models.add(p.narration.model)
        table.add_row(
            p.name,
            p.aspect_label,
            p.aspect_ratio,
            f"{p.min_scenes}~{p.max_scenes}",
            f"{p.scene_duration:g}s",
            f"{p.narration_limit}자",
            p.narration.voice or "-" if p.narration.enabled else "꺼짐",
            p.ambient.value if p.narration.enabled else "-",
            p.transition.value,
        )
    console.print(table)

    cap = "/".join(f"{v:g}" for v in sorted(limits))
    console.print(
        "\n[dim]「목표」는 씬 목표 길이, 「상한」은 씬당 대본 글자수 상한입니다.\n"
        "내레이션을 쓰면 목표는 대본 작성 기준일 뿐이고, 실제 화면 길이는 "
        f"합성된 목소리가 정합니다 (백엔드 상한 {cap}초).[/]"
    )
    if models:
        console.print(f"[dim]TTS 모델: {', '.join(sorted(models))}[/]")


@app.command(name="tts-bakeoff")
def tts_bakeoff_cmd(
    out: Annotated[Path, typer.Option(help="결과 wav와 보고서를 쓸 디렉터리")] = Path(
        "docs/tts-bakeoff"
    ),
    models: Annotated[
        str | None, typer.Option(help="쉼표로 구분한 모델 목록. 생략하면 설치된 것 전부")
    ] = None,
    reference: Annotated[
        Path | None,
        typer.Option(help="클로닝 지원 모델에 넘길 레퍼런스 오디오 (한국어 음원이어야 공정)"),
    ] = None,
    normalize: Annotated[
        bool, typer.Option(help="합성 전에 숫자·기호를 한국어 낭독형으로 바꿉니다")
    ] = False,
) -> None:
    """후보 TTS 모델로 같은 문장을 합성해 비교합니다."""
    from .tts.bakeoff import run_bakeoff

    selected = [m.strip() for m in models.split(",")] if models else None
    results = run_bakeoff(
        out,
        selected,
        reference_audio=str(reference) if reference else None,
        normalize_text=normalize,
    )
    if not results:
        raise typer.Exit(code=1)


@app.command(name="list")
def list_cmd() -> None:
    """실행 기록을 최신순으로 보여줍니다."""
    ids = list_runs()
    if not ids:
        info("실행 기록이 없습니다.")
        return
    for run_id in ids:
        run = Run.load(run_id)
        done = sum(1 for s in STAGE_ORDER if run.is_done(s))
        console.print(f"  {run_id}  [dim]{run.manifest.profile_name} · {done}/{len(STAGE_ORDER)} 단계[/]")


@app.command()
def status(run_id: RunIdArg = None) -> None:
    """실행 하나의 단계별 상태를 보여줍니다."""
    run = _load(run_id)
    m = run.manifest

    console.print(f"[bold]{m.run_id}[/]")
    console.print(f"  주제      {m.topic}")
    console.print(f"  프로파일  {m.profile_name} ({m.profile.aspect_label}, {m.profile.aspect_ratio})")
    console.print(f"  백엔드    영상={m.video_backend} LLM={m.llm_backend} vrew={'건너뜀' if m.skip_vrew else '사용'}")

    table = Table(show_header=True, header_style="bold")
    table.add_column("단계")
    table.add_column("설명")
    table.add_column("상태")
    table.add_column("결과", overflow="fold")
    for name in STAGE_ORDER:
        st = m.stages.get(name)
        state = st.status.value if st else "pending"
        colour = {"completed": "green", "failed": "red", "running": "yellow"}.get(state, "dim")
        detail = st.error if st and st.error else ", ".join(f"{k}={v}" for k, v in (st.outputs if st else {}).items())
        table.add_row(name, STAGE_LABELS[name], f"[{colour}]{state}[/]", detail or "")
    console.print(table)

    if m.scenes or m.narrations:
        scene_table = Table(show_header=True, header_style="bold")
        for column in ("씬", "내레이션", "클립", "화면 길이", "요청", "시도", "비고"):
            scene_table.add_column(column)

        keys = sorted(set(m.scenes) | set(m.narrations), key=int)
        for key in keys:
            a = m.scenes.get(key)
            n = m.narrations.get(key)
            scene_table.add_row(
                key,
                f"{n.duration:.2f}초" if n and n.duration else (n.status.value if n else "-"),
                a.status.value if a else "-",
                f"{a.duration:.2f}초" if a and a.duration else "",
                f"{a.clip_request_seconds}초" if a and a.clip_request_seconds else "",
                str(a.attempts) if a else "",
                ((a.error if a else None) or (n.error if n else None) or "")[:50],
            )
        console.print(scene_table)


# --------------------------------------------------------------------- 개별 단계


@app.command()
def outline(run_id: RunIdArg = None) -> None:
    """s1 — 주제로 구성안을 만듭니다."""
    run = _load(run_id)
    step(STAGE_LABELS["s1"])
    s1_ideate.run_stage(run)
    ok(f"구성안: {run.paths.outline}")


@app.command()
def script(
    run_id: RunIdArg = None,
    scenes: Annotated[int | None, typer.Option(help="씬 개수. 기본은 프로파일의 max_scenes.")] = None,
) -> None:
    """s2 — 구성안을 씬 대본으로 옮깁니다."""
    run = _load(run_id)
    step(STAGE_LABELS["s2"])
    result = s2_script.run_stage(run, scene_count=scenes)
    ok(f"대본 {len(result.scenes)}씬: {result.title}")


@app.command()
def narrate(
    run_id: RunIdArg = None,
    only: Annotated[str | None, typer.Option(help="특정 씬만 다시 합성 (예: 3,7)")] = None,
    force: Annotated[bool, typer.Option(help="이미 합성된 것도 다시 만듭니다")] = False,
) -> None:
    """narrate — 대본을 목소리로 만듭니다. (클립 길이가 여기서 정해집니다)"""
    run = _load(run_id)
    s_narrate.run_stage(run, only=_parse_only(only), force=force)


@app.command()
def clips(
    run_id: RunIdArg = None,
    only: Annotated[str | None, typer.Option(help="특정 씬만 다시 생성 (예: 3,7)")] = None,
    force: Annotated[bool, typer.Option(help="이미 받은 클립도 다시 생성")] = False,
    concurrency: Annotated[int, typer.Option(help="동시 생성 개수")] = 2,
    backend: Annotated[str | None, typer.Option(help="영상 백엔드 (mock/hermes)")] = None,
) -> None:
    """s3 — 씬 프롬프트로 클립을 생성합니다."""
    run = _load(run_id)
    if backend:
        run.manifest.video_backend = backend
        run.save()
    s3_clips.run_stage(run, only=_parse_only(only), force=force, concurrency=concurrency)
    ok("클립 준비 완료")


@app.command()
def assemble(
    run_id: RunIdArg = None,
    force: Annotated[bool, typer.Option(help="정규화본을 다시 만듭니다")] = False,
) -> None:
    """s4 — 정규화하고 이어붙입니다."""
    run = _load(run_id)
    s4_assemble.run_stage(run, force=force)


@app.command()
def finish(run_id: RunIdArg = None) -> None:
    """s5 — Vrew 폴더를 준비하거나(기본) 자막을 구워 완성합니다."""
    run = _load(run_id)
    s5_finish.run_stage(run)


@app.command()
def handoff(run_id: RunIdArg = None) -> None:
    """s5 별칭 — Vrew 작업 폴더를 준비합니다."""
    run = _load(run_id)
    if run.manifest.skip_vrew:
        warn("이 실행은 --skip-vrew 로 시작됐습니다. Vrew 폴더 준비로 전환합니다.")
        run.manifest.skip_vrew = False
        run.save()
    s5_finish.run_stage(run)


@app.command()
def ingest(
    run_id: RunIdArg = None,
    source: Annotated[Path | None, typer.Option(help="Vrew 내보내기 파일 경로")] = None,
) -> None:
    """s6 — Vrew에서 내보낸 결과를 최종본으로 회수합니다."""
    run = _load(run_id)
    s6_ingest.run_stage(run, source=source)


# --------------------------------------------------------------------- 전체 실행


@app.command()
def run(
    topic: Annotated[str | None, typer.Argument(help="영상 주제")] = None,
    profile: Annotated[str, typer.Option(help="출력 프로파일")] = "shorts",
    video_backend: Annotated[str, typer.Option(help="영상 백엔드 (hermes/mock)")] = "hermes",
    llm_backend: Annotated[str, typer.Option(help="LLM 백엔드 (claude/codex/mock)")] = "claude",
    skip_vrew: Annotated[bool, typer.Option(help="Vrew 없이 ffmpeg로 자막을 구워 완성")] = False,
    no_narration: Annotated[
        bool,
        typer.Option(
            "--no-narration",
            help="로컬 TTS를 끕니다. 씬 길이가 프로파일 고정값이 되고 목소리는 Vrew 몫이 됩니다.",
        ),
    ] = False,
    scenes: Annotated[int | None, typer.Option(help="씬 개수")] = None,
    concurrency: Annotated[int, typer.Option(help="클립 동시 생성 개수")] = 2,
    resume: Annotated[str | None, typer.Option(help="기존 실행 ID를 이어서 진행")] = None,
    from_stage: Annotated[
        str | None, typer.Option("--from", help=f"이 단계부터 다시 실행 ({'/'.join(STAGE_ORDER)})")
    ] = None,
    until: Annotated[
        str | None,
        typer.Option(
            "--until",
            help="이 단계까지만 실행하고 멈춥니다. 클립을 뽑기 전에 대본을 검토할 때 씁니다.",
        ),
    ] = None,
) -> None:
    """s1부터 s5까지 한 번에 돌립니다. (s6는 Vrew 작업 뒤 `avs ingest`)"""
    if resume:
        run_obj = _load(resume)
        if topic:
            run_obj.manifest.topic = topic
        run_obj.manifest.skip_vrew = skip_vrew or run_obj.manifest.skip_vrew
        run_obj.save()
    else:
        if not topic:
            fail("주제를 입력하거나 --resume 으로 기존 실행을 지정하세요.")
            raise typer.Exit(code=1)
        try:
            selected = config.load_profile(profile)
        except FileNotFoundError as exc:
            fail(str(exc))
            raise typer.Exit(code=1) from exc
        if no_narration:
            selected = selected.model_copy(
                update={"narration": selected.narration.model_copy(update={"backend": "none"})}
            )
        run_obj = Run.create(
            topic=topic,
            profile=selected,
            video_backend=video_backend,
            llm_backend=llm_backend,
            skip_vrew=skip_vrew,
        )
        info(f"실행 ID: {run_obj.id}")

    try:
        todo = stages_from(from_stage)
    except ValueError as exc:
        fail(str(exc))
        raise typer.Exit(code=1) from exc

    if until:
        if until not in STAGE_ORDER:
            fail(f"알 수 없는 단계: {until} (가능: {', '.join(STAGE_ORDER)})")
            raise typer.Exit(code=1)
        todo = [s for s in todo if STAGE_ORDER.index(s) <= STAGE_ORDER.index(until)]

    # --from 으로 지목한 단계부터는 완료 표시를 무시하고 다시 돈다.
    rerun = set(todo) if from_stage else set()

    for name in todo:
        if name == "s6":
            # Vrew 작업은 사람이 하는 단계라 자동 실행에 포함하지 않는다.
            continue
        if run_obj.is_done(name) and name not in rerun:
            info(f"{name} 완료됨 — 건너뜀")
            continue

        if name == "s1":
            step(STAGE_LABELS["s1"])
            s1_ideate.run_stage(run_obj)
        elif name == "s2":
            step(STAGE_LABELS["s2"])
            result = s2_script.run_stage(run_obj, scene_count=scenes)
            ok(f"{len(result.scenes)}씬 — {result.title}")
        elif name == "narrate":
            s_narrate.run_stage(run_obj)
        elif name == "s3":
            # `--from s3` 는 단계를 다시 밟겠다는 뜻이지 이미 받아둔 클립을
            # 버리겠다는 뜻이 아니다. 재생성은 `avs clips --force` 로 명시한다.
            s3_clips.run_stage(run_obj, concurrency=concurrency)
        elif name == "s4":
            s4_assemble.run_stage(run_obj, force=name in rerun)
        elif name == "s5":
            s5_finish.run_stage(run_obj)

    if until and until != STAGE_ORDER[-1] and until != "s5":
        ok(f"{until} 까지 실행하고 멈췄습니다. 이어서: `avs run --resume {run_obj.id}`")
    elif run_obj.manifest.skip_vrew:
        ok(f"완료 — {run_obj.paths.final}")
    else:
        ok(f"자동 구간 완료. Vrew 작업 후 `avs ingest {run_obj.id}` 를 실행하세요.")


if __name__ == "__main__":
    app()
