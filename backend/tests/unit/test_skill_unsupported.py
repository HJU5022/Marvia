"""V14 보강: Skill 답의 핵심 낱말이 Skill 원문에 없으면 Skill 근거 답이 아니다 (validate.skill_unsupported_terms).
Skill 원문은 실제 skills/ 폴더(llm.CHAT_AGENT_SKILLS)를 쓴다. LLM 호출은 없다 (비용 0).
근거: "B/L도 없고 포워더는 연락이 안 되는데" 답의 "화물 인도증"은 Skill 어디에도 없는데 꼬리표 없이 Skill 답으로 나갔다."""
import pytest

from backend.app.services import llm
from backend.app.services.judge import validate

SKILLS = llm.skills_reference(llm.CHAT_AGENT_SKILLS)

# (a) 실제 사례: 모델 지식을 Skill 답처럼 낸 것. 걸려야 한다
CASE_Q = "B/L도 없고 포워더는 연락이 안 되는데 뭘 할 수 있을까?"
CASE_A = ("포워더와 연락이 닿지 않을 때는 포워더가 발행한 선하증권 사본이나 화물 인도증을 찾아 그 안에 적힌 선박 이름과 항차, 선사 이름을 확인한 뒤 "
          "선사 고객센터나 부산항만공사 안내를 통해 화물의 도착 일정과 양륙 터미널을 직접 조회할 수 있습니다.")

# (b) 실제 Skill 문장을 공손하게 바꿔 쓴 답. 걸리면 안 된다
GENUINE = [
    "오래된 위치는 위치가 없는 것과 다릅니다. 마지막 수신 위치로 읽으며, 위치가 아예 없을 때만 판정을 보류합니다.",
    "해수부 입항 신고를 AIS 목적지보다 더 믿습니다. 입항 신고는 선사가 제출하는 공식 서류이고, AIS 목적지는 선원이 손으로 넣는 값이라 틀릴 때가 많기 때문입니다.",
    "항해상태는 선원이 손으로 넣는 값이라 속도나 위치와 어긋날 수 있습니다. 그래서 항해상태 대신 속도와 위치로 판단합니다.",
    "반출 단계는 통관이 끝나 화물이 창고에서 나간 상태를 뜻합니다. 배송 일정은 운송사에 확인해 주세요.",
    "주의 등급은 아직 여유는 있지만 확인할 것이 있다는 뜻입니다. 긴급 등급은 지금 조치하지 않으면 판매 예정일을 놓친다는 뜻입니다.",
    "부산항 화물이 아니면 이 서비스는 판정하지 않습니다. 이 서비스는 부산항에 내리는 화물만 확인합니다.",
    "같은 이름의 배가 여럿이면 어느 배인지 확정하지 못합니다. 포워더 도착 통지서의 배 이름과 항차, 입항 예정일을 알려 주시면 확인할 수 있습니다.",
    "해수부 입항 신고는 보통 도착 1주일 전쯤 들어옵니다. 그 전에 신고가 없으면 도착 1주일 전쯤 다시 조회해 보세요.",
]


# (c) Skill 어디에도 없는 실무 조언(보험·신용장·은행). 걸려야 한다
OUTSIDE_A = "포워더와 연락이 안 되면 무역보험공사에 클레임을 접수하고 신용장 개설 은행에 지급 정지를 요청하세요."


def test_real_case_terms_after_import_basics():
    terms = validate.skill_unsupported_terms(CASE_A, SKILLS, CASE_Q)
    # Kiwi는 "인도증"을 인도+증으로 나눈다. 1글자 "증"은 세지 않고, "인도"는 일반 용어 "인도지시서"의 조각이라 허용된다.
    # import-basics Skill(B/L은 선박회사가 발행, 관세청 고객지원센터 125)이 들어온 뒤로 발행·고객·센터는 Skill 원문에 있다.
    # 남는 것은 "사본" 하나라 기준(UNSUPPORTED_MIN) 아래다
    assert terms == ["사본"]


def test_answer_outside_skills_is_flagged():
    terms = validate.skill_unsupported_terms(OUTSIDE_A, SKILLS, CASE_Q)
    assert {"보험", "신용장", "은행"} <= set(terms) and len(terms) >= validate.UNSUPPORTED_MIN
    assert validate.skill_unsupported(OUTSIDE_A, SKILLS, CASE_Q)


@pytest.mark.parametrize("reply", GENUINE)
def test_genuine_skill_answers_pass(reply):
    assert validate.skill_unsupported_terms(reply, SKILLS) == []
    assert not validate.skill_unsupported(reply, SKILLS)


def test_one_stray_word_is_tolerated():
    # 낱말 하나만 Skill에 없으면 (말투·표현 차이일 수 있어) Skill 답으로 둔다
    reply = "오래된 위치는 위치가 없는 것과 다릅니다. 마지막 수신 위치로 읽으며 인도증 같은 것은 보지 않습니다."
    assert len(validate.skill_unsupported_terms(reply, SKILLS)) == 1
    assert not validate.skill_unsupported(reply, SKILLS)


def test_words_from_the_question_are_not_counted():
    # 사용자가 쓴 낱말을 되짚은 것은 모델 지식이 아니다
    reply = "야적료 체화료 감면은 Skill 문서에 없습니다."
    assert validate.skill_unsupported(reply, SKILLS)
    assert not validate.skill_unsupported(reply, SKILLS, "야적료 체화료 감면이 어때?")


# (c) 배포 실측: Skill 문장을 활용형으로 풀어 쓴 답이 "Skill에 없는 낱말"로 걸려 일반 설명으로 낮춰졌다.
# 걸린 낱말은 입력하·고치지·다르게(7번), 등급일·안내된·상태이고·사항(13번), 서쪽의·이용하(10번)처럼 뿌리는 Skill에 있는 말이다.
# 명사만 보는 방식(Kiwi)으로 바꾼 뒤에는 run2_10(남아·아실 같은 활용형)도 같이 통과해야 한다.
# 원본: 위키 프로젝트/Marvia-근거/skill_baseline_15q_20261006_1005.txt, kiwi_trial_20261006/cases.json
INFLECTED = [
    ("목적지가 BUSAN이 아니라 이상한 글자로 나와. 딴 데 가는 거야?",
     "AIS의 목적지나 ETA는 선원이 손으로 직접 입력하는 값이라 항구를 떠난 뒤 고치지 않아 실제 목적지와 다르게 남는 경우가 종종 있습니다."),
    ("신항이랑 북항은 뭐가 달라? 내 짐은 어디로 와?",
     "신항은 부산 서쪽의 가덕도와 진해 쪽에 위치한 대형 컨테이너선 대부분이 이용하는 항만이며, 북항은 부산 도심 쪽에 위치한 기존 항만입니다. "
     "화물이 어느 곳으로 들어오는지는 선사의 입항 정보나 B/L 번호로 화물을 조회하시면 확인하실 수 있습니다."),
    ("watch랑 act는 뭐가 달라? watch면 뭘 해야 돼?",
     "순항 등급은 판매 예정일 전에 할 일이 없는 상태이고, 주의 등급은 아직 여유는 있지만 확인할 것이 있는 상태이며, "
     "긴급 등급은 지금 조치하지 않으면 판매 예정일을 놓치는 상태입니다. 주의 등급일 때는 안내된 신호나 확인할 사항을 점검하시면 됩니다."),
    # run2_10: "올지"·"아실" 같은 활용형이 걸리던 답
    ("신항이랑 북항은 뭐가 달라? 내 짐은 어디로 와?",
     "신항은 부산 서쪽의 대형 컨테이너 항만이고, 북항은 도심 쪽 기존 항만입니다. 화물이 어디로 올지는 선하증권 번호로 조회하면 아실 수 있습니다."),
]


@pytest.mark.parametrize("question,reply", INFLECTED)
def test_inflected_skill_answers_pass(question, reply):
    assert not validate.skill_unsupported(reply, SKILLS, question)


def test_grade_names_transliterated_are_flagged():
    # run2_13: 화면 이름(주의·긴급) 대신 영문 등급 이름을 소리 나는 대로 옮긴 답(와치·액트)은 Skill에 없는 명사라 걸려야 한다
    question = "watch랑 act는 뭐가 달라? watch면 뭘 해야 돼?"
    reply = ("와치 등급은 아직 여유가 있지만 확인할 점이 있다는 뜻이며, 액트 등급은 지금 조치하지 않으면 판매 예정일을 넘길 수 있다는 뜻입니다. "
             "와치 등급일 때는 안내된 신호나 일정을 살펴보고 필요한 부분을 점검하시면 됩니다.")
    terms = validate.skill_unsupported_terms(reply, SKILLS, question)
    assert "와치" in terms and "액트" in terms
    assert validate.skill_unsupported(reply, SKILLS, question)


def test_conjugations_are_not_counted_as_missing_words():
    # 동사·형용사 활용형(남아·있거·올지·아실·넘길·살펴보고·고치지·입력하)은 명사가 아니라서 세지 않는다
    reply = "값이 그대로 남아 있거나 어디로 올지 아실 수 있고, 날짜를 넘길 때는 살펴보고 고치지 않고 입력하세요."
    assert validate.skill_unsupported_terms(reply, "값 날짜 입력") == []


def test_noun_with_skill_root_is_still_flagged():
    # 뿌리 낱말이 Skill에 있어도 명사 끝(료·증 등)이 붙은 새 낱말은 봐 주지 않는다 ("야적료"는 "야적"이 있어도 센다)
    terms = validate.skill_unsupported_terms("야적료와 인도증을 챙기세요.", SKILLS)
    assert "야적료" in terms


def test_general_terms_are_not_counted():
    # 3층(일반 설명)도 허용하는 일반 해운 용어는 Skill에 없어도 센 것이 아니다
    reply = "수하인은 마스터 하우스 선하증권 도착통지서 인도지시서를 포워더에게 받습니다."
    assert validate.skill_unsupported_terms(reply, "") == []
