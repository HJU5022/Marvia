from langchain_core.runnables import RunnableConfig

from marvia.graph.identify import build_identify_graph, build_lookup_graph
from marvia.tools.rules import load_rules


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


def test_one_failed_lookup_does_not_stop_the_others(monkeypatch):
    from marvia.graph import identify

    real = identify.lookup_cargo

    def flaky(number):
        if number == "DEMO0002":
            raise OSError("읽기 오류")
        return real(number)

    monkeypatch.setattr(identify, "lookup_cargo", flaky)
    out = run("DEMO0001DEMO0002 어디야?")
    assert [c["facts"] is not None for c in out["cargos"]] == [True, False]
    assert out["cargos"][1]["error"] == {"code": "lookup_failed", "message": "OSError", "retryable": True}


def spy(monkeypatch) -> list[str]:
    """식별이 조회 함수(lookup_cargo)에 넘긴 번호를 모은다."""
    from marvia.graph import identify

    seen: list[str] = []
    real = identify.lookup_cargo

    def lookup(number):
        seen.append(number)
        return real(number)

    monkeypatch.setattr(identify, "lookup_cargo", lookup)
    return seen


def test_a_container_is_found_among_cargo_this_conversation_already_looked_up(monkeypatch):
    # [왜] UNI-PASS는 컨테이너 번호로 찾지 못한다. 지난 차례에 조회한 화물의 사실에서 찾는다 (계획 6a)
    first = run("DEMO0001 어디야?")
    seen = spy(monkeypatch)
    out = build_identify_graph().invoke(
        {
            "text": "컨테이너 DEMU1234560 어디쯤이에요?",
            "mask_map": first["mask_map"],
            "cargos": first["cargos"],
        }
    )
    assert out["masked_text"] == "컨테이너 [CNTR1] 어디쯤이에요?"
    cargo = out["cargos"][0]
    assert (cargo["token"], cargo["kind"], cargo["bl_no"], cargo["confidence"]) == (
        "[CNTR1]",
        "container",
        "DEMO0001",
        "confirmed",
    )
    assert cargo["facts"]["stage"] == "반입신고"
    assert seen == []  # 컨테이너 번호로는 아무것도 조회하지 않았다


def test_a_bl_in_the_same_message_carries_the_container(monkeypatch):
    seen = spy(monkeypatch)
    out = run("DEMO0001 컨테이너 DEMU1234560 둘 다 봐 줘")
    assert [(c["token"], c["facts"]["stage"]) for c in out["cargos"]] == [
        ("[BL1]", "반입신고"),
        ("[CNTR1]", "반입신고"),
    ]
    assert seen == ["DEMO0001"]


def test_a_container_on_two_watched_cargos_is_left_as_candidates(monkeypatch):
    # [왜] 한 컨테이너에 여러 화물(LCL)이 실릴 수 있다. 하나를 골라 답하지 않는다
    # [왜] 후보 줄은 조회 서브그래프가 만든다. 식별은 선택지를 띄울 때 그 줄을 화물 칸에서 뺀다 (계획 6c)
    seen = spy(monkeypatch)
    out = build_lookup_graph(lambda config: ["DEMO0002", "DEMO0003"]).invoke({"numbers": ["TESU0000013"]})
    cargo = out["cargos"][0]
    assert (cargo["token"], cargo["confidence"], cargo["candidates"]) == (
        "[CNTR1]",
        "candidate",
        ["DEMO0002", "DEMO0003"],
    )
    assert cargo["error"]["code"] == "container_many" and cargo["facts"] is None
    assert seen == ["DEMO0002", "DEMO0003"]  # 감시 목록 화물만 다시 조회했다


def test_the_same_number_on_two_plain_turns_is_looked_up_twice(monkeypatch):
    # [왜] 식별 서브그래프의 조회는 reuse=False다. 지난 사실을 다시 쓰면 통관 상태가 낡은 채 답한다 (계획 6c)
    seen = spy(monkeypatch)
    graph = build_identify_graph()
    first = graph.invoke({"text": "DEMO0001 어디야?"})
    graph.invoke({"text": "DEMO0001 지금은?", "cargos": first["cargos"], "mask_map": first["mask_map"]})
    assert seen.count("DEMO0001") == 2


def test_an_unknown_container_gets_the_fixed_line_without_any_lookup(monkeypatch):
    from marvia.tools.rules import load_rules

    seen = spy(monkeypatch)
    out = build_identify_graph(lambda config: []).invoke({"text": "NOPU1234560 어디야?"})
    assert out["cargos"][0]["error"] == {
        "code": "container_unknown",
        "message": load_rules("unipass")["messages"]["container_unknown"],
        "retryable": False,
    }
    assert seen == []


def test_live_mode_reads_no_watch_list_for_a_container(monkeypatch):
    # [왜] 실제 응답에는 컨테이너 칸이 없다. 감시 화물을 다시 조회해도 맞출 수 없다 (계획 6a 정정)
    from marvia.graph import identify
    from marvia.identify.models import ToolError
    from marvia.tools.rules import load_rules

    monkeypatch.setenv("MARVIA_UNIPASS_MODE", "live")
    seen: list[str] = []
    asked: list[RunnableConfig] = []

    def lookup(number: str) -> ToolError:
        seen.append(number)  # [주의] 실제 함수를 부르지 않는다
        return ToolError(code="not_found", message="", retryable=False)

    def watched(config: RunnableConfig) -> list[str]:
        asked.append(config)
        return ["DEMO0002", "DEMO0003"]

    monkeypatch.setattr(identify, "lookup_cargo", lookup)
    out = build_identify_graph(watched).invoke({"text": "TESU0000013 어디야?"})
    assert out["cargos"][0]["error"]["message"] == load_rules("unipass")["messages"]["container_unknown"]
    assert asked == [] and seen == []


def test_several_watched_cargos_on_one_container_give_a_choice_with_all_first():
    out = build_identify_graph(lambda config: ["DEMO0002", "DEMO0003"]).invoke(
        {"text": "TESU0000013 어디야?"}
    )
    question = out["question"]
    assert [o["label"] for o in question["options"]] == ["[BL1] + [BL2]", "[BL1]", "[BL2]"]
    assert question["recommended"] == 0
    assert question["alternatives"] == [["DEMO0002", "DEMO0003"], ["DEMO0002"], ["DEMO0003"]]
    # [왜] 화면에 보낼 칸(질문, 선택지)에는 토큰만 있다. 실제 번호는 alternatives에만 있다
    shown = str({key: question[key] for key in ("question", "options")})
    assert "TESU0000013" not in shown and "DEMO0002" not in shown
    assert out["numbers"] == []  # 고른 화물만 다시 조회한다


def test_a_single_match_asks_nothing():
    out = build_identify_graph(lambda config: ["DEMO0001"]).invoke({"text": "DEMU1234560 어디야?"})
    assert out["question"] is None and out["numbers"] == ["DEMU1234560"]


def test_a_container_shaped_number_with_a_wrong_check_digit_is_asked_before_any_lookup(monkeypatch):
    seen = spy(monkeypatch)
    out = run("DEMU1234565 어디야?")
    question = out["question"]
    assert question["question"].startswith("[BL1]은 컨테이너 번호 모양인데 확인 숫자가 맞지 않아요")
    assert question["alternatives"] == [["DEMU1234565"], []]
    assert out["masked_text"] == "[BL1] 어디야?" and out["numbers"] == []
    assert seen == []


def test_two_typos_are_asked_in_one_question(monkeypatch):
    seen = spy(monkeypatch)
    out = run("DEMU1234565, TESU0000012 어디야?")
    question = out["question"]
    assert question["alternatives"] == [["DEMU1234565", "TESU0000012"], []]
    assert question["question"].startswith("[BL1] + [BL2]은 컨테이너 번호 모양인데")
    shown = str(question["question"]) + str(question["options"])
    assert "DEMU1234565" not in shown and "TESU0000012" not in shown
    assert out["numbers"] == [] and seen == []


def test_a_typo_next_to_an_ambiguous_chunk_is_never_dropped():
    for text in ("MOCK12345678TEST87654321 DEMU1234565", "DEMU1234565 MOCK12345678TEST87654321"):
        out = run(text)
        assert out["question"]["alternatives"][0] == ["MOCK12345678", "TEST87654321"], text
        assert out["numbers"] == ["DEMU1234565"], (
            text
        )  # 다른 질문이 이기면 오타 번호는 권장안(B/L 조회)을 따른다


def test_live_mode_looks_up_no_earlier_cargo_for_a_container(monkeypatch):
    # [왜] 실제 모드는 이 대화의 화물도 다시 조회하지 않는다. 사실에 컨테이너가 없어 맞출 수 없다
    from marvia.graph import identify
    from marvia.identify.models import ToolError

    monkeypatch.setenv("MARVIA_UNIPASS_MODE", "live")
    seen: list[str] = []

    def lookup(number: str) -> ToolError:
        seen.append(number)  # [주의] 실제 함수를 부르지 않는다
        return ToolError(code="not_found", message="", retryable=False)

    monkeypatch.setattr(identify, "lookup_cargo", lookup)
    out = build_identify_graph(lambda config: []).invoke(
        {"text": "TESU0000013 어디야?", "mask_map": {"[BL1]": "DEMO0001"}}
    )
    assert out["cargos"][0]["error"]["code"] == "container_unknown"
    assert seen == []


def test_a_spaced_container_with_a_wrong_check_digit_is_asked_before_any_lookup(monkeypatch):
    seen = spy(monkeypatch)
    out = run("DEMU 123456 1 어디야?")
    question = out["question"]
    assert question["question"].startswith("[BL1]은 컨테이너 번호 모양인데 확인 숫자가 맞지 않아요")
    shown = str(question["question"]) + str(question["options"])
    assert "DEMU" not in shown and "123456" not in shown
    assert out["masked_text"] == "[BL1] 어디야?" and out["numbers"] == []
    assert seen == []


def test_question_and_choice_texts_come_from_the_rules():
    # [왜] 화면에 보이는 정한 글은 rules/identify.yaml에 둔다 (계획 6c). 글을 바꿀 때 이 파일만 고친다
    texts = load_rules("identify")["questions"]
    ambiguous = run("MOCK12345678TEST87654321")["question"]
    assert ambiguous["question"] == texts["ambiguous"]["question"].format(raw="MOCK12345678TEST87654321")
    assert ambiguous["options"][0]["description"] == texts["ambiguous"]["option"].format(count=2)
    typo = run("DEMU1234565 어디야?")["question"]
    assert typo["question"] == texts["typo"]["question"].format(tokens="[BL1]")
    assert typo["options"] == [
        {"label": "[BL1]", "description": texts["typo"]["as_bl"]},
        {"label": texts["typo"]["skip_label"], "description": texts["typo"]["skip"]},
    ]
    many = build_identify_graph(lambda config: ["DEMO0002", "DEMO0003"]).invoke(
        {"text": "TESU0000013 어디야?"}
    )
    assert many["question"]["question"] == texts["container"]["question"].format(token="[CNTR1]")
    assert [o["description"] for o in many["question"]["options"]] == [
        texts["container"]["all"].format(count=2),
        texts["container"]["one"],
        texts["container"]["one"],
    ]
