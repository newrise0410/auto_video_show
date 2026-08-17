# 로컬 TTS 베이크오프 결과

같은 문장을 후보 모델마다 합성한 결과. **wav를 직접 듣고** 판정한다.
여기 있는 수치는 속도 기준(합격 조건 3번)만 답해준다.

## 합격 기준

1. 영어 토큰을 자연스러운 영어 발음으로 읽는가
2. 숫자·단위를 한국어 어법대로 읽는가 (「세 배」, 「구십이 도」, 「일 대 십오」)
3. 8초 분량 합성이 10초 이내인가
4. 라이선스가 수익화를 허용하는가

## 후보

| 모델 | 상태 | 라이선스 | 클로닝 | 디바이스 | 로딩 |
|---|---|---|---|---|---|
| chatterbox | OK | MIT (PerTh 워터마크 자동 삽입) | 가능 | cuda | 382.4초 |

## 문장별 결과

### chatterbox

| 문장 | 길이 | 합성 | RTF | 파일 |
|---|---|---|---|---|
| codeswitch | 4.52초 | 12.20초 | 2.70 | [01_codeswitch.wav](chatterbox/01_codeswitch.wav) |
| numbers | 5.56초 | 4.12초 | 0.74 | [02_numbers.wav](chatterbox/02_numbers.wav) |
| proper_noun | 4.20초 | 3.06초 | 0.73 | [03_proper_noun.wav](chatterbox/03_proper_noun.wav) |
| range | 4.08초 | 2.95초 | 0.72 | [04_range.wav](chatterbox/04_range.wav) |
| plain | 4.40초 | 3.14초 | 0.71 | [05_plain.wav](chatterbox/05_plain.wav) |

## 평가 문장

- **codeswitch** — 이 API를 쓰면 핸드드립보다 세 배 빠릅니다.
- **numbers** — 물 온도는 92도, 원두 대 물 비율은 1 대 15가 기본값입니다.
- **proper_noun** — GitHub Actions에서 CI를 돌리듯이 매일 자동으로 실행됩니다.
- **range** — 30초에서 1분 정도 식히면 90도 초반까지 떨어집니다.
- **plain** — 원두를 바꿔도 커피가 쓰다면 원인은 대개 추출에 있습니다.
