# Spec: UNI-PASS 처리 이력 원문 화면 표시 

## 무엇을
B/L로 조회하면 결과 화면에 UNI-PASS 화물통관진행정보의 처리 이력(`cargCsclPrgsInfoDtlQryVo`) 13칸을 그대로 보여 준다.
처리 구분, 처리 일시, 신고번호, 반출입 일시·근거·내용, 사전 안내, 장치장 이름·부호, 포장 개수·단위, 중량·단위.

## 왜
지금 화면은 단계 이름과 시각만 보여 준다. 수입자는 반출 기한, 장치기간 안내, 포장·중량처럼 세관이 준 원래 값을
UNI-PASS 사이트에 따로 들어가지 않고 확인하고 싶어 한다 (사용자 요청).

## 규칙과의 관계
SDD 3.5·7절은 "UNI-PASS의 중량·세관명·화주 정보를 LLM에 넘기거나 DB에 저장하지 않는다"이다 (품명은 예외로 저장하고 채팅 LLM에 준다. 이 Spec의 화면 표 범위와는 별개다). 화면 표시는 막지 않는다.
이 원문에는 중량과 관세법인·포워더명(rlbrBssNo)이 들어 있어 아래처럼 화면에만 둔다.

- 서버: `CustomsRecord.display_rows`(exclude=True)로 받아 판정 LLM 입력(model_dump)에 들어가지 않는다
- 판정이 끝난 뒤 `AgentResponse.customs_detail`로 붙인다 (`routers/agent.py _assess`). 판정·검증 단계는 원문을 보지 않는다
- 이력 저장(`_logged`, query_log.response)에서 뺀다. 그래서 이력 재생·후속 질문 응답에는 원문이 없다. 채팅 대화 저장(`routers/chat.py`, conversations)에서도 같은 칸을 뺀다
- 컨테이너 번호도 같은 줄에서 다룬다: 이력에는 평문을 넣지 않고 [CNTR1] 번호표와 잠근 값으로 둔다 (`_seal_containers`)
- 후속 질문 LLM 입력(`llm.answer_follow_up`)과 검증 허용 낱말(`validate.py`)에서도 뺀다
- 화면은 React 텍스트로만 그려 안내문 속 글자가 HTML로 해석되지 않는다 (`web/components/CustomsDetailTable.tsx`)
- 품명(prnm)은 이력 줄이 아니라 상단에 있고 이 표의 범위가 아니다. `user_cargo.goods_name`에 따로 저장한다 (docs/ERD.md)

## 하지 않는 것
- DB 저장. 저장하게 되면 신고번호는 B/L처럼 암호화, 근거번호·중량·포장은 저장 대상에서 빼는 것을 다시 정한다
- 칸 해석(신고번호가 단계마다 무엇인지 등). UNI-PASS 글자 그대로 보여 준다

## 완료 기준
- `backend/tests/unit/test_customs_detail.py`: 13칸 파싱, 판정 LLM 입력·이력 저장·후속 질문 LLM 입력에 원문 없음, 판정 뒤 응답에 붙음
- 결과 화면에 "관세청 처리 내역" 표가 보인다 (`web/components/CustomsDetailTable.tsx`)
