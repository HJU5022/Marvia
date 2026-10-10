# 0001. 등급은 코드 판정 표가 정하고 LLM은 회색 지대에서 올리기만 한다

상태: 채택

## 맥락
처음엔 2층 판정([PRD 6.2](../Marvia_PRD.md))의 등급(fine/watch/act)을 LLM이 골랐다. 평가셋 30건에서 exact 27/30, verdict_accuracy 0.857, act_recall 0.909였다 (`evals/results/b_20260929_2251.json`).

## 결정
- 등급은 `services/judge/verdict.py`가 판정 표로 먼저 정한다. 재료는 `skills/cargo-verdict/rules.md`의 `margin_act_days`, `act_signals`, `gray_signals`다.
- act를 가르는 신호(anchor_wait, customs_hold)가 unknown인 회색 지대에서만 LLM이 표 등급보다 올릴 수 있다.
- LLM은 등급을 표보다 낮추지 못한다. 라우터의 검증 규칙 V8이 막는다.

## 대안
- LLM이 등급까지 고르기: 처음 구현이다. 위 측정에서 exact 27/30.

## 결과
- 좋아진 것: exact 27/30 -> 29/30, act_recall 0.909 -> 1.0 (`b_20260929_2251` -> `b_20260930_0021`). LLM 없이 규칙만 쓰는 (a) 구성도 verdict_accuracy 1.0, act_recall 1.0이다 (`evals/results/a_20261001_1631.json`).
- 대가: 등급 정확도로는 LLM 실력을 거의 재지 못한다 ([EVAL_REPORT 3-1절](../../EVAL_REPORT.md)). 이 변경 직후 F02 문항이 failed로 끝나는 회귀가 있었고, partial 폴백으로 고쳤다 ([0007](0007-validation-retry-partial-fallback.md)).

## 근거
- [EVAL_REPORT.md](../../EVAL_REPORT.md) 4절 표 1번, 4-1절 F02, 3-1절
- [SDD](../Marvia_SDD.md) 4.1절, 5.7절 V8
- [CLAUDE.md](../../CLAUDE.md) "할 것": "등급(verdict)은 코드가 판정 표로 정한다"
- 커밋 `3b0dea5`
