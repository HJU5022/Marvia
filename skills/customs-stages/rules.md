---
# 계약 C6. 통관 단계 기준의 원본. 코드는 이 프론트매터를 읽는다 (SDD 3.6, 10-01).
# 키 하나는 skills/*/rules.md 중 한 파일에만 둔다. backend/app/services/rules.py가 모두 합쳐 읽고, 같은 키가 두 파일에 있으면 실패한다.
# 출처: UNI-PASS OpenAPI 연계가이드 v4.1, 2026-09-27 실제 조회 1건(부산항 해상 수입 일반화물, 단계 이름만 옮김). 검수: 하정운 (09-30, todo 칸).

# 통관 보류 낱말. 단계 이름에 하나라도 들어가면 customs_hold 신호가 켜지고 needs_broker가 true (services/signals.py)
customs_hold_words: [검사, 보류, 정지, 반송, 폐기]

# 통관 진행 평가 문장 (검사 규칙 V11, services/validate.py, 10-01). 한 문장에 주어 낱말과 평가 낱말이 같이 있으면 위반이다.
# 단계 이름만으로는 통관이 잘되는지 알 수 없어 이런 평가는 근거가 없다 (SKILL.md "통관 단계를 말할 때").
# 주어 낱말이 없는 문장("입항이 지연되고 있습니다")은 걸리지 않는다
customs_subject_words: [통관, 세관]
customs_assessment_words: [순조, 원활, 양호, 문제없, 문제 없, 정상적으로 진행, 정상 진행, 잘 진행, 지연될, 늦어질, 곧 끝]

# 정상 단계 목록 (해상 수입 일반화물). name은 UNI-PASS 이력의 처리구분 이름 그대로다.
# 코드는 name만 읽어 "목록에 없는 단계"를 가린다 (띄어쓰기는 무시, rules.stage_key). meaning·next·todo는 LLM 설명용이다.
# next가 null이면 다음 단계가 없다(통관 끝, 또는 앞 단계에 따라 다음이 달라짐. 이유는 meaning).
customs_stages:
  - name: 입항적재화물목록 제출
    meaning: 배에 실린 화물 목록을 세관에 냈다
    next: 입항적재화물목록 심사완료
    todo: 없음. 배가 오는 중
  - name: 입항적재화물목록 심사완료
    meaning: 세관이 목록을 확인했다
    next: 하선신고 수리
    todo: 없음
  - name: 하선신고 수리
    meaning: 배에서 내릴 화물과 내릴 곳이 승인됐다
    next: 입항보고 수리
    todo: 없음
  - name: 입항보고 수리
    meaning: 배가 입항했다
    next: 반입신고
    todo: 관세사에게 수입신고 서류가 준비됐는지 확인
  - name: 입항적재화물목록 운항정보 정정
    meaning: 목록의 운항 정보를 고쳤다. 흔한 행정 절차이고, 통관은 고치기 전 단계의 흐름을 그대로 이어 간다
    next: null
    todo: 없음
  - name: 반입신고
    meaning: 화물이 터미널·보세창고에 들어갔다
    next: 수입신고
    todo: 관세사가 수입신고를 했는지 확인
  - name: 수입신고
    meaning: 관세사가 수입신고를 냈다
    next: 수입(사용소비) 심사진행 또는 수입신고수리
    todo: 없음. 세관 처리를 기다린다
  - name: 수입(사용소비) 심사진행
    meaning: 세관이 신고 내용을 보고 있다. 정상 절차다
    next: 수입신고수리
    todo: 없음
  - name: 수입신고수리
    meaning: 통관이 끝났다
    next: 반출신고
    todo: 운송사와 반출·배송 일정을 잡는다. 수리일로부터 15일 안에 반출해야 하는 곳이 많고 넘기면 과태료가 붙는다
  - name: 반출신고
    meaning: 화물이 창고에서 나갔다
    next: null
    todo: 입고를 확인한다
---

# 통관 단계 기준값

| 키 | 뜻 | 읽는 곳 |
|---|---|---|
| customs_hold_words | 단계 이름에 이 낱말이 하나라도 들어가면 통관이 멈췄거나 검사 중인 단계로 본다 | services/signals.py (customs_hold 신호, needs_broker) |
| customs_stages | 정상 단계 목록. name(단계 이름), meaning(뜻), next(다음 단계, null이면 끝), todo(사용자가 할 일) | services/rules.py customs_stage_names (name만), LLM은 통관 해설에 전부 |

- 단계는 대체로 목록 순서로 찍히지만 하선신고가 입항보고보다 먼저 찍히기도 한다
- UNI-PASS 이력 줄에는 단계 코드가 없고 처리구분에 한글 이름이 온다. 그래서 코드 대신 이름으로 정리한다
