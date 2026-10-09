"""채팅 창구가 사용자에게 보내는 고정 문구와 LLM에 붙이는 힌트 글 (services/chat/chat.py에서 옮김). 데이터만 있고 동작은 없다."""
from __future__ import annotations

from backend.app.services.chat import referrals
from backend.app.services.watch.watch import MAX_WATCH

# cargo.previous_line이 만드는 줄의 머리 ("지난 조회(10.01)에서는..."). 채팅 답에 붙는 기억 줄은 이것 하나뿐이다 (D1)
PREVIOUS_LINE_PREFIX = "지난 조회("

DEFAULT_BL_TYPE = "HOUSE"  # 구분을 말하지 않으면 House로 조회하고 답에 알린다 (소량 수입자는 보통 House B/L)

# 예시에 테스트 B/L을 쓰지 않는다. 실제 사용자에게 가짜 번호를 보여 주게 된다 (화면 용어 점검)
NEED_BL = "조회할 B/L 번호를 문장에 넣어 주세요. 예: (내 B/L 번호) 화물 괜찮아?"

NO_CARGO = "지금 보고 있는 화물이 없어요. 먼저 B/L 번호로 화물을 조회해 주세요."

LLM_DOWN = "지금은 문장 이해 기능을 쓸 수 없어 B/L 번호가 있는 조회만 돼요. " + NEED_BL

# 출처 줄은 짧게 한 줄. 유럽 설명은 결과가 없을 때만 아래 EMPTY 문장에 한 줄로 붙인다
PREV_PORT_NOTE = "해수부 입항 신고의 직전 기항지 기준이에요."

PREV_PORT_EMPTY_NOTE = PREV_PORT_NOTE + " 출발지가 아니라 직전에 들른 항구라서, 유럽발 배는 중국·싱가포르 등으로 나올 수 있어요."

# 프롬프트 주입 방어 (SDD 7절). 아래 두 문구는 LLM이 쓴 문장을 내보낼 수 없을 때 대신 쓰는 고정 안내다
# 끝을 "B/L 번호를 달라"에서 "사용법을 물어보라"로 바꿨다: 모델이 답을 포기할 때마다 B/L만 요구하면 챗봇 같다는 판단
OTHER_REPLY = ("마르비아는 B/L 번호로 화물 상태를 확인하고, 지금 보고 있는 화물에 대한 질문에 답하고, "
               "어디에서 오는 배가 부산에 들어오는지 찾아 드려요. 자세한 사용법은 \"어떻게 써?\"라고 물어봐 주세요.")

# 인사에는 인사만 한다. B/L을 달라고 하거나 기능을 늘어놓지 않는다 (answer_kind=greeting)
GREETING_REPLY = "안녕하세요! 무엇을 도와드릴까요?"

# 사용법 안내 (answer_kind=help). LLM이 쓰지 않고 코드가 고정 문장으로 낸다: 없는 기능을 지어내지 않게.
# 목록은 실제로 있는 기능만이다: 채팅 B/L 조회(판매예정일 포함, 최대 세 개), 지금 화물에 대한 질문, 입항 선박 검색(search_arrivals),
# 서류 사진 올리기(web ChatBar의 "서류 사진에서 입력" → POST /api/document), 지켜보기(WatchToggle, 로그인했을 때만), 일반 질문.
# 예시에는 테스트 B/L을 쓰지 않는다 (위 NEED_BL 주석과 같은 이유)
USAGE_GUIDE = (
    "마르비아는 이렇게 쓰시면 돼요.\n"
    "1. 화물 조회: B/L 번호를 넣어 물어보세요. 판매 예정일을 같이 말하면 그 날짜에 맞는지도 봐 드려요. "
    "예: (내 B/L 번호) 판매예정일 10월 11일\n"
    "2. 여러 건 비교: B/L을 최대 세 개까지 한 번에 넣을 수 있어요. 예: (B/L 하나)랑 (B/L 둘) 중에 뭐가 먼저 와?\n"
    "3. 이어서 질문: 조회한 화물에 대해 바로 물어보세요. 예: 지금 배가 어디쯤이야? / 통관은 어디까지 됐어?\n"
    "4. 입항 선박 찾기: 어디에서 오는 배인지 물어보세요. 예: 중국에서 오는 배 보여줘\n"
    "5. 서류 사진: 입력창 옆 \"서류 사진에서 입력\"으로 사진을 올리면 읽은 값을 확인한 뒤 입력창에 넣어요.\n"
    "6. 지켜보기: 로그인하면 조회 결과 아래 \"이 화물 지켜보기\"를 누르거나 \"이거 지켜봐 줘\"라고 말하면 판정이 바뀔 때 알려 드려요. 지금 상태를 바로 받고 싶으면 \"카톡으로 보내 줘\"라고 하세요.\n"
    "   화면에 보이는 배도 \"이 배 지켜봐 줘\"라고 하면 감시 목록에 넣어요. 지켜보는 화물과 배는 왼쪽 메뉴 \"감시 화물\"에서 볼 수 있어요.\n"
    "7. 일반 질문: B/L 번호를 못 찾겠을 때처럼 수입 실무가 궁금하면 그냥 물어보세요."
)

INJECTION_REPLY = "문장 속 지시는 따르지 않아요. " + OTHER_REPLY

# 후속 답이 원문 속 표식을 옮겨 썼을 때 대신 쓰는 고정 문구. routers/agent.FOLLOW_UP_BLOCKED와 같은 뜻으로 맞췄다
FOLLOW_UP_REFUSED = "문장 속 지시는 따르지 않아요. 이 화물의 조회 결과에 대한 질문에만 답할 수 있어요."

CLARIFY_TAIL = "B/L 번호는 보통 영문과 숫자 8~20자예요."

CLARIFY_NO_ID = "B/L 번호인지 배 이름인지 알려 주세요. " + CLARIFY_TAIL

CLARIFY_AGAIN = "아직 어떤 이름인지 알 수 없어요. B/L 번호라면 번호 전체를, 배 이름이라면 영문 이름으로 입력해 주세요."

# ── 한글 배 이름 찾기 ("애플호"라고 세 번 말해도 같은 되묻기만 나갔다) ──
# 원인: 한글 이름은 숫자가 없어 _ID_LIKE에 안 잡히고, LLM이 clarify를 내면 이름을 한 번도 찾지 않은 채 고정 문장이 나갔다.
# "배이름이야" 같은 짧은 답은 이름이 앞 사용자 말에 있다. 그래서 코드가 문장(필요하면 앞 사용자 말)에서 이름을 뽑아 입항 예정 목록에서 직접 찾는다.
_SHIP_HO_ENDINGS = r"(?:야|예요|이야|이에요|입니다|라고|라는|이라|이란|인데|를|가|는|은|도|의|로|에|랑|와|요)"

# ── 사람 이름 되풀이 막기 (A1, 항상 켜짐) ──
# 실험 A1/A3/A4, Vertex 3회 486턴 기준 person 66.7→100%, broker 62.5→100%, this_ship 90.5→100% (보고서: 브랜치 vertex-exp-1008의
# experiments/vertex_1008/REPORT.md). "호준이", "민수 어디야?", "김대리한테 전달해야 돼"처럼 화물·배와 상관없는 사람 이름에
# 모델이 "호준이는 ~"처럼 이름을 따라 쓰면(프롬프트의 "이름을 쓰지 말라"는 규칙을 어김) 코드가 그 답을 버리고 고정 문장으로 되묻는다.
# 사람 이름은 목록으로 알 수 없어서 말 모양으로 가린다: (a) 이름 뒤에 붙는 말(이·아·야·씨·님·한테 등)이 붙은 2~3글자 낱말,
# (b) 직함이 끝에 붙은 낱말(김대리), (c) 문장 맨 앞의 2~3글자 낱말(서술어 끝이 아닐 때). 단 Skill 문서·고정 안내에 있는 낱말(화물, 통관 등)은 이름이 아니다.
PERSON_ASK = "누구를 말씀하시는지 잘 모르겠어요. 화물이나 배라면 B/L 번호나 배 이름으로 알려 주세요."

_PERSON_SUFFIXES = sorted(["이한테", "한테", "이는", "이가", "이랑", "이도", "이야", "씨", "님", "이", "아", "야"], key=len, reverse=True)

CONTAINER_NOT_FOUND = ("내 화물 목록에서 이 컨테이너 번호를 찾지 못했어요. 조회한 적 있는 화물만 컨테이너 번호로 찾을 수 있어요. "
                       "B/L 번호로 조회해 주세요.")

CONTAINER_NEED_LOGIN = ("컨테이너 번호로 찾기는 로그인한 뒤 조회한 적 있는 화물에서만 돼요. "
                        "로그인하거나 B/L 번호로 조회해 주세요.")

ARRIVALS_LIMIT_NOTE = "입항 예정은 오늘부터 최대 {n}일까지만 보여 드릴 수 있어요."

FAILED_LOOKUP = "조회하지 못했어요. 잠시 뒤 다시 물어봐 주세요."  # 고른 도구가 모두 실패했을 때

# 읽기 전용 도구 결과를 문장으로 못 옮겼을 때 (검사에 걸렸거나 답이 비었을 때). 틀린 문장을 내보내지 않는다
LOOKUP_NOT_SUMMARIZED = "조회는 했지만 결과를 문장으로 정리하지 못했어요. 다시 물어봐 주세요."

# 위 문구는 마지막 수단이다 (같은 막다른 문구가 연달아 나갔다). 도구 결과가 있으면 먼저 코드가
# 결과 값을 그대로 옮긴 문장(lookup_fallback)을 낸다: 값은 도구가 준 것뿐이라 LLM 문장 검사(V7·V9·V10)가 필요 없다
LOOKUP_FALLBACK_LEAD = "조회한 결과를 그대로 전해 드려요."

LOOKUP_FALLBACK_SAME = "방금과 같은 조회 결과예요."  # 바로 앞 답과 글자가 같을 때 앞에 붙인다 (같은 답 연속 금지)

# 같은 B/L이 연달아 "조회 결과 없음"일 때 ("다시 해줄래"에 같은 문장이 되풀이됐다).
# 같은 조회를 반복해도 결과가 같으니 번호와 구분을 고쳐 보게 한다. 구분은 코드가 아는 값으로 반대쪽을 권한다
NO_RESULT_REPLY = "조회 결과가 없어요. B/L 번호와 마스터·하우스 구분을 다시 확인해 주세요."  # routers/agent.NO_CARGO의 "~요" 버전 (말투 통일)

NO_RESULT_AGAIN = ("같은 번호로 다시 조회해도 결과가 없어요. 번호를 한 글자씩 다시 확인해 주세요. "
                   "지금은 {now} B/L로 조회했는데, {other} B/L이면 \"{other_ko}로 다시\"라고 말해 주세요.")

NO_RESULT_THIRD = "그래도 안 나오면 포워더나 선사에게 B/L 번호를 다시 받아서 확인해 주세요."

BL_TYPE_KO = {"MASTER": "마스터", "HOUSE": "하우스"}

# 도구 없는 실무 질문인데 Skill 문서로 받칠 수 없을 때 (answer_kind=not_in_skills, 또는 근거 조각 검사 V14에 끝내 걸렸을 때).
# 도메인 조언은 제품 담당이 쓴 skills/*.md에서만 나온다. 문서에 없으면 지어내지 않고 없다고 말한다
NOT_IN_SKILLS = "그 내용은 마르비아가 가진 자료에 없어요. " + OTHER_REPLY

# 화면에 화물이 있는데 통관 시기를 도구 없이 답했을 때 다시 묻는 말: 그 화물의 실제 통관 단계로 답해야 한다 (날짜 약속은 하지 않는다)
CLEARANCE_HINT = ("has_current_cargo is true and the message asks about clearance timing. Call ask_cargo so the answer uses the "
                  "real customs stage of this cargo. Do not promise a date.")

# 같은 고정 안내를 두 번 연달아 보이지 않는다 (실측: 같은 긴 안내가 세 번 반복됐다). 바로 앞 답이 고정 안내면 더 짧은 말로 바꾼다
SHORT_NOTICE = "그 부분은 제가 확인할 자료가 없어요. 화물 B/L 번호나 배에 대해 물어봐 주세요."

SHORT_NOTICE_2 = "아직 확인할 자료가 없어요. \"어떻게 써?\"라고 물어보시면 할 수 있는 일을 알려 드려요."

BROKER_SHORT = "그건 관세사에게 확인해 주세요."

# 화면에 화물이 있는데 도구 없이 안내만 냈을 때 한 번 다시 물으며 붙이는 말 (실측: "이 배 지금 어디쯤이야?"에 ask_cargo를 안 불렀다)
CARGO_ON_SCREEN_HINT = ("You called no tool. has_current_cargo is true. If the message asks about this ship or this cargo "
                        "(where it is, when it arrives, customs, what to do), call ask_cargo. If it asks which ships come "
                        "from a place, call search_arrivals. Otherwise answer as before.")

MEMO_ANON = "로그인하면 저장한 메모를 찾아 드릴 수 있어요."

MEMO_NONE = "저장된 메모에서 찾지 못했어요."

MEMO_HINT = ("The user asks about something they saved or told Marvia before (a contact, a phone number, a note). Call recall_memo "
             "now (topic contact for a company or phone number, otherwise any; query = the company, role, ship or cargo words the "
             "user used). Do not answer not_in_skills for this.")

MEMO_SAVE_LEAD = "알려 주신 내용은 메모로 기억해 둘게요."

DATE_PROMISE_NOTE = "반출이나 수령 날짜는 약속드릴 수 없어요. 위 통관 단계를 확인해 주세요."

BROKER_ONLY = "관세·세금·통관 가능 여부는 마르비아가 답하지 않아요. 관세사에게 문의해 주세요.\n" + referrals.broker_tail()

# 한 문장에 B/L이 여러 개일 때의 고정 문장. 번호는 적지 않는다: 코드가 쓴 문장에도 원문 B/L을 새로 내보내지 않으려고
MULTI_BL_NOTICE = "(한 번에 최대 세 개까지 조회해요. 나머지는 따로 보내 주세요.)"

MULTI_TABLE_LEAD = "화물 {n}건을 조회했어요. 표에서 하나를 누르면 아래에 자세히 보여 줘요."  # LLM 비교 문장이 없거나 검사에 걸렸을 때. 표가 답이다 (화면: 결과 칸은 대화창 아래다)

MULTI_FAILED_NOTICE = "(일부 B/L은 조회하지 못했어요. 잠시 뒤 따로 다시 물어봐 주세요.)"

# 여러 B/L 중 판정을 못 낸 줄 (화면: 표에 "판정 없음 / 선박 확인되지 않음"만 떠서 무엇이 필요한지 몰랐다).
# 이유는 표 칸(note)에, 해야 할 일은 답 문장에 코드가 쓴다. 판정 흐름의 되묻기·결과 없음 문구(routers/agent)와 같은 뜻이다
ROW_NEED_NOTE = "확인 필요"

ROW_NOTE_SAME_NAME = "같은 이름 배 {n}척"

ROW_NOTE_NOT_FOUND = "조회 결과 없음"

ROW_NOTE_MORE_INFO = "정보 더 필요"

ROW_SAY_SAME_NAME = "{bl}는 같은 이름의 배가 여러 척이라 항차 번호나 포워더 입항 예정일이 필요해요."

ROW_SAY_STILL_SAME = "{bl}는 알려 주신 항차나 입항 예정일로도 어느 배인지 가르지 못했어요."

ROW_SAY_NOT_FOUND = "{bl}는 조회 결과가 없어요. B/L 번호와 마스터·하우스 구분을 확인해 주세요."

SALE_PAST = "입력하신 판매일 {m}월 {d}일은 이미 지난 날짜예요."

SALE_UNREADABLE = "판매일을 날짜로 읽지 못해서 쓰지 않았어요."

ROW_SAY_MORE_INFO = "{bl}는 판정에 필요한 정보가 더 필요해요."

# B/L로 읽지 못한 식별자 모양 글자 안내 (화면: "tesbl41"이 말없이 빠졌다)
UNREAD_NOTICE = "(B/L 번호로 읽지 못한 글자가 있어요: {names}. 번호를 확인해 주세요.)"

# 구분을 말하지 않으면 하우스 → 마스터 순으로 코드가 알아서 조회한다. 예전 "하우스로 조회했어요" 안내(HOUSE_NOTICE)는 없앴다
NOT_FOUND_BOTH = "bl_not_found"  # 하우스·마스터 둘 다 세관에 없을 때 응답의 missing_inputs 표식 (web CandidatePicker, cargo.found_cargo가 읽는다)

NO_RESULT_BOTH = "조회 결과가 없어요. B/L 번호를 다시 확인해 주세요."

WATCH_ASK = "이 화물을 지켜볼까요?"

WATCH_LOGIN_TAIL = "로그인하면 지켜보다가 알려 드려요."

# 켜기 성공 문장. 카카오톡은 연결해 둔 사람에게만 간다 (services/watch/watch._notify: 연결 안 됨은 조용히 넘어간다). 화면 띠는 누구에게나 뜬다
WATCH_ON_REPLY = ("이 화물을 지켜볼게요. 판정이 바뀌면 다음에 접속할 때 알려 드리고, "
                  "카카오톡을 연결해 두셨다면 카카오톡으로도 보내 드려요.")

WATCH_ON_PLAIN = "이 화물을 지켜볼게요. 판정이 바뀌면 다음에 접속할 때 알려 드려요."

KAKAO_LINKED_TAIL = "판정이 바뀌면 카카오톡으로도 보내 드려요."

KAKAO_UNLINKED_TAIL = "카카오톡은 아직 연결되지 않았어요. 설정에서 연결하면 판정이 바뀔 때 카톡으로도 받을 수 있어요."

WATCH_OFF_REPLY = "이 화물은 더 이상 지켜보지 않을게요."

WATCH_NEED_LOGIN = "로그인하면 이 화물을 지켜보다가 판정이 바뀔 때 알려 드려요."

WATCH_HOW = "지켜보기를 켜거나 끄려면 \"이 화물 지켜봐 줘\", \"그만 지켜봐도 돼\"처럼 말씀해 주세요."

WATCH_NO_CARGO = "지켜볼 화물이 없어요. 먼저 B/L 번호로 화물을 조회해 주세요."

WATCH_ONE_AT_A_TIME = "한 번에 한 화물만 지켜볼 수 있어요. 하나씩 말씀해 주세요."

# WatchError.kind(services/watch/watch.py) 와 저장소 실패(db)를 사용자 문장으로. 켜기가 안 된 이유를 지어내지 않고 종류별로 쓴다
WATCH_NOT_FOUND = "화물을 찾지 못해 감시 등록은 하지 못했어요. B/L 번호를 다시 확인해 주세요."

WATCH_FAIL_REPLY = {
    "not_saved": "이 화물은 아직 저장되는 중이에요. 잠시 뒤에 다시 말씀해 주세요.",
    "done": "반출이 끝난 화물은 지켜볼 수 없어요.",
    "limit": f"지켜보기는 최대 {MAX_WATCH}건까지예요. 다른 화물을 먼저 꺼 주세요.",
    "no_key": "화물 정보를 안전하게 열 수 없어 지금은 지켜볼 수 없어요.",
    "db": "지켜보기 저장소에 연결하지 못했어요. 잠시 뒤 다시 말씀해 주세요.",
}

# 지켜보기 성공·이미 켜짐 답 끝에 붙이는 감시 화물 쪽 링크. 줄 머리 "감시 화물에서 보기: "는 화면(ChatBar linkify)이 링크 줄로 알아본다.
# 주소는 서버가 모르는 웹 기본 주소 없이 사이트 안 경로(/watch, web/components/Shell.tsx "감시 화물" 메뉴와 같다)만 쓴다
WATCH_PAGE_LINE = "감시 화물에서 보기: [감시 화물](/watch)"

WATCH_ALREADY_HEAD = "이미 이 화물을 지켜보고 있어요."

WATCH_ALREADY_ON = WATCH_ALREADY_HEAD + " 판정이 바뀌면 알려 드려요."

WATCH_ALREADY_OFF = "이 화물은 지금 지켜보고 있지 않아요."

VESSEL_ASK_WHICH = "어느 배를 넣을까요? 배 이름을 알려 주세요."

VESSEL_NEED_LOGIN = "로그인하면 배를 감시 목록에 넣을 수 있어요."

VESSEL_UNAVAILABLE = "지켜보기 저장소에 연결하지 못했어요. 잠시 뒤 다시 말씀해 주세요."

VESSEL_NOT_FOUND = "그 이름의 배를 찾지 못했어요. 배 이름을 다시 확인해 주세요."

VESSEL_MANY = "같은 이름의 배가 여러 척이라 어느 배인지 정하지 못했어요. 목록에서 배를 눌러 고른 뒤 다시 말씀해 주세요."

VESSEL_ON_REPLY = "{name} 선박을 감시 목록에 넣었어요."

VESSEL_OFF_REPLY = "{name} 선박을 감시 목록에서 뺐어요."

VESSEL_OFF_NO_MMSI = "그 배의 선박 번호를 확인하지 못해 목록에서 뺄 수 없어요. 감시 화물 화면에서 직접 꺼 주세요."

VESSEL_DEFAULT_ERROR = "배 지켜보기를 처리하지 못했어요. 잠시 뒤 다시 시도해 주세요."

KAKAO_SENT = "카카오톡으로 지금 상태를 보냈어요."

KAKAO_COOLDOWN_REPLY = "방금 보내 드렸어요. 5분 뒤에 다시 보낼 수 있어요."

KAKAO_NOT_LINKED = "설정에서 카카오톡을 연결하면 보내 드릴 수 있어요."

KAKAO_NEED_LOGIN = "로그인하고 카카오톡을 연결하면 보내 드릴 수 있어요."

KAKAO_NO_CARGO = "보낼 화물이 없어요. 먼저 B/L 번호로 화물을 조회해 주세요."

KAKAO_ONE_AT_A_TIME = "한 번에 한 화물만 보낼 수 있어요. 하나씩 말씀해 주세요."

KAKAO_NOT_READY = "이 화물의 상태를 아직 저장하는 중이에요. 잠시 뒤에 다시 말씀해 주세요."

KAKAO_NO_VERDICT = "아직 판정된 상태가 없어서 보낼 수 없어요. 먼저 화물을 조회해 주세요."

KAKAO_FAIL_REPLY = {
    "relink": "카카오톡 연결이 끊어졌어요. 설정에서 다시 연결해 주세요.",
    "no_consent": "카카오톡 메시지 보내기에 동의가 필요해요. 설정에서 다시 연결해 주세요.",
}

KAKAO_FAILED = "카카오톡으로 보내지 못했어요. 잠시 뒤 다시 말씀해 주세요."

KAKAO_HOW = "지금 상태를 받으려면 \"카톡으로 보내 줘\"처럼 말씀해 주세요."

UNKNOWN_BL_WORD = "해당 B/L"  # 번호표에 없는 토큰(모델이 지어낸 [BL9] 등)을 바꿀 말
