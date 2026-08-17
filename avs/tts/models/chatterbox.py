"""Chatterbox Multilingual v3 어댑터 — Resemble AI, MIT, 0.5B.

23개 언어를 지원하고 한국어(`ko`)가 포함된다. 목소리는 **레퍼런스 오디오
제로샷 클로닝**이 기본 메커니즘이라, 프리셋을 쓰려면 번들 레퍼런스 클립을
가리키면 된다. 레퍼런스를 아예 주지 않으면 모델 기본 화자로 읽는다.

주의: 생성물에 PerTh 워터마크가 자동으로 박힌다. 들리지 않고 재인코딩을
견디며, 출처 확인용이다.

`language_id` 를 하나만 받기 때문에 한 문장 안에 영어가 섞여도 `ko` 로 넘긴다.
그 상태에서 영어가 어떻게 읽히는지가 베이크오프의 핵심 관전 포인트다.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_LANGUAGE = "ko"


def _device(config: dict) -> str:
    import torch

    requested = (config.get("device") or "auto").lower()
    if requested != "auto":
        return requested
    return "cuda" if torch.cuda.is_available() else "cpu"


def probe() -> dict:
    import torch
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS  # noqa: F401 - 임포트 가능 여부 확인

    return {
        "model": "chatterbox",
        "torch": torch.__version__,
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "cuda": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "languages": [
            "ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi", "it",
            "ja", "ko", "ms", "nl", "no", "pl", "pt", "ru", "sv", "sw", "tr", "zh",
        ],
        "supports_cloning": True,
        "license": "MIT (PerTh 워터마크 자동 삽입)",
    }


def load(config: dict):
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    device = _device(config)
    model = ChatterboxMultilingualTTS.from_pretrained(device=device)
    return {"model": model, "device": device}


def synthesize(engine, item: dict, config: dict) -> dict:
    import torchaudio

    model = engine["model"]
    out_path = Path(item["out_path"])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    kwargs = {"language_id": item.get("language") or config.get("language") or DEFAULT_LANGUAGE}
    reference = config.get("reference_audio")
    if reference:
        kwargs["audio_prompt_path"] = str(reference)

    wav = model.generate(item["text"], **kwargs)

    sample_rate = int(getattr(model, "sr", 24000))
    if wav.ndim == 1:
        wav = wav.unsqueeze(0)
    torchaudio.save(str(out_path), wav.cpu(), sample_rate)

    return {
        "path": str(out_path),
        "duration": round(wav.shape[-1] / sample_rate, 3),
        "sample_rate": sample_rate,
    }
