# 0012. 서비스 모델을 gpt-4o-mini에서 gemini-3.5-flash-lite로 바꿨다

상태: 채택 (gpt-4o-mini를 대체함)

## 맥락
서비스 모델은 처음 `openai/gpt-4o-mini`(OpenRouter)였다. 판정 평가셋 30건에서 후보 모델을 비교했다. 기억 뽑기와 제목은 지금도 gpt-4o-mini다 (`docs/release_manifest.json` models).

## 결정
서비스 모델(`LLM_MODEL`)은 `google/gemini-3.5-flash-lite`(OpenRouter)다. 같은 프롬프트(judge 10, judge-eval 3, follow-up 5), 30건, 1회씩 비교한 결과다.

| 지표 | gpt-4o-mini (`b_20261006_1739`) | gemini-3.5-flash-lite (`b_20261006_2306`) |
|---|---|---|
| exact | 30/30 | 30/30 |
| 통관 해설 | 0.95 (20건) | 1.0 (20건) |
| p50 / p95 | 3,989ms / 7,066ms | 2,024ms / 7,446ms |
| 요청당 비용 | $0.000696 | $0.0022 |

## 대안
- qwen/qwen3-235b-a22b-2507: 판정 30/30, 해설 0.95지만 요청당 $0.003791(약 10배), p95 30.4초, 출력 계약 준수 64.7%(34개 중 22개)라 선택하지 않았다 (`EVAL_REPORT.md` 5절).
- Vertex AI 직접 호출: 1회 실행(`b_20261007_0935.json`)은 경로가 달라 표와 섞지 않았다.

## 결과
좋아진 것: p50 지연이 절반으로 줄고 해설 점수가 같거나 높다. 대가: 요청당 비용이 약 3.2배 늘었다. 7절 게이트($0.005) 안이다. 비교는 각 1회이고 `git_commit`이 비어 있거나 `-dirty`라 흔들림 폭은 알 수 없다. flash-lite의 출력 단위 계약 준수율은 재지 않았다. 문서에 남은 결정 근거는 `.env.example`의 "평가 30/30, 숨은 생각 없이 빠름" 한 줄이다.

## 근거
- `EVAL_REPORT.md` 5절 "왜 이 모델인가"
- `docs/release_manifest.json` models, `docs/prompt_versions.md` 머리말
