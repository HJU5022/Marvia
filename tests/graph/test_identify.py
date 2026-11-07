from langchain_core.runnables import RunnableConfig

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
    seen = spy(monkeypatch)
    out = build_identify_graph(lambda config: ["DEMO0002", "DEMO0003"]).invoke(
        {"text": "TESU0000013 어디야?"}
    )
    cargo = out["cargos"][0]
    assert (cargo["token"], cargo["confidence"], cargo["candidates"]) == (
        "[CNTR1]",
        "candidate",
        ["DEMO0002", "DEMO0003"],
    )
    assert cargo["error"]["code"] == "container_many" and cargo["facts"] is None
    assert seen == ["DEMO0002", "DEMO0003"]  # 감시 목록 화물만 다시 조회했다


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
