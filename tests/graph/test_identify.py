from marvia.graph.identify import build_identify_graph


def run(text: str) -> dict:
    return build_identify_graph().invoke({"text": text})


def test_two_numbers_found():
    out = run("DEMO0001DEMO0002 어디야?")
    assert out["masked_text"] == "[BL1][BL2] 어디야?"
    assert [c["token"] for c in out["cargos"]] == ["[BL1]", "[BL2]"]
    assert [c["facts"]["stage"] for c in out["cargos"]] == ["반입신고", "수입신고"]
    assert out["question"] is None


def test_ambiguous_returns_question_and_stops():
    out = run("MOCK12345678TEST87654321")
    assert out["question"]["alternatives"][0] == ["MOCK12345678", "TEST87654321"]
    assert out.get("cargos", []) == []


def test_unknown_number_kept_with_error():
    out = run("NOPE12345678")
    cargo = out["cargos"][0]
    assert cargo["confidence"] == "unknown"
    assert cargo["error"]["code"] == "not_found"


def test_mask_table_continues_from_the_previous_turn():
    out = build_identify_graph().invoke(
        {"text": "DEMO0002하고 DEMO0001 둘 다 봐 줘", "mask_map": {"[BL1]": "DEMO0001"}}
    )
    assert out["masked_text"] == "[BL2]하고 [BL1] 둘 다 봐 줘"
    assert out["mask_map"] == {"[BL1]": "DEMO0001", "[BL2]": "DEMO0002"}
    assert [c["token"] for c in out["cargos"]] == ["[BL2]", "[BL1]"]
