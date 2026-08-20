# auto_video_show

주제 한 줄로 쇼츠/롱폼 영상을 뽑는 로컬 파이프라인.

기획·대본은 `claude -p`, 내레이션은 **로컬 TTS**(Supertonic), 영상은 Hermes를 경유한
**Grok Imagine**(슈퍼그록 OAuth), 편집·조립은 로컬 **ffmpeg**. Vrew는 원하면 쓰는
다듬기 도구다.

```
주제 ─ s1 기획 ─ s2 대본 ─ narrate ─ s3 클립 ─ s4 정규화·믹스·조립 ─ s5 마감 ─ s6 회수 ─ mp4
       claude -p          로컬 TTS   Grok      ffmpeg               ffmpeg / Vrew
```

**`narrate` 가 클립 생성보다 먼저 도는 게 핵심이다.** 합성된 목소리의 실측 길이가
각 씬의 화면 길이를 정한다(2-pass). 그래서 말이 잘리거나 어색한 공백이 생기지 않는다.

## 설치

```powershell
uv sync
uv venv --python 3.12 .venv-tts\supertonic
uv pip install --python .venv-tts\supertonic supertonic
uv run avs doctor    # 외부 도구 · Grok 자격증명 · TTS 점검
```

필요한 것: `ffmpeg`/`ffprobe`, `claude`(또는 `codex`), Hermes Agent + 슈퍼그록/
X Premium+ 구독, 로컬 TTS 가상환경. Vrew는 선택(없으면 `--skip-vrew`).

TTS는 별도 venv를 쓴다 — PyTorch/ONNX 스택이 프로젝트의 Python 3.14와 맞지 않기
때문이다. 자세한 절차는 [docs/tts-setup.md](docs/tts-setup.md).

Grok 자격증명이 없다고 나오면:

```powershell
hermes auth add xai-oauth
```

> `hermes status` 는 OAuth 저장 경로 중 하나만 보기 때문에 로그인 상태여도
> "not logged in" 으로 표시될 수 있다. `avs doctor` 를 기준으로 판단할 것.

## 쓰기

```powershell
# 전체 실행 (쇼츠, Vrew 핸드오프까지)
uv run avs run "집에서 커피 맛있게 내리는 법"

# 클립을 뽑기 전에 대본만 보고 판단하고 싶을 때
uv run avs run "주제" --until s2
uv run avs run --resume <run_id>            # 마음에 들면 이어서

# Vrew 없이 ffmpeg가 자막까지 구워 완성 (내레이션 포함 완제품)
uv run avs run "주제" --skip-vrew

# 가로 롱폼
uv run avs run "주제" --profile longform

# 내레이션을 끄고 예전처럼 씬 고정 길이로 (목소리는 Vrew 몫)
uv run avs run "주제" --no-narration

# 외부 호출 없이 파이프라인만 점검 (TTS는 로컬이라 그대로 돈다)
uv run avs run "테스트" --video-backend mock --llm-backend mock --skip-vrew
```

Vrew 경로에서는 `runs/<id>/vrew_in/` 에 조립본·SRT·내레이션·작업 안내가
준비된다. Vrew에서 마무리한 mp4를 `runs/<id>/vrew_out/` 에 넣고:

```powershell
uv run avs ingest <run_id>
```

### 단계별 실행 / 복구

```powershell
uv run avs status <run_id>                  # 단계·씬별 상태
uv run avs narrate <run_id> --only 3        # 특정 씬 목소리만 다시
uv run avs clips <run_id> --only 3,7        # 마음에 안 드는 씬만 다시 생성
uv run avs run --resume <run_id> --from s4  # 조립부터 다시
uv run avs list                             # 실행 기록
uv run avs lint <run_id>                    # 대본 문체 측정
```

`lint` 는 파이프라인을 돌리지 않는다. `--file` 로 아무 대본 JSON이나 잴 수 있고,
`--before` 로 전후를 나란히 놓는다. 수치는 **한 방향 증거**다 — 나쁘면 확실히
나쁘지만, 좋다고 좋은 대본이라는 뜻은 아니다. 최종 판정은 소리 내어 읽는 것이다.

모든 단계는 멱등이다. 이미 받아둔 클립은 절대 다시 만들지 않는다. 클립 하나에
1~4분씩 걸리기 때문에 이게 이 도구의 핵심 성질이다.

내레이션은 **대본 문장의 해시**로 재사용 여부를 정한다. 대본을 고치면 문장이 바뀐
씬만 다시 합성되고 나머지는 그대로 남는다.

## 프로파일

출력 규격은 코드가 아니라 `avs/profiles/*.yaml` 이 정한다.

```powershell
uv run avs profiles
```

| | shorts | longform |
|---|---|---|
| 캔버스 | 1080x1920 (9:16) | 1920x1080 (16:9) |
| 씬 목표 길이 | 8초 | 10초 |
| 씬 수 | 5~8 | 18~30 |
| 내레이션 상한 | 64자 | 80자 |
| 보이스 | F1 | M2 |
| 전환 | 없음 | xfade 0.5초 |

`scene_duration` 은 내레이션을 쓸 때 **고정값이 아니라 대본 작성용 목표치**다.
실제 화면 길이는 합성된 목소리 길이가 정하고, `max_scene_duration`(Grok 상한 15초)에서
잘린다.

`narration_max_chars` 를 직접 지정하지 않으면 `scene_duration × chars_per_second`
로 계산한다. 씬 길이를 바꾸면 대본 분량이 따라 움직인다.

주요 오디오 설정:

| 키 | 뜻 |
|---|---|
| `narration.backend` | `local` 또는 `none`(내레이션 끔) |
| `narration.voice` | Supertonic 내장 보이스 `M1`~`M5` / `F1`~`F5` |
| `narration.head_pad` / `tail_pad` | 말 앞뒤 여유. 화면 길이에 그대로 더해진다 |
| `ambient` | `duck`(말할 때만 환경음 낮춤) / `attenuate` / `mute` |
| `source_audio` | Grok 환경음을 `keep` 할지 `mute` 할지 |
| `loudness_target` | 최종 LUFS. 유튜브 기준 −14 |

프로젝트 루트에 `profiles/` 폴더를 만들면 내장 프로파일보다 우선한다.

## 구조

```
avs/
  cli.py          명령 정의
  state.py        실행 매니페스트, 단계 상태, 재개 로직
  models.py       Profile / Scene / Script / RunManifest
  prompts.py      s1·s2 프롬프트
  quality.py      대본 문체 계측 (avs lint)
  profiles/       출력 규격 YAML
  data/           낱말 사전 (탐지용)
  stages/         s1·s2·narrate·s3~s6
  backends/       claude / codex / mock, hermes(Grok) / mock, 로컬 TTS
  tts/            브리지 러너 · 모델 어댑터 · 텍스트 정규화 · 베이크오프
  media/          probe · normalize · mix · concat · subtitles · timeline
runs/<run_id>/    실행 산출물 (git 제외)
.venv-tts/        TTS 모델별 가상환경 (git 제외)
docs/             조사 기록
```

백엔드는 전부 Protocol 뒤에 있다. mock 백엔드로 계정·네트워크 없이 파이프라인
전체를 관통시킬 수 있고, 이게 개발 반복 속도를 결정한다.

TTS와 Grok은 둘 다 **별도 파이썬 프로세스를 통한 브리지**로 부른다. 각자 우리와
맞지 않는 런타임(Hermes venv, torch/ONNX 스택)에 살기 때문이다.

## 알아둘 것

- Grok Imagine 클립은 **720p 상한**이다. 1080 캔버스로는 lanczos 업스케일한다.
- 클립에는 **환경음이 들어 있다.** 무음이 아니다. 내레이션을 켜면 말할 때만
  이 소리를 눌러준다(`ambient: duck`).
- xAI는 **초당 요청 수 제한**이 있다(현재 2 RPS). 제출 간격을 자동으로 벌리지만
  `--concurrency` 를 크게 올리면 429가 늘어난다. 기본값 2를 권한다.
- TTS에 넣기 전에 **숫자를 한국어 낭독형으로 바꾼다**(「1 대 15가」→「일 대 십오가」).
  안 그러면 모델이 무너진다. 실측 근거는 아래 스파이크 문서에 있다.
- 2-pass를 쓰면 **영상 길이 = 내레이션 길이 합 + 씬별 패딩**이다. 목표 길이를 채우려면
  `max_scenes` 를 늘리거나 씬당 대본을 길게 쓴다(`scene_duration` ↑ → `narration_limit` ↑).
  덤으로 클립 요청 길이가 짧아져서 **Grok 생성 비용도 같이 줄어든다** — 고정 8초로
  뽑던 것이 내레이션 3초짜리 씬에서는 4초 요청이 된다.
- **음성 클로닝은 아직 안 된다.** Supertonic은 프리셋 보이스만 제공한다.
- Supertonic에는 **프로소디 손잡이가 없다** — 속도·피치·휴지를 못 만진다. 낭독이
  어떻게 들릴지를 정하는 유일한 레버는 **텍스트 자체**다. 그래서 대본 문체를
  `avs lint` 로 잰다 ([대본 전달력](docs/spike-script-quality.md)).
- 대본이 어색하면 **s2가 아니라 s1을 의심할 것.** 구성안의 낱말이 그대로 낭독된다.
  실측에서 어색한 표현 여섯 개가 전부 구성안에서 태어났다.
- Vrew는 GUI 전용이라 자동화에 넣지 않았다. 이제 목소리까지 파이프라인이 만들므로
  Vrew는 선택 사항이다.

**다음에 뭘 할지**는 [docs/roadmap.md](docs/roadmap.md) 에 정리해 뒀다. 근거와 출처, 그리고
"확인 못 한 것" 목록까지 함께 있다.

조사 기록: [고도화 로드맵](docs/roadmap.md) · [Grok 연동](docs/spike-hermes-video-gen.md) ·
[로컬 TTS 선정](docs/spike-local-tts.md) · [TTS 환경 구축](docs/tts-setup.md) ·
[대본 전달력](docs/spike-script-quality.md) ·
[Grok 리서치 원문](docs/research/grok-2026-08-17.md)

## 테스트

```powershell
uv run pytest -q
```

ffmpeg 파라미터 계산, 타임라인·자막 타이밍, 대본 검증 같은 순수 로직을 덮는다.
외부 호출은 mock 백엔드로 대체한다.
