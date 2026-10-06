---
# 계약 C6. 안내처(다음 행선지) 재료. 코드(services/referrals.py)가 이 프론트매터를 읽는다 (docs/specs/referral-guide.md, 10-06).
# 키 하나는 skills/*/rules.md 중 한 파일에만 둔다. backend/app/services/rules.py가 모두 합쳐 읽고, 같은 키가 두 파일에 있으면 실패한다.
# 안내 문장과 주소·전화는 코드가 붙인다. LLM은 쓰지 않는다. 주소·전화는 10-06에 접속해 확인한 값이다
signal_referrals:
  customs_hold: "관세사에게 바로 연락하세요. 관세청 고객지원센터 125 (평일 09:00~18:00)"
  dest_changed: "포워더에게 목적지가 부산이 아닌 이유(경유인지 변경인지)를 바로 확인하세요."
  sales_date_exceeded: "판매처에도 일정이 늦어질 수 있다고 알려 두세요."
  anchor_wait: "포워더에게 접안 예정일을 물어보세요."
  position_stale: "포워더에게 배의 현재 위치를 확인해 보세요."
  eta_conflict: "포워더에게 선사 스케줄 기준 입항 예정일을 확인해 보세요."
referral_order: [customs_hold, dest_changed, sales_date_exceeded, anchor_wait, position_stale, eta_conflict]
referral_max: 2
referral_prefix: "확인처: "
signal_referral_links:
  customs_hold: "진행 상황 직접 보기: UNI-PASS 화물진행정보 (https://unipass.customs.go.kr/csp/index.do)"
broker_referral: "확인처: 관세청 고객지원센터 125 · 관세법령정보포털 (https://unipass.customs.go.kr/clip/index.do)"
out_of_scope:
  - topic: air_land
    match: '항공|비행기|에어\s*카고|육상\s*운송|육로'
    reply: "마르비아는 부산항으로 들어오는 해상 수입 화물만 확인합니다. 항공·육상 화물은 포워더에게 문의해 주세요."
  - topic: warehouse_date
    match: '창고.*(언제|며칠|날짜|몇\s*일)|(언제|며칠|몇\s*일).*창고'
    reply: "창고에서 받는 날은 마르비아가 예측하지 않습니다. 반출 일정은 포워더에게 확인해 주세요. 지금 통관 단계는 알려 드릴 수 있어요."
  - topic: schedule_change
    match: '(앞당|당겨|늦춰|미뤄|바꿔|변경).*(일정|입항|예약|스케줄|배)|(일정|입항|예약|스케줄|배).*(앞당|당겨|늦춰|미뤄|바꿔|변경)'
    require: '줄\s*수|해\s*줘|해\s*주|가능|할\s*수|돼\?|되나|될까'
    reply: "마르비아는 예약이나 일정을 바꿀 수 없습니다. 일정 변경은 포워더나 선사에 요청해 주세요."
  - topic: weather
    match: '태풍|날씨|기상|파도|풍랑|폭풍'
    reply: "날씨로 늦어질지는 미리 판단하지 않습니다. 실제로 늦어지면 배 위치와 도착 예정에 나타나고, 그때 판정이 바뀝니다. B/L 번호를 알려 주시면 지금 상태를 확인해 드릴게요."
  - topic: import_requirement
    match: '(수입|들여오|들여올).*(요건|인증|허가|검역)|(요건|인증|허가|검역).*(필요|받아야|해야)'
    reply: "품목별 수입 요건은 마르비아가 판단하지 않습니다. 신고를 맡은 관세사에게 요건을 확인해 주세요."
---

# 안내처 표

코드(services/referrals.py)가 아래 키를 읽어 "다음 행선지"를 붙인다. 문장과 주소는 코드가 붙이고 LLM은 쓰지 않는다.
원본 설명과 정한 이유는 docs/specs/referral-guide.md에 있다.

| 키 | 쓰는 곳 | 뜻 |
|---|---|---|
| signal_referrals | 판정 응답의 할 일(actions) 끝 | 켜진 신호마다 누구에게 무엇을 물을지. 없는 신호(navstat_mismatch)는 붙이지 않는다 |
| referral_order, referral_max | 같은 곳 | 여러 신호가 켜지면 이 순서(위험한 순서)로 referral_max개까지만 |
| referral_prefix | 같은 곳 | 붙이는 줄의 머리 |
| signal_referral_links | 같은 곳 | 신호에 붙는 공식 창구 줄. 지금은 통관 보류에만 |
| broker_referral | 채팅 세액·통관 가부 고정 안내 끝 | 관세사 안내 뒤 공식 창구 |
| out_of_scope | 채팅, B/L이 없는 문장 | 범위 밖 주제를 LLM 없이 고정 문장으로 답한다. require가 있으면 그것도 맞아야 한다 |

- "괜찮음"(켜진 신호 없음)에는 붙이지 않는다. 불필요한 행동을 시키지 않는다
- 입력 오류로 세지 않는 신호(깨진·빈 목적지, cargo-verdict/rules.md ignore_dest_values)에는 붙이지 않는다
- 날씨 답은 원인을 단정하지 않는다. 판정은 관측값에서 나오고 날씨 영향은 관측할 수 없는 추정이다 (10-06 결정 논의)
- 품목별 수입 요건 기관(식품, 농산물 검역 등)은 넣지 않는다. 품목마다 달라 덮을 수 없고 판정과 무관하다
