from marvia.graph.answer import cargo_lines, final_answer, partial_answer
from marvia.tools.rules import load_rules

DRAFT = {
    "answer": "2026-11-26까지 수입신고해야 해요.",
    "citations": ["L001556@20261002#제241조.3항"],
    "next_options": ["관세사에게 수입신고를 맡기기"],
    "forwarder_message": "",
}


def test_cargo_lines_use_tokens(cargos):
    assert cargo_lines(cargos) == [
        "[BL1]: 반입신고 (부산) 2026-10-27",
        "[BL2]: 조회하지 못했어요 (재생 데이터에 없는 번호입니다, not_found)",
    ]


def test_final_answer_parts_in_order(cargos, evidence):
    text = final_answer(DRAFT, cargos, evidence)
    # [왜] 코드가 쓰는 머리(읽은 건수·화물 상태)가 먼저, 작성자 답, 선택지, 근거 순서
    order = ["2건으로 읽었어요.", "[BL1]: 반입신고", DRAFT["answer"], "- 관세사에게", "근거:"]
    assert [text.index(part) for part in order] == sorted(text.index(part) for part in order)
    assert "관세법 > 제9장 통관 > 제241조(수출ㆍ수입 또는 반송의 신고)" in text
    assert "https://www.law.go.kr/test" in text and "L001556@20261002#제241조.3항" in text
    assert "B/L" not in text  # 포워더 메시지가 없으면 안내 줄도 없다


def test_final_answer_forwarder_block(evidence):
    draft = DRAFT | {"forwarder_message": "이번 고추 화물의 운송 서류 번호를 알려 주세요.", "citations": []}
    text = final_answer(draft, [], evidence)
    # 코드가 쓰는 안내 줄이 B/L과 화물관리번호를 말하고, 그 아래에 작성자의 메시지가 온다
    assert "B/L" in text and "화물관리번호" in text
    assert text.index("화물관리번호") < text.index("이번 고추 화물")


def test_partial_answer(cargos, calc, evidence):
    calc = calc | {"reimport": {"verdict": "사실 부족", "basis": ["시행규칙 별표 9 제2호가목7)"]}}
    failed = [{"tool": "search_law", "message": "DB 연결 실패"}]
    text = partial_answer(cargos, calc, evidence, ["재수입 조건 조문"], failed)
    assert "끝까지 확인하지 못했어요" in text
    assert "[BL1] 수입신고 기한: 2026-11-26까지 (관세법 제241조제3항)" in text
    assert "재수입 검사: 사실 부족 (시행규칙 별표 9 제2호가목7))" in text
    assert "관세법 > 제9장 통관 > 제241조(수출ㆍ수입 또는 반송의 신고)" in text
    assert "- 재수입 조건 조문" in text and "- search_law: DB 연결 실패" in text
    assert all(option in text for option in load_rules("agent")["finish"]["next_options"])
