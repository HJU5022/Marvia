"""판정 흐름이 LLM 없이 내는 고정 문구와 판정 재시도 상한 (routers/agent.py에서 옮김, SDD 5.7, 8절). 데이터만 있고 동작은 없다."""

from backend.app.services.judge import verdict as verdict_table

NOT_JUDGED = "조회한 값을 정리했습니다. 판정은 아직 붙지 않았습니다."

# 화면에 그대로 나가는 문구라 약어(M/H, ETA)를 풀어 쓴다 (화면 용어 점검)
NO_CARGO = "조회 결과가 없습니다. B/L 번호와 마스터·하우스 구분을 다시 확인해 주세요."

ASK_BACK = "같은 이름의 배가 여러 척입니다. 항차 번호나 포워더가 알려 준 입항 예정일을 알려주시면 어느 배인지 가릅니다."

# 항차·입항 예정일을 이미 받았는데도 못 가른 경우 (버그 찾기). 같은 ASK_BACK을 되풀이하면 "항차를 알려 달라"는 말에
# 항차를 알려 줬는데 또 항차를 달라는 꼴이 된다. 화면 후보 고르기(web/components/CandidatePicker.tsx)가 있어 그것을 안내한다
ASK_BACK_AFTER_EVIDENCE = ("알려 주신 항차나 입항 예정일로도 어느 배인지 가르지 못했습니다. "
                           "화면의 후보 중에서 고르시거나, 포워더에게 받은 입항 예정일을 알려 주세요.")

NO_VESSEL = "선박 위치 서비스에서 이 배를 찾지 못했습니다. 포워더 도착 통지서(A/N)의 입항 예정일을 알려주세요."

# 사용자가 고른 배(resolved_mmsi)가 이 화물의 후보에 없을 때. 전에는 어떤 MMSI든 그대로 확정해서,
# 화면을 거치지 않고 아무 번호나 보내면 남의 배로 판정했고 "배는 확인했지만" 같은 앞뒤 안 맞는 답이 나왔다
RESOLVED_NOT_CANDIDATE = "고르신 배가 이 화물의 후보 목록에 없어 확정하지 않았습니다. 화면의 후보 중에서 다시 골라 주세요."

RESOLVED_NO_CANDIDATES = "고르신 배를 이 화물의 후보에서 확인하지 못했습니다."

NO_VESSEL_AFTER_ETA ="선박 위치 서비스에서 이 배를 찾지 못해 판정하지 못했습니다. 입항 일정은 포워더에게 직접 확인해 주세요."

VESSEL_TOOL_FAILED = "선박 위치 서비스에 연결하지 못해 판정하지 못했습니다. 잠시 뒤 다시 조회해 주세요."

# 위치 없음 ("위치 없음 → 판정 보류" 문구: 조회되지 않는다고 그대로 말하고 포워더 입항 예정일을 묻는다)
POSITION_MISSING = "배는 확인했지만 지금 배 위치가 조회되지 않아 판정하지 않았습니다. 포워더 도착 통지서(A/N)의 입항 예정일을 알려주세요."

POSITION_MISSING_AFTER_ETA = "배는 확인했지만 지금 배 위치가 조회되지 않아 판정하지 않았습니다. 입항 일정은 포워더에게 직접 확인해 주세요."

# 도착일 모름. 대략값은 코드 계산이라 "참고용"을 반드시 붙인다 ("신뢰하지 마세요")
NO_ETA = ("판매 예정일은 받았지만 도착 예정일을 확인할 근거(해수부 입항 신고, AIS 도착 예정)가 아직 없어 판정하지 않았습니다. "
          "포워더 도착 통지서(A/N)의 입항 예정일을 알려주시면 판매 예정일까지 여유를 봐 드립니다.")

NO_ETA_WITH_ESTIMATE = ("판매 예정일은 받았지만 도착 예정일을 확인할 근거(해수부 입항 신고, AIS 도착 예정)가 아직 없어 판정하지 않았습니다. "
                        "현재 위치와 속도로 계산한 대략적인 부산 도착은 {month}월 {day}일쯤입니다. 참고용이며 속도나 기항지에 따라 달라질 수 있습니다. "
                        "포워더 도착 통지서(A/N)의 입항 예정일을 알려주시면 판매 예정일까지 여유를 봐 드립니다.")

POSITION_TOOL_FAILED = "선박 위치 조회에 실패해 판정하지 않았습니다. 해수부 입항 예정은 참고로만 보여 드립니다. 잠시 뒤 다시 조회해 주세요."

# ShipFinder 하루 호출 한도를 다 썼을 때 (status 38, clients/shipfinder.py quota_exhausted). 오늘은 다시 조회해도 안 되므로
# "잠시 뒤"가 아니라 내일이라고 알린다
QUOTA_EXHAUSTED_TAIL = " 오늘 선박 위치 조회 한도를 다 써서, 내일 다시 조회해 주세요."

NOT_BUSAN = "부산항에 내리는 화물만 확인할 수 있습니다. 이 화물은 다른 항만으로 들어옵니다."

LLM_FAILED = "판정을 만들지 못했습니다. 조회한 값과 신호만 보여 드립니다."

# 판정 LLM이 끝내 실패했을 때 표 등급으로 확정하며 쓰는 문구 (_llm_gave_up). 숫자를 넣지 않는다 (V7)
TABLE_FALLBACK = "판정 표 기준으로 '{label}'입니다. 설명 문장은 만들지 못했습니다. 아래 근거를 확인해 주세요."

VERDICT_LABEL = verdict_table.VERDICT_LABEL  # 원본은 services/judge/verdict.py (화물 비서 "지난 조회" 줄과 같이 쓴다)

# 반출된 화물. 반출신고는 통관의 마지막 단계다 (skills/customs-stages/rules.md customs_stages, next가 null)
RELEASED_STAGE = "반출신고"

RELEASED = "이 화물은 이미 보세창고에서 반출됐습니다. 통관이 끝나 배 위치는 확인하지 않았습니다. 배송 일정은 운송사에 확인해 주세요."

RELEASED_EXPLANATION = "화물이 보세창고에서 나갔고 세관 절차가 모두 끝났습니다."

# 할 일은 customs-stages/rules.md 반출신고 todo("입고를 확인한다")를 따르고, 범위 밖인 배송 일정은 운송사로 넘긴다 (PRD 4절 창고 수령일 예측)
RELEASED_ACTIONS = ["배송 일정은 운송사에 확인하세요.", "물건이 도착하면 입고를 확인하세요."]

# 목록에 없는 통관 단계의 설명 문장. customs-stages/rules.md에 뜻이 없어 LLM이 설명할 근거가 없다.
# LLM에 맡기면 이름만 보고 뜻을 지어내거나 "지연될 수 있다" 같은 평가를 덧붙였다 (평가 B10 "검사지정", 매번)
UNLISTED_STAGE_EXPLANATION = "{stage} 단계입니다. 목록에 없는 단계라 뜻을 확인할 수 없어 관세사 확인이 필요합니다."

JUDGE_ATTEMPTS = 3  # 판정 LLM 호출 최대 횟수: 처음 + 위반 내용 첨부 + 강화 (SDD 5.7)

# 판정 재시도의 시간 예산(초). 판정 표 같은 도메인 임계값이 아니라 응답 대기 상한이라 코드에 둔다.
# 다음 시도는 "지금까지 쓴 시간 + 방금 호출에 걸린 시간"이 이 값 안에 들어올 때만 시작한다. 안 들어오면 더 묻지 않고
# 판정 표 등급 + 고정 문구로 partial을 낸다(_llm_gave_up, 등급은 원래 코드가 정한다).
# 근거: 화면은 90초에 요청을 포기한다(web/lib/api.ts AGENT_TIMEOUT_MS). 실측에서 판정 호출 한 번이 7~40초였고,
# 세 번 다 돌면 121초·170초가 나와 화면이 먼저 끊겼다. 판정 앞 단계(채팅 이해, 통관·식별·위치 조회)에 쓸 몫을 남긴다.
# 한계: 호출 하나의 상한은 llm.TIMEOUT_SEC(60초)이라, 예상보다 느린 마지막 호출은 이 예산을 넘을 수 있다
JUDGE_BUDGET_SEC = 60.0

# _identify가 "선박 검색 도구가 실패했다"를 알릴 때 쓰는 라우터 안의 표시. 응답의 vessel_match로는 나가지 않는다
TOOL_FAILED = "tool_failed"

FOLLOW_UP_FAILED = "질문에 답하지 못했습니다. 잠시 뒤 다시 물어봐 주세요."

# 질문이 역할 재설정·지시 무시 모양이면 LLM을 부르지 않고 이 문구로 답한다 (services/judge/guard.py, SDD 7절)
FOLLOW_UP_BLOCKED = "이 화물의 조회 결과에 대한 질문에만 답할 수 있습니다. 예: 여유가 며칠인가요? 지금 통관 단계는 무엇인가요?"

# 후속 답에 거는 검증 규칙. answer 문장을 보는 것은 V1(오래된 위치를 현재 위치라 하지 않기),
# V7(근거에 없는 숫자 금지), V11(통관 진행 평가 금지)이다. 나머지는 판정·근거 칸을 보는데, 후속 질문은 그 칸을 바꾸지 않는다 (services/judge/validate.py)
# 여기에 후속 답 전용 V9(근거에 없는 영문 낱말 금지, validate.check_follow_up_words)와 V10(질문 낱말 옮기기 금지)을 더 건다
FOLLOW_UP_RULES = {"V1", "V7", "V11", "V15"}  # V11: 후속 답에도 통관 진행 평가를 쓰지 않는다. V15: 판매 예정일이 지났다고 쓰지 않는다

# 후속 질문에서 LLM이 부른 도구 결과를 근거 카드로 붙일 때의 출처. Evidence.source 값 중에서 고른다 (계약 C1, 바꾸지 않음)
TOOL_SOURCE = {"get_vessel_candidates": "shipfinder", "get_live_position": "shipfinder",
               "get_port_schedule": "mof", "estimate_distance": "searoute"}
