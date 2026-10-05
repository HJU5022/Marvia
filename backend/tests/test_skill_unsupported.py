"""V14 보강 (10-06): Skill 답의 핵심 낱말이 Skill 원문에 없으면 Skill 근거 답이 아니다 (validate.skill_unsupported_terms).
Skill 원문은 실제 skills/ 폴더(llm.CHAT_AGENT_SKILLS)를 쓴다. LLM 호출은 없다 (비용 0).
근거: 10-06 실측 "B/L도 없고 포워더는 연락이 안 되는데" 답의 "화물 인도증"은 Skill 어디에도 없는데 꼬리표 없이 Skill 답으로 나갔다."""
import pytest

from backend.app.services import llm, validate

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
    "지켜볼 것 등급은 아직 여유는 있지만 확인할 것이 있다는 뜻입니다. 지금 조치 등급은 지금 조치하지 않으면 판매 예정일을 놓친다는 뜻입니다.",
    "부산항 화물이 아니면 이 서비스는 판정하지 않습니다. 이 서비스는 부산항에 내리는 화물만 확인합니다.",
    "같은 이름의 배가 여럿이면 어느 배인지 확정하지 못합니다. 포워더 도착 통지서의 배 이름과 항차, 입항 예정일을 알려 주시면 확인할 수 있습니다.",
    "해수부 입항 신고는 보통 도착 1주일 전쯤 들어옵니다. 그 전에 신고가 없으면 도착 1주일 전쯤 다시 조회해 보세요.",
]


def test_real_case_is_flagged():
    terms = validate.skill_unsupported_terms(CASE_A, SKILLS, CASE_Q)
    assert "인도증" in terms and len(terms) >= validate.UNSUPPORTED_MIN
    assert validate.skill_unsupported(CASE_A, SKILLS, CASE_Q)


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


def test_general_terms_are_not_counted():
    # 3층(일반 설명)도 허용하는 일반 해운 용어는 Skill에 없어도 센 것이 아니다
    reply = "수하인은 마스터 하우스 선하증권 도착통지서 인도지시서를 포워더에게 받습니다."
    assert validate.skill_unsupported_terms(reply, "") == []
