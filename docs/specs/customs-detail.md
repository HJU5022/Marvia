# Spec: UNI-PASS 처리 이력 원문 화면 표시

관련: [SDD 3.5](../Marvia_SDD.md) (UNI-PASS 응답에서 남기는 칸과 LLM에 넘기는 범위)

## 현재 동작

- B/L로 조회하면 결과 화면의 "관세청 처리 내역" 표에 UNI-PASS 화물통관진행정보의 처리 이력(`cargCsclPrgsInfoDtlQryVo`) 13칸을 그대로 보여 준다: 처리 구분, 처리 일시, 신고번호, 반출입 일시·근거·내용, 사전 안내, 장치장 이름·부호, 포장 개수·단위, 중량·단위
- 이 원문은 화면에만 간다. 판정 LLM, 후속 질문 LLM, 검증, DB 저장에는 들어가지 않는다

## 왜

단계 이름과 시각만으로는 반출 기한, 장치기간 안내, 포장·중량처럼 세관이 준 원래 값을 확인할 수 없었다. 수입자가 UNI-PASS 사이트에 따로 들어가지 않고 보게 한다.

## 규칙

SDD 3.5는 중량, 세관명, 화주 정보를 LLM에 넘기거나 DB에 저장하지 않는다고 정한다. 화면 표시는 막지 않는다. 이 원문에는 중량과 반출입 근거번호(`rlbrBssNo`, 관세법인명이 들어오기도 한다)가 들어 있어 아래처럼 화면에만 둔다.

| 규칙 | 위치 |
|---|---|
| 서버는 원문을 `CustomsRecord.display_rows`(`exclude=True`)로 받아 판정 LLM 입력(model_dump)에 넣지 않는다 | `schemas/customs.py`, `services/judge/customs.py` |
| 판정이 끝난 뒤 `AgentResponse.customs_detail`로 붙인다. 판정·검증 단계는 원문을 보지 않는다 | `routers/agent.py _assess` |
| 조회 이력 저장(`_logged`, query_log.response)에서 뺀다. 그래서 이력 재생·후속 질문 응답에는 원문이 없다. 채팅 대화 저장(conversations)에서도 같은 칸을 뺀다 | `routers/agent.py`, `routers/chat.py` |
| 컨테이너 번호는 조회 이력에 평문을 넣지 않고 [CNTR1] 번호표와 잠근 값으로 둔다 | `routers/agent.py _seal_containers` |
| 후속 질문 LLM 입력과 검증 허용 낱말에서도 뺀다 | `services/llm.py answer_follow_up`, `services/judge/validate.py` |
| 화면은 React 텍스트로만 그려 안내문 속 글자가 HTML로 해석되지 않는다 | `web/components/CustomsDetailTable.tsx` |

이 표의 범위가 아닌 UNI-PASS 칸: 품명(`prnm`), 포워더명(`frwrEntsConm`), 선사(`shcoFlco`), 컨테이너 번호(`cntrNo`)는 처리 이력 줄이 아니라 응답 상단 값이다. 이 값들은 `user_cargo`에 저장한다 (`019_cargo_sheet.sql`, `020_goods_name.sql`, [ERD.md](../ERD.md)). LLM에 넘기는 범위는 [SDD 3.5](../Marvia_SDD.md)에 있다.

## 범위 밖

- 처리 이력 원문의 DB 저장. 저장하게 되면 신고번호는 B/L처럼 암호화하고, 근거번호·중량·포장은 저장 대상에서 빼는 것을 다시 정한다
- 칸 해석(신고번호가 단계마다 무엇인지 등). UNI-PASS 글자 그대로 보여 준다

## 완료 기준

- `backend/tests/unit/test_customs_detail.py`: 13칸 파싱, 판정 LLM 입력·이력 저장·후속 질문 LLM 입력에 원문 없음, 판정 뒤 응답에 붙음
- 결과 화면에 "관세청 처리 내역" 표가 보인다 (`web/components/CustomsDetailTable.tsx`)
