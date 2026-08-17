"""후보 TTS 모델 비교 하네스.

한국어 TTS 품질은 벤치마크 수치로 예측이 안 된다. 같은 문장을 후보마다
합성해서 직접 듣고 고르는 게 유일한 방법이라, 그 과정을 명령 하나로 만든다.
모델을 갈아치울 때도 그대로 재사용한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .. import config
from ..backends.tts_local import LocalTTSBackend, SynthItem, VoiceConfig
from ..console import fail, info, ok, step
from .normalize_text import normalize

# 한·영 코드스위칭 + 숫자·단위. 실제 대본에서 자주 나오는 형태만 골랐다.
SAMPLES: list[tuple[str, str]] = [
    ("codeswitch", "이 API를 쓰면 핸드드립보다 세 배 빠릅니다."),
    ("numbers", "물 온도는 92도, 원두 대 물 비율은 1 대 15가 기본값입니다."),
    ("proper_noun", "GitHub Actions에서 CI를 돌리듯이 매일 자동으로 실행됩니다."),
    ("range", "30초에서 1분 정도 식히면 90도 초반까지 떨어집니다."),
    ("plain", "원두를 바꿔도 커피가 쓰다면 원인은 대개 추출에 있습니다."),
]


@dataclass
class ModelResult:
    model: str
    ok: bool
    load_seconds: float = 0.0
    error: str = ""
    clips: list[dict] = None  # type: ignore[assignment]
    probe: dict = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.clips = self.clips or []
        self.probe = self.probe or {}


def run_model(
    model: str,
    out_dir: Path,
    *,
    voice: str | None = None,
    reference_audio: str | None = None,
    normalize_text: bool = False,
) -> ModelResult:
    from ..backends.tts_local import probe as tts_probe

    target = out_dir / model
    target.mkdir(parents=True, exist_ok=True)

    try:
        info_payload = tts_probe(model)
    except Exception as exc:  # noqa: BLE001 - 후보 하나가 죽어도 나머지는 계속
        return ModelResult(model=model, ok=False, error=f"probe 실패: {exc}")

    backend = LocalTTSBackend(
        VoiceConfig(model=model, voice=voice, reference_audio=reference_audio)
    )
    prepare = normalize if normalize_text else (lambda s: s)
    items = [
        SynthItem(id=name, text=prepare(text), out_path=target / f"{i:02d}_{name}.wav")
        for i, (name, text) in enumerate(SAMPLES, start=1)
    ]

    try:
        results = backend.synthesize_batch(items)
    except Exception as exc:  # noqa: BLE001
        return ModelResult(model=model, ok=False, error=str(exc), probe=info_payload)

    by_id = {r.get("id"): r for r in results}
    clips = []
    for (name, text), item in zip(SAMPLES, items, strict=False):
        r = by_id.get(name, {})
        clips.append(
            {
                "name": name,
                "text": text,
                "path": r.get("path", ""),
                "duration": r.get("duration", 0.0),
                "synth_seconds": r.get("synth_seconds", 0.0),
                "success": bool(r.get("success")),
                "error": r.get("error", ""),
            }
        )

    return ModelResult(
        model=model,
        ok=True,
        load_seconds=backend.last_load_seconds,
        clips=clips,
        probe=info_payload,
    )


def realtime_factor(clip: dict) -> float:
    """합성 시간 / 오디오 길이. 1보다 작으면 실시간보다 빠르다."""
    duration = clip.get("duration") or 0.0
    return (clip.get("synth_seconds") or 0.0) / duration if duration else 0.0


def merge_previous(results: list[ModelResult], out_dir: Path) -> list[ModelResult]:
    """이번에 안 돌린 모델의 지난 결과를 살려둔다.

    후보마다 설치가 끝나는 시점이 달라서 `--models` 로 하나씩 돌리게 되는데,
    그때마다 보고서에서 다른 후보가 사라지면 비교가 안 된다.
    """
    previous_path = out_dir / "results.json"
    if not previous_path.is_file():
        return results

    fresh = {r.model for r in results}
    try:
        stored = json.loads(previous_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return results

    merged = list(results)
    for entry in stored:
        if entry.get("model") in fresh:
            continue
        merged.append(
            ModelResult(
                model=entry.get("model", "?"),
                ok=bool(entry.get("ok")),
                load_seconds=float(entry.get("load_seconds") or 0.0),
                error=entry.get("error", ""),
                clips=entry.get("clips") or [],
                probe=entry.get("probe") or {},
            )
        )
    return sorted(merged, key=lambda r: r.model)


def write_report(results: list[ModelResult], out_dir: Path) -> Path:
    lines = [
        "# 로컬 TTS 베이크오프 결과",
        "",
        "같은 문장을 후보 모델마다 합성한 결과. **wav를 직접 듣고** 판정한다.",
        "여기 있는 수치는 속도 기준(합격 조건 3번)만 답해준다.",
        "",
        "## 합격 기준",
        "",
        "1. 영어 토큰을 자연스러운 영어 발음으로 읽는가",
        "2. 숫자·단위를 한국어 어법대로 읽는가 (「세 배」, 「구십이 도」, 「일 대 십오」)",
        "3. 8초 분량 합성이 10초 이내인가",
        "4. 라이선스가 수익화를 허용하는가",
        "",
        "## 후보",
        "",
        "| 모델 | 상태 | 라이선스 | 클로닝 | 디바이스 | 로딩 |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        if not r.ok:
            lines.append(f"| {r.model} | 실패 | | | | |")
            continue
        p = r.probe
        lines.append(
            f"| {r.model} | OK | {p.get('license', '?')} | "
            f"{'가능' if p.get('supports_cloning') else '불가'} | "
            f"{p.get('device', '?')} | {r.load_seconds:.1f}초 |"
        )

    lines += [
        "",
        "> `load` 는 모델을 메모리에 올리는 시간이다. 배치로 합성하므로 실행당 한 번만 든다.",
        "> `RTF`(realtime factor)는 합성시간/오디오길이 — 1보다 작으면 실시간보다 빠르다.",
        "",
        "## 문장별 결과",
        "",
    ]
    for r in results:
        lines += [f"### {r.model}", ""]
        if not r.ok:
            lines += [f"```\n{r.error}\n```", ""]
            continue
        lines += ["| 문장 | 길이 | 합성 | RTF | 파일 |", "|---|---|---|---|---|"]
        for c in r.clips:
            if not c["success"]:
                lines.append(f"| {c['name']} | | | | 실패: {c['error'][:60]} |")
                continue
            rel = Path(c["path"]).name
            lines.append(
                f"| {c['name']} | {c['duration']:.2f}초 | {c['synth_seconds']:.2f}초 | "
                f"{realtime_factor(c):.2f} | [{rel}]({r.model}/{rel}) |"
            )
        lines.append("")

    lines += ["## 평가 문장", ""]
    for name, text in SAMPLES:
        lines.append(f"- **{name}** — {text}")
    lines.append("")

    report = out_dir / "RESULTS.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    (out_dir / "results.json").write_text(
        json.dumps(
            [{"model": r.model, "ok": r.ok, "error": r.error, "probe": r.probe, "clips": r.clips} for r in results],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return report


def run_bakeoff(
    out_dir: Path,
    models: list[str] | None = None,
    *,
    reference_audio: str | None = None,
    normalize_text: bool = False,
) -> list[ModelResult]:
    candidates = models or config.installed_tts_models()
    if not candidates:
        fail("설치된 TTS 가상환경이 없습니다. docs/tts-setup.md 를 보세요.")
        return []

    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for model in candidates:
        step(f"{model} 합성 중 ({len(SAMPLES)}문장)")
        result = run_model(
            model,
            out_dir,
            reference_audio=reference_audio,
            normalize_text=normalize_text,
        )
        if result.ok:
            good = sum(1 for c in result.clips if c["success"])
            ok(f"{model} — {good}/{len(result.clips)} 문장 성공, 로딩 {result.load_seconds:.1f}초")
        else:
            fail(f"{model} — {result.error[:200]}")
        results.append(result)

    report = write_report(merge_previous(results, out_dir), out_dir)
    info(f"보고서: {report}")
    return results
