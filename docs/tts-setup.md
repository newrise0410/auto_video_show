# 로컬 TTS 환경 구축

## 왜 가상환경을 따로 쓰나

프로젝트 venv는 **Python 3.14**인데, PyTorch CUDA 휠이 이 버전(Windows)에 정상적으로
올라오지 않는다. 후보 모델끼리도 의존성이 충돌한다(`torch==2.6.0` 고정 대 `>=2.9.0`).

그래서 TTS 모델은 **모델마다 별도 venv**에 두고, 프로젝트 쪽에서는 서브프로세스
브리지(`avs/tts/runner.py`)로 호출한다. Hermes(Grok) 연동과 같은 구조다.

```
avs (Python 3.14)
  └─ subprocess: .venv-tts/<model>/Scripts/python.exe avs/tts/runner.py
       └─ avs/tts/models/<model>.py  →  실제 모델
```

## Supertonic (현재 채택 모델)

ONNX Runtime만 쓰므로 CUDA도 torch도 필요 없다. 설치가 1분이면 끝난다.

```powershell
uv venv --python 3.12 .venv-tts\supertonic
uv pip install --python .venv-tts\supertonic supertonic
```

모델 가중치는 첫 실행 때 Hugging Face에서 자동으로 받는다(약 99M).

확인:

```powershell
uv run avs doctor
```

`TTS: supertonic  OK  cpu (onnxruntime) / 클로닝 불가 / code MIT / weights OpenRAIL-M`
이 나오면 된다.

## Chatterbox (선택 — 한국어 품질 문제로 비권장)

한국어를 제대로 못 읽는다(`docs/spike-local-tts.md` 참조). 다른 언어나 음성 클로닝
실험용으로만 둔다.

```powershell
uv venv --python 3.12 .venv-tts\chatterbox
uv pip install --python .venv-tts\chatterbox chatterbox-tts
# 위 명령은 CPU용 torch를 가져온다. CUDA 빌드로 갈아끼운다 (약 2.4GB)
uv pip install --python .venv-tts\chatterbox --reinstall `
  torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124
```

CUDA 확인:

```powershell
.\.venv-tts\chatterbox\Scripts\python.exe -c "import torch; print(torch.cuda.is_available())"
```

## 경로 덮어쓰기

| 환경변수 | 용도 |
|---|---|
| `AVS_TTS_VENV_ROOT` | `.venv-tts` 대신 쓸 디렉터리 |
| `AVS_TTS_PYTHON_<MODEL>` | 특정 모델의 파이썬 절대경로 (예: `AVS_TTS_PYTHON_SUPERTONIC`) |
| `AVS_TTS_PYTHON` | 모든 모델에 적용되는 기본 파이썬 |

## 보이스 바꾸기

Supertonic은 내장 보이스 10종을 제공한다: `M1`~`M5`, `F1`~`F5`.
프로파일에서 고른다.

```yaml
narration:
  voice: F1
```

**오디오 클로닝은 지원하지 않는다.** Supertonic의 커스텀 보이스는 상용
Voice Builder가 만들어 준 스타일 JSON이 있어야 하고, 그 파일 경로를
`reference_audio` 에 넣으면 어댑터가 알아서 쓴다.

## 모델 추가하기

1. `.venv-tts/<name>/` 에 venv를 만들고 패키지를 설치한다
2. `avs/tts/models/<name>.py` 에 `probe()` / `load(config)` / `synthesize(engine, item, config)`
   세 함수를 구현한다 (`supertonic.py` 를 참고)
3. `avs/tts/models/__init__.py` 의 `ADAPTERS` 에 이름을 추가한다
4. `uv run avs tts-bakeoff --models <name>` 으로 비교한다

어댑터 모듈은 **TTS venv 안에서** 임포트되므로 `avs` 패키지를 참조하면 안 된다.
