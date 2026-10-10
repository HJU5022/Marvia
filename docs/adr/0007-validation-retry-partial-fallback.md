# 0007. LLM 출력은 검증 규칙 V1~V15를 통과시키고, 위반이 계속되면 판정 표 등급으로 partial 폴백한다

상태: 채택

## 맥락
LLM 출력에 틀린 숫자, 오래된 위치를 "현재 위치"라 쓰는 문장, 근거 없는 낱말이 섞일 수 있다. 프롬프트 문장만으로는 역할 재설정 주입이 다 막히지 않았다. 공격 8종 x 채널 5개 x 3회에서 1/120이 남았다 ([evals/results/injection/README.md](../../evals/results/injection/README.md)).

## 결정
- `services/judge/validate.py`가 V1~V7, V9~V15를 검사하고, 라우터가 V8(등급이 판정 표 아래로 내려가지 않음, [0001](0001-verdict-by-code-table.md))을 검사한다. 규칙 목록은 [SDD 5.7절](../Marvia_SDD.md) 표에 있다.
- 위반 시 3단계: 1차는 위반 내용을 붙여 다시 묻고, 2차는 "JSON만, 규칙 준수"로 강화하고, 3차는 폴백한다. 시간 예산 `JUDGE_BUDGET_SEC`(60초)을 넘길 것 같으면 다음 시도를 시작하지 않는다.
- 폴백 응답은 `status=partial`이다. 판정 표 등급 + 고정 문구를 주고 evidence는 그대로 둔다. 회색 지대면 등급 없이 partial이다. `failed`는 통관 정보를 못 가져왔을 때만 쓴다.
- 프롬프트 방어와 별개로 코드 방어(guard, V9, V10)를 둔다.

## 대안
- 위반 시 failed 반환: 처음 구현이다. F02 문항이 V1에 3번 걸려 failed로 끝났다 ([EVAL_REPORT 4-1절](../../EVAL_REPORT.md)). partial로 바꾼 뒤 F02는 정답이다.
- 프롬프트 문장만으로 주입 막기: 위 측정에서 남아 코드 방어를 더했다.

## 결과
- 좋아진 것: 등급은 코드가 정하므로 LLM이 못 만든 것은 문장뿐이고, 그때도 사용자는 등급을 받는다. 출력 계약 준수율은 규칙 + gpt-4o-mini (b) 구성 5회에서 출력 112개 중 110개, 98.2%다 ([EVAL_REPORT 9-2절](../../EVAL_REPORT.md), `evals/results/b_20261002_1143.json`, `b_20261002_1146.json`, `b_20261002_1149.json`, `b_20261002_1153.json`, `b_20261002_1156.json`).
- 대가: 재시도가 지연과 비용을 늘린다. 관리할 검증 규칙이 15개다.

## 근거
- [SDD](../Marvia_SDD.md) 5.7절 표와 재시도 문단, 7절
- [EVAL_REPORT.md](../../EVAL_REPORT.md) 4-1절, 9-2절
- [CLAUDE.md](../../CLAUDE.md) "할 것": "LLM 출력은 검증 규칙(validate.py V1~V7·V9~V15, 라우터 V8)을 통과해야 한다"
- `backend/app/services/judge/answers.py JUDGE_BUDGET_SEC`
