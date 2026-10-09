# 0015. 동명 선박은 사용자 근거 없이 LLM이 확정하지 않는다

상태: 채택

## 맥락
선명으로 배를 찾으면 같은 이름의 배가 여럿일 수 있다. 처음 계획은 "2척 이상이면 LLM이 고른다"였다. 근거 없이 LLM이 고르면 남의 배를 확정했다 ([SDD](../Marvia_SDD.md) "부록. 계획 대비 변경" 표 선박 식별 행).

## 결정
- 후보가 1척이면 코드가 확정한다.
- 후보가 여럿이고 사용자가 준 항차나 포워더 예정일이 있으면 `llm.pick_vessel`을 부른다. 출력은 `{choice, confidence: high|medium|low, reasons_per_candidate}`이고, confidence가 high이고 choice가 후보 안에 있을 때만 confirmed다.
- 사용자 근거(항차, 입항 예정일)가 없으면 LLM을 부르지 않고 확정하지 않는다. 확정하지 못하면 판정 대신 되묻는다.

## 대안
- 2척 이상이면 바로 LLM이 선택: 처음 계획이다. 평가에서 선박 오확정 2건(B01, B12)이 났다.

## 결과
- 좋아진 것: exact 28/30 -> 30/30, 선박 오확정 2건 -> 0건, LLM 호출 29 -> 25, p95 7.1초 -> 5.3초 (`evals/results/b_20261001_1953.json` -> `b_20261001_2131.json`, [EVAL_REPORT 4절](../../EVAL_REPORT.md) 표 3번).
- 대가: 두 결과 파일은 커밋 안 된 수정이 있던 작업 트리(`-dirty`)에서 돌았다. 같은 때 들어간 guard 오탐 수정(`8a0531f`)이 섞였을 수 있다 ([EVAL_REPORT 4절](../../EVAL_REPORT.md) "한 번에 하나만 바꿨나").

## 근거
- [SDD](../Marvia_SDD.md) 5.5절
- [EVAL_REPORT.md](../../EVAL_REPORT.md) 4절 표 3번, 4-1절
- [PRD](../Marvia_PRD.md) 3절 차별점(확정 못 하면 판정 대신 되묻는다)
- 커밋 `6c737eb`
