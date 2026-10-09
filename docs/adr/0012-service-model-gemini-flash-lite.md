# 0012. 서비스 모델을 gpt-4o-mini에서 gemini-3.5-flash-lite로 바꿨다

상태: 채택

## 맥락
서비스 모델은 처음 `openai/gpt-4o-mini`(OpenRouter)였다. 판정 평가셋 30건에서 후보 모델을 비교했다.

## 결정
- 서비스 모델(`LLM_MODEL`)은 `google/gemini-3.5-flash-lite`(OpenRouter)다.
- 기억 뽑기와 대화 제목은 `MEMORY_MODEL`로 따로 지정하고, 운영 값은 `openai/gpt-4o-mini`다 ([release_manifest.json](../release_manifest.json) `models.memory_and_title`).

결정 뒤 같은 프롬프트(judge 10, judge-eval 3, follow-up 5)로 30건을 1회씩 돌려 확인했다 ([EVAL_REPORT 5절](../../EVAL_REPORT.md) 표). 판정 exact는 둘 다 30/30이고, flash-lite는 p50 3,989ms -> 2,024ms, 요청당 비용 $0.000696 -> $0.0022다. p95는 7,066ms -> 7,446ms로 비슷하다. 통관 해설은 0.95 -> 1.0이지만 채점 모델이 달라 직접 비교한 값은 아니다(gpt-4o-mini 실행은 `google/gemini-2.5-flash`, flash-lite 실행은 `anthropic/claude-haiku-4.5`, 각 파일 `rows[].customs_grade.model`). 출처는 `evals/results/b_20261006_1739.json`, `b_20261006_2306.json`이다.

## 대안
- qwen/qwen3-235b-a22b-2507: 판정 30/30, 해설 20/21이었지만 요청당 $0.003791, p95 30.4초, 출력 계약 준수 64.7%(34개 중 22개)라 고르지 않았다 ([EVAL_REPORT 5절, 9-2절](../../EVAL_REPORT.md), `evals/results/c_20261002_1241.json`).
- Vertex AI 직접 호출: 1회 실행(`b_20261007_0935.json`)은 호출 경로가 달라 위 비교와 섞지 않았다.

## 결과
- 좋아진 것: p50 지연이 절반으로 줄었다. 판정 exact는 같다.
- 대가: 요청당 비용이 약 3.2배 늘었다. [EVAL_REPORT 7절](../../EVAL_REPORT.md) 비용 게이트($0.005) 안이다.
- 위 비교는 각 1회이고 `git_commit`이 비어 있거나 `-dirty`라 두 모델 차이의 흔들림 폭은 알 수 없다. flash-lite만 OpenRouter 경로로 6회 다시 돌렸다 (judge·follow-up 프롬프트 3판 x 2회, `evals/results/b_20261007_2102.json` ~ `b_20261007_2116.json`). 6회 모두 exact 30/30, p50 1,875~2,078ms, p95 3,579~6,288ms, 요청당 $0.002406~$0.002808다.
- flash-lite의 출력 단위 계약 준수율은 재지 않았다.
- 문서에 남은 결정 근거는 `.env.example`의 "평가 30/30, 숨은 생각 없이 빠름" 한 줄이다. 위 비교는 결정 뒤에 잰 확인 측정이다.

## 근거
- [EVAL_REPORT.md](../../EVAL_REPORT.md) 5절 "왜 이 모델인가", 7절
- [release_manifest.json](../release_manifest.json) `models`, [prompt_versions.md](../prompt_versions.md) 머리말
