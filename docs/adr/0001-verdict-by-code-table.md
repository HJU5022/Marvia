# 0001. 등급은 코드 판정 표가 정하고 LLM은 회색 지대에서 올리기만 한다

상태: 채택 · 날짜: 2026-09-30 (커밋 3b0dea5)

## 맥락
처음엔 2층 판정의 등급(fine/watch/act)을 LLM이 골랐다. 평가셋 30건에서 exact 27/30이었고, 실패 유도 문항에서 등급이 어긋났다 (`EVAL_REPORT.md` 4절 1번, `evals/results/b_20260929_2251.json`).

## 결정
등급은 `services/judge/verdict.py`가 판정 표로 먼저 정한다. 재료는 `skills/cargo-verdict/rules.md`(`margin_act_days`, `act_signals`, `gray_signals`)다. act를 가르는 신호(anchor_wait, customs_hold)가 unknown인 회색 지대에서만 LLM이 표 등급 이상으로 올릴 수 있다. 낮추지는 못한다(검증 V8).

## 대안
- LLM이 등급까지 고르게 두기: 처음 구현. 위 측정에서 27/30.
- 회색 지대 없이 표만 쓰기: 근거 문서에 이 대안을 비교한 기록은 없다.

## 결과
좋아진 것: exact 27/30 -> 29/30 (`b_20260929_2251` -> `b_20260930_0021`). LLM이 없는 (a) 규칙 베이스라인도 verdict_accuracy 1.0, act 재현율 1.0이다 (`a_20261001_1631.json`).
대가: 등급 정확도가 LLM 실력을 거의 재지 못한다 (`EVAL_REPORT.md` 3-1절). 이 변경으로 F02 문항이 failed로 끝나는 회귀가 있었고, 이후 partial 폴백으로 해결했다 (ADR 0007).

## 근거
- `EVAL_REPORT.md` 4절 표 1번, 4-1절 F02, 3-1절 첫 항목
- `docs/Marvia_SDD.md` 4.1절 7번, 5.7절 V8
- `CLAUDE.md` "할 것" 3번째 항목, 작업 리스트 D7 행
