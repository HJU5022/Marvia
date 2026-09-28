# Spec: 2층 판정 출력 파인튜닝 (judge 증류)

상태: 제안. 코드 없음. 정운님(C 묶음) 합의와 SDD 반영 전에는 구현하지 않는다 (CLAUDE.md "SDD 5절과 작업 리스트에 없는 기능은 Spec 먼저").
범위: PRD 4절 P0·P1에 없는 기능이다. 이번 동결(10/8) 안에 할지, 발표의 확장 가능성으로만 둘지는 합의로 정한다.

## Why

- 페르소나: 부산항 해상 수입 소량 화주 (PRD 2절). 조회 한 번에 답을 빨리, 싸게 받아야 한다.
- 상황: 매 요청마다 부르는 LLM은 2층 판정 `llm.judge()` 하나다 (SDD 4.1 7단계). 선박 선택과 후속 질문은 필요할 때만 부른다.
- 문제:
  1. 판정 입력의 대부분이 프롬프트와 skills 문서 전문이다. 09-27 스모크에서 입력 3,870토큰, 출력 131토큰 (docs/prompt_versions.md judge v3). 요청마다 같은 문서를 다시 보낸다.
  2. 출력 형식·내용 규칙(V1~V7)을 어기면 최대 3단계 재시도한다 (SDD 5.7). 재시도는 지연과 비용을 늘린다.
  3. SDD 7절 목표는 p95 15초 이내, 요청당 비용 상한은 평가 뒤 확정. 판정 호출이 두 지표에 모두 걸린다.
- 측정 지표: 판정 호출 입력 토큰, 요청당 비용, 판정 호출 지연, V1~V7 위반율과 재시도 비율. 판정 정확도(verdict_accuracy, act_recall)는 떨어지면 안 된다.

## Goal

- 해결 목표: 강한 모델(MODEL_B)이 낸 판정 중 검증을 통과한 것만 모아 작은 모델(gpt-4o-mini)을 API 파인튜닝한다. 파인튜닝 모델은 skills 전문 없이 짧은 시스템 프롬프트만 받고도 같은 형식의 판정을 낸다.
- 성공 기준 (전부 평가셋 30건 실행 결과로 판단, 실행 전 숫자는 적지 않는다):
  - 판정 정확도와 act_recall이 기준 모델(현재 MODEL_A) 이상. act_recall 1.0 게이트는 그대로 (PRD 8절)
  - V1~V7 위반율이 기준 모델 이하
  - 판정 호출 입력 토큰과 요청당 비용이 기준 모델보다 낮음
  - 셋 중 하나라도 못 미치면 DISCARD. 기본 모델은 바꾸지 않는다 (D10과 같은 KEEP/DISCARD 방식)
- Out of Scope:
  - 판단 기준을 모델에 외우게 하는 것. 임계값과 상충 우선순위의 원본은 계속 skills/ais-reliability/rules.md다
  - 선박 선택(pick_vessel), 후속 질문(answer_follow_up) 파인튜닝. 호출 빈도가 낮고 MRN 식별로 선박 선택은 더 줄었다
  - 평가 judge(marvia-judge-eval) 파인튜닝. 생성 모델과 독립이어야 한다 (PRD 8절)
  - 오픈소스 모델 학습·자체 서빙, GPU 서버
  - 실제 수집 데이터(워커 DB의 ShipFinder·해수부 값)와 UNI-PASS 값으로 학습하는 것

## What

**Happy Path**
1. 학습 입력 생성 (`scripts/ft_make_cases.py`): 코드가 rules.md 임계값 경계 앞뒤로 신호 7종 조합, 통관 단계, 여유 일수를 가공값으로 만든다. 입력 모양은 `llm._judge_input()`과 같다
2. 정답 생성 (`scripts/ft_label.py`): 각 입력을 MODEL_B + 현재 판정 프롬프트 + skills 전문으로 판정한다
3. 거르기: 판정 출력을 라우터와 같은 방식으로 AgentResponse로 조립한 뒤(`validate.check()`는 AgentResponse를 받는다) V1~V7을 통과하고, 신호가 전부 clear면 fine인 규칙과 맞는 답만 남긴다. 버린 건수와 이유를 기록한다
4. 학습 파일: 시스템 프롬프트는 짧은 판정 전용 문구(Langfuse 프롬프트 `marvia-judge-ft`), 사용자 메시지는 1의 입력, 답은 3을 통과한 JSON. 학습용·검증용으로 나눈다
5. 학습 (`scripts/ft_train.py`): OpenAI 파인튜닝 API로 gpt-4o-mini 학습. job id와 결과 모델 이름을 기록한다
6. 연결: `llm.py`에 모델 이름이 `ft:`로 시작하면 OpenAI를 직접 부르는 분기. 기본 모델은 그대로다
7. 비교: 평가 실행기(D8)에 구성 하나를 더해 30건을 돌리고 성공 기준으로 KEEP/DISCARD

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | rules.md 임계값이나 skills 문서가 바뀜 | 파인튜닝 모델은 예전 기준을 기억한다. 학습 데이터 생성 때 rules.md 해시를 기록하고, 해시가 다르면 llm.py가 파인튜닝 모델을 쓰지 않고 기본 모델로 돌아간다 |
| EC-02 | 파인튜닝 모델 출력이 V1~V7 위반 | 지금과 같은 3단계 재시도. 재시도 두 번째부터는 기본 모델 + skills 전문으로 부른다 |
| EC-03 | OpenAI 호출 실패, 키 없음 | LLMError. 라우터는 지금처럼 partial. 기본 모델로 1회 라우팅할지는 합의로 정한다 |
| EC-04 | MODEL_B 정답이 틀림 (잘못된 판정이 규칙은 통과) | V1~V7은 형식·근거만 본다. 경계 조합 표본 일부를 사람이 검토하고, 평가셋 정확도가 떨어지면 DISCARD |
| EC-05 | 학습 입력이 평가셋 30건과 겹침 | 평가셋 입력·fixture는 학습 생성기에서 읽지 않는다. 생성 뒤 평가셋과 같은 신호 조합·값이 있으면 뺀다 |
| EC-06 | 입력 속 문자열(AIS 목적지 등)에 지시문 | 판정 입력에는 원래 AIS 목적지 원문이 가지 않는다 (#52 테스트). 학습 입력도 같은 `_judge_input()` 모양이라 같다 |

## How

파일 (모두 새로 만들거나 C 묶음 파일을 고친다. 담당 합의 필요)

```
scripts/ft_make_cases.py   가공 입력 생성. rules.md를 읽고 경계 앞뒤 값을 만든다
scripts/ft_label.py        MODEL_B로 정답 생성, validate.check()로 거르기
scripts/ft_train.py        OpenAI 파일 업로드, 파인튜닝 job 생성·상태 확인
evals/ft/                  생성 데이터 (가공값만). 학습 파일, 버린 건수, rules.md 해시
backend/app/services/llm.py  ft: 모델 분기, rules 해시 확인
```

학습 파일 한 줄 (OpenAI chat 파인튜닝 형식)

```
{"messages": [
  {"role": "system", "content": "<marvia-judge-ft 프롬프트>"},
  {"role": "user", "content": "<_judge_input() JSON>"},
  {"role": "assistant", "content": "<V1~V7 통과한 JudgeOutput JSON>"}
]}
```

환경변수 (계약 C8 변경이라 PR 리뷰 필요)

```
OPENAI_API_KEY    파인튜닝 학습과 ft: 모델 호출. OpenRouter로는 파인튜닝 모델을 부를 수 없다
MODEL_FT          파인튜닝 모델 이름 (ft:gpt-4o-mini:...). 비어 있으면 쓰지 않는다
```

비용과 시간 (추정. 실행 전이라 숫자는 가격표 확인 뒤 적는다)

- 정답 생성: MODEL_B 호출을 학습 건수만큼 추가
- 학습: 학습 토큰 × epoch. OpenAI 파인튜닝 가격표로 확인
- 호출: 파인튜닝 모델 단가는 기본 gpt-4o-mini보다 비싸다. 입력 토큰 감소분이 이걸 넘어야 이득이다
- 작업량: 스크립트 3개와 llm.py 분기, 평가 1회. D8 실행기가 먼저 있어야 비교할 수 있다

데이터 규칙

- 가공값만 쓴다. 실제 선박·B/L 값은 학습 파일에 넣지 않는다 (CLAUDE.md, SDD 7절, ShipFinder·UNI-PASS 이용 조건)
- 평가셋은 사람이 쓰고 확정한다는 규칙은 그대로다. 이 Spec의 생성 데이터는 학습용이고 평가에 쓰지 않는다

## AC (Given-When-Then)

**AC-01 · 검증 통과한 답만 학습에 들어간다**
- GIVEN: MODEL_B 정답 중 V1~V7 위반이 섞여 있다
- WHEN: ft_label.py를 돌린다
- THEN: 학습 파일에는 위반 0건, 버린 건수와 규칙별 이유가 기록된다

**AC-02 · 평가셋과 겹치지 않는다**
- GIVEN: 평가셋 30건
- WHEN: 학습 입력을 만든다
- THEN: 평가셋과 같은 입력은 0건

**AC-03 · 기준이 바뀌면 파인튜닝 모델을 쓰지 않는다**
- GIVEN: 학습 때와 rules.md 해시가 다르다
- WHEN: judge()가 호출된다
- THEN: 기본 모델 + skills 전문으로 판정하고 로그에 이유를 남긴다

**AC-04 · 비교 결과로 KEEP/DISCARD**
- GIVEN: D8 실행기로 기준 모델과 파인튜닝 모델을 각각 30건 실행
- WHEN: 성공 기준 3개를 대조한다
- THEN: 하나라도 못 미치면 DISCARD, 기본 모델 유지. 결과는 EVAL_REPORT.md 개선 실험에 실제 숫자로 적는다

**AC-05 · 키 없이 테스트가 돈다**
- GIVEN: OPENAI_API_KEY, MODEL_FT 없음
- WHEN: pytest
- THEN: ft: 분기는 목(mock)으로 검사되고, 기본 경로 테스트는 지금과 같이 통과한다

## 정할 것

- [ ] 이번 동결 안에 할지, 발표 확장 가능성으로만 둘지 (프론트 E1~E11이 전부 남아 있다)
- [ ] OpenAI 키와 예산
- [ ] C 묶음 파일(llm.py) 변경과 계약 C8(.env.example) 변경 승인
- [ ] 학습 건수와 경계 조합 범위, 사람이 검토할 표본 수
