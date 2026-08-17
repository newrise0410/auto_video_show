# 스파이크 — Hermes 경유 Grok Imagine 호출 규약

영상 생성 어댑터(`avs/backends/video_hermes.py`)를 쓰기 전에 호출 방식과 응답
형태를 확정하기 위한 조사 기록. **2026-08-17** 기준.

## 결론 요약

| 항목 | 실측값 |
|---|---|
| 호출 경로 | Hermes 가상환경 파이썬으로 xAI video_gen 프로바이더 함수 직접 호출 |
| 인증 | Hermes가 이미 보유한 xAI OAuth 토큰(JWT) 재사용. 추가 설정 불필요 |
| 반환값 | 로컬 파일이 아니라 **HTTPS URL** (files-cdn 저장본 또는 만료되는 임시 링크) |
| 비율 | 9:16 / 16:9 등 7종을 **네이티브 지원** — 크롭으로 화면을 버릴 필요 없음 |
| 해상도 | 480p / 720p (720p가 상한) |
| 길이 | 1~15초 가변 (정수 초) |
| 오디오 | **있음.** 장면에 맞는 환경음이 들어온다 |
| 소요 시간 | 클립 1개당 대략 1~4분 |

## 왜 에이전트 루프를 안 쓰는가

`hermes -z "..." -t video_gen` 로 에이전트를 태우면 모델이 도구를 부를지 말지,
결과 경로를 어떻게 문장으로 풀어 쓸지가 매번 달라진다. 토큰도 쓴다.

프로바이더는 그냥 평범한 파이썬 함수라서 직접 부르면 된다. 다만 Hermes는
자체 가상환경(Python 3.11)에 설치되어 있고 `agent.*` / `tools.*` 를 임포트하므로,
우리 인터프리터에서 임포트할 수는 없다. 그래서 브리지 스크립트
(`avs/backends/hermes_runner.py`)를 **Hermes 쪽 파이썬**으로 실행하고,
stdin/stdout으로 JSON을 주고받는다.

```
avs (Python 3.14)
  └─ subprocess: <hermes>/venv/Scripts/python.exe hermes_runner.py
       └─ plugins/video_gen/xai/__init__.py :: run_xai_video_generation(...)
            └─ POST https://api.x.ai/v1/videos/generations  → 폴링 → URL
```

브리지 출력에는 임포트 로그가 섞일 수 있어서 `<<<AVS_RESULT>>>` 센티널 뒤에
결과 JSON을 붙인다.

## 인증

Hermes의 자격증명 해석 순서는 `runtime provider (xai-oauth 풀) → auth.json
싱글턴 OAuth → XAI_API_KEY` 다.

주의: `hermes status` 는 이 중 싱글턴 경로만 본다. 이 PC에서는
`hermes status` 가 "xAI OAuth ✗ not logged in" 이라고 표시하지만,
`resolve_xai_http_credentials()` 는 풀에서 786자짜리 JWT를 정상적으로
돌려준다. **`hermes status` 만 보고 미로그인이라고 판단하면 안 된다.**
`avs doctor` 는 프로바이더의 `has_xai_video_credentials()` 를 직접 호출한다.

## 응답 형태

성공:
```json
{"success": true, "video": "https://...mp4", "model": "grok-imagine-video",
 "duration": 8, "aspect_ratio": "9:16", "provider": "xai", "request_id": "..."}
```

실패:
```json
{"success": false, "video": null, "error": "...", "error_type": "auth_required"}
```

재시도해도 소용없는 `error_type` 은 `_FATAL_ERROR_TYPES` 로 분류해 즉시 포기한다
(`auth_required`, `missing_prompt`, `invalid_*`, `unsupported_model` 등).

## 실측 클립 (2026-08-17)

프롬프트: *"Vertical 9:16 close-up of a dark coffee cup ... no text or lettering
anywhere in frame"*, `duration=8, aspect_ratio=9:16, resolution=720p`

```
width=720  height=1280      ← 요청한 세로 비율 그대로
r_frame_rate=24/1           ← 24fps (프로파일 30fps로 정규화 필요)
duration=8.041667           ← 요청보다 살짝 김. 정규화에서 -t 로 자른다
codec_name=h264 (video)
codec_name=aac  (audio)     ← mean_volume -28.5dB, max -15.8dB = 실제 환경음
codec_name=mjpeg (video)    ← 썸네일 스트림. -map 0:v:0 로 반드시 첫 스트림만 집을 것
size=1425440
```

### 문서와 어긋난 점 두 가지

1. **`capabilities()` 는 `supports_audio: false` 라고 보고하지만 실제로는
   오디오가 들어온다.** 이 플래그를 믿고 파이프라인을 무음 전제로 짜면 안 된다.
   `Profile.source_audio` 로 `keep`/`mute` 를 고르게 해뒀다.
2. **mp4 안에 비디오 스트림이 둘(h264 + mjpeg 썸네일)이다.** ffmpeg에서
   `-map 0:v` 로 잡으면 썸네일까지 딸려온다. `-map 0:v:0` 을 써야 한다.

## 대안 경로 (지금은 안 씀)

- `hermes serve` HTTP API — 구조화 응답이지만 서버를 띄워 관리해야 한다.
- `hermes mcp` — MCP 클라이언트 의존성이 추가된다.
- xAI Imagine API 직접 호출 — API 키 발급 + 초당 $0.08 종량 과금.
  구독으로 커버되는 지금 경로가 더 낫다.

세 경로 모두 같은 `VideoGenBackend` Protocol 뒤에 들어가므로, 필요해지면
클래스 하나만 추가하면 된다.
