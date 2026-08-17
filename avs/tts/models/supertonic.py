"""Supertonic 3 어댑터 — ONNX Runtime, GPU 불필요.

99M 파라미터 ONNX 모델이라 CPU에서도 빠르다. 내장 보이스 10종(M1~M5, F1~F5)을
쓰고, 클로닝은 별도 상용 서비스(Voice Builder)로 만든 스타일 JSON이 있어야 한다.
즉 **이 어댑터는 프리셋 전용**이고, `reference_audio` 는 스타일 JSON 경로로 해석한다.

`lang="na"` 가 멀티링구얼 모드다. 한국어 문장에 영어가 섞여 있어도 언어를 따로
지정하지 않고 넘길 수 있어서 코드스위칭에 그대로 맞는다.

라이선스: 코드 MIT / 가중치 OpenRAIL-M (사용 목적 제한 조항 있음).
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_VOICE = "F1"
# 'na' = 멀티링구얼. 한/영이 섞인 문장을 언어 지정 없이 처리한다.
DEFAULT_LANG = "na"
SAMPLE_RATE = 44100


def probe() -> dict:
    import supertonic as st

    return {
        "model": "supertonic",
        "version": getattr(st, "__version__", "?"),
        "device": "cpu (onnxruntime)",
        "languages": list(st.AVAILABLE_LANGUAGES),
        "voices": ["M1", "M2", "M3", "M4", "M5", "F1", "F2", "F3", "F4", "F5"],
        "supports_cloning": False,
        "license": "code MIT / weights OpenRAIL-M",
    }


def load(config: dict):
    import supertonic as st

    tts = st.TTS(
        model=config.get("checkpoint") or st.DEFAULT_MODEL,
        auto_download=True,
    )

    reference = config.get("reference_audio")
    if reference:
        # Supertonic 은 오디오에서 바로 클로닝하지 않는다. Voice Builder 가
        # 만들어 준 스타일 JSON 경로만 받는다.
        style = tts.get_voice_style_from_path(reference)
    else:
        style = tts.get_voice_style(config.get("voice") or DEFAULT_VOICE)

    return {"tts": tts, "style": style}


def synthesize(engine, item: dict, config: dict) -> dict:
    tts = engine["tts"]
    style = engine["style"]

    out_path = Path(item["out_path"])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    wav, duration = tts.synthesize(
        item["text"],
        voice_style=style,
        speed=float(config.get("speed") or 1.0),
        lang=item.get("language") or config.get("language") or DEFAULT_LANG,
        silence_duration=float(config.get("silence_duration") or 0.25),
    )
    tts.save_audio(wav, str(out_path))

    # duration 은 (1,) 배열로 온다.
    seconds = float(duration[0]) if hasattr(duration, "__len__") else float(duration)
    return {
        "path": str(out_path),
        "duration": round(seconds, 3),
        "sample_rate": SAMPLE_RATE,
    }
