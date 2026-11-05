"""에이전트 루프가 부르는 도메인 도구 (계획 3c, 설계 7절·6.3).

하지 않는 일: 루프·한도·승인 판단(graph/agent.py), 답 쓰기(graph/main.py의 write).
[주의] 도구는 가린 토큰만 받고 가린 토큰만 돌려준다. 실제 번호는 mask_map으로 조회할 때만 꺼내고,
       결과 글과 공책에는 토큰을 쓴다. 도구 결과(ToolMessage)는 모델이 다음 일을 고를 요약이고,
       근거 본문·계산 값은 공책 칸(evidence, calc)에 넣어 작성자·검증자가 거기서 읽는다.
[왜] 도구 설명(docstring)은 모델이 읽는 프롬프트라 prompts/*.md처럼 영어로 쓴다.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import date
from typing import Annotated

import httpx
import psycopg
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from marvia.graph.answer import cargo_lines
from marvia.graph.identify import identify_number
from marvia.identify.mask import LABELS, mask_text
from marvia.identify.parse import read_numbers
from marvia.llm import LLMFailed
from marvia.rag.models import Evidence
from marvia.tools.deadlines import import_deadlines, kst_date
from marvia.tools.reimport import ItemFacts, reimport_check
from marvia.tools.rules import load_rules

# 가린 토큰 모양: [BL1], [CARGO2], [NUM3]. [왜] 이름표는 identify.mask의 것을 그대로 쓴다
TOKEN = re.compile(r"\[(?:" + "|".join(LABELS) + r")\d+\]")


def error_name(error: Exception) -> str:
    """실패 기록에 남길 이름. 오류 글은 넣지 않는다(접속 주소나 요청 글이 섞일 수 있다)."""
    # [왜] LLMFailed는 이미 오류 종류 이름(과 상태 코드)만 담고 있다 (llm.structured)
    return str(error) if isinstance(error, LLMFailed) else type(error).__name__


def _reply(runtime: ToolRuntime, text: str, **update) -> Command:
    """모델에게 돌려줄 결과 글(ToolMessage)과 공책에 쓸 칸을 함께 돌려준다."""
    # [왜] 도구가 공책 칸을 바꾸려면 Command(update=...)를 돌려준다. ToolMessage의 tool_call_id가
    #      모델이 부른 호출 id와 같아야 모델이 어느 호출의 결과인지 안다
    message = ToolMessage(text, tool_call_id=runtime.tool_call_id)
    return Command(update={**update, "messages": [message]})


def cargo_deadlines(cargos: list[dict], today: date) -> list[dict]:
    """화물마다 지금 단계로 법정 기한을 센다. 단계 시각이 없는 화물은 건너뛴다."""
    deadlines = []
    for cargo in cargos:
        facts = cargo["facts"]
        if not facts or not facts.get("stage_at"):
            continue
        # [주의] 단계 시각은 한국 날짜로 바꿔 센다 (화물 줄 cargo_lines·검증자와 같은 kst_date)
        stage_on = kst_date(facts["stage_at"])
        deadlines += [
            {"cargo": cargo["token"], **deadline.model_dump(mode="json")}
            for deadline in import_deadlines(facts["stage"], stage_on, today)
        ]
    return deadlines


def flag_labels() -> str:
    """재수입 사유 이름표와 뜻을 한 줄씩 (계획자 길 프롬프트와 check_reimport 설명이 같은 글을 쓴다)."""
    return "\n".join(f"- {flag}: {item}" for flag, item in load_rules("reimport")["forced"].items())


def search_calls(rewrites: int) -> int:
    """검색 한 번이 고쳐 쓰기 rewrites번으로 끝났을 때 RAG 안에서 부른 LLM 호출 수."""
    # [왜] 질의 분석 1 + 채점 (고쳐 쓰기 + 1) + 고쳐 쓰기 = 2 + 2 × 고쳐 쓰기. 이 셈은 여기 한 곳에만 둔다
    return 2 + 2 * rewrites


def worst_search_calls(rewrites: int | None = None) -> int:
    """검색 한 번이 RAG 안에서 부를 수 있는 LLM 호출의 최대. rewrites가 없으면 rag.yaml 값(계획자 길)."""
    return search_calls(load_rules("rag")["loop"]["max_rewrites"] if rewrites is None else rewrites)


class Choice(BaseModel):
    """선택지 하나."""

    label: str = Field(description="Short Korean label for the option")
    description: str = Field(description="One Korean sentence on what happens if the user picks it")


def make_tools(
    rag_graph, today: Callable[[], date], provision: Callable[[str, date], list[Evidence]] | None = None
) -> list:
    """에이전트 루프에 줄 도구 목록을 만든다. rag_graph는 계획 2의 RAG 서브그래프(컴파일한 것).

    provision은 조문 이름표를 코퍼스 단위로 바꾸는 직접 조회다. 주면 get_provision 도구가 생긴다.
    """
    max_llm_calls = load_rules("agent")["loop"]["max_llm_calls"]
    # [왜] 에이전트 길의 RAG는 고쳐 쓰기를 agent.yaml 값으로 줄여 만든다(main.py). 최악도 같은 값으로 센다
    worst_search = worst_search_calls(load_rules("agent")["loop"]["rag_rewrites"])
    max_searches = load_rules("agent")["loop"]["max_searches"]

    @tool
    def search_law(query: str, runtime: ToolRuntime) -> Command:
        """Search the Korean statutes and notices for provisions. query: one Korean sentence in formal
        legal terms. Never put a cargo token in it.
        """
        query = query.strip()
        if query in runtime.state.get("searched", []):
            # [왜] 같은 질의를 다시 찾으면 같은 결과에 돈만 든다 (11-06 손 시험: 검색 네 번 반복)
            return _reply(runtime, "이미 찾은 질의예요. 앞의 결과를 쓰거나 다른 조문을 찾으세요.")
        # [왜] 한도는 호출이 일어나는 곳에서 지킨다.
        #      이 단계의 search_law 호출 수는 마지막 모델 메시지에서 센다. 한도에 막힌 호출도 거기 들어 있어
        #      세는 값이 실제보다 크거나 같다(안전 쪽). 병렬 검색은 전부 통과하거나 전부 거절된다
        last_ai = next(m for m in reversed(runtime.state["messages"]) if m.type == "ai")
        searches = sum(call["name"] == "search_law" for call in last_ai.tool_calls)
        if runtime.state.get("llm_calls", 0) + worst_search * searches > max_llm_calls:
            return _reply(runtime, "LLM 호출 한도가 가까워 더 찾지 않아요. 지금까지 찾은 것으로 끝내세요.")
        # [왜] 라이브러리 미들웨어의 횟수는 질문(interrupt)으로 멈췄다 이어 가면 다시 0부터 센다.
        #      searched는 공책에 남으므로 여기서도 센다. 미들웨어는 그대로 둔다 (이중 안전)
        if len(runtime.state.get("searched", [])) + searches > max_searches:
            return _reply(
                runtime, "이번 차례에 찾을 수 있는 횟수를 다 썼어요. 지금까지 찾은 것으로 끝내세요."
            )
        try:
            out = rag_graph.invoke({"question": query, "as_of": today()})
        except (httpx.HTTPError, psycopg.Error, LLMFailed) as error:
            # [왜] 검색 실패는 차례를 멈추지 않는다. 기록만 하고 모델이 다음 길을 고른다 (설계 결정 4의 ①)
            # [왜] RAG는 어느 단계에서든 실패할 수 있다. 실패 지점을 모르니 최악의 호출 수를 센다
            #      (상한을 넘지 않게)
            name = error_name(error)
            failed = [{"tool": "search_law", "message": name}]
            return _reply(
                runtime, f"검색 실패: {name}", failed_tools=failed, searched=[query], llm_calls=worst_search
            )
        found = out.get("evidence", [])
        missing = "" if out.get("sufficient") else out.get("missing", "")
        # [왜] 모델에게는 unit_id와 제목만 준다. 무엇을 찾았는지만 알면 된다.
        #      본문은 작성자가 evidence 칸에서 읽는다
        lines = [f"[{e['unit_id']}] {e['heading']}" for e in found] or ["찾은 조문이 없어요."]
        if missing:
            lines.append(f"빠진 근거: {missing}")
        return _reply(
            runtime,
            "\n".join(lines),
            evidence=found,
            gaps=[missing] if missing else [],  # [왜] 빈 문장은 남기지 않는다
            searched=[query],
            llm_calls=search_calls(out.get("rewrites", 0)),
        )

    @tool
    def get_provision(label: str, runtime: ToolRuntime) -> Command:
        """Fetch the provision a basis label names, e.g. "관세법 제241조제3항", straight from the
        indexed statutes (no search, no LLM call). Use it for the basis labels of calc_deadlines and
        check_reimport instead of search_law. Labels that are not articles (annexes) are not found.
        """
        assert provision is not None
        try:
            found = provision(label, today())
        except psycopg.Error as error:
            name = error_name(error)
            return _reply(
                runtime, f"조회 실패: {name}", failed_tools=[{"tool": "get_provision", "message": name}]
            )
        if not found:
            return _reply(runtime, f"찾지 못했어요: {label}. 이 이름표는 조문이 아니거나 코퍼스에 없어요.")
        # [왜] 모델에게는 unit_id와 제목만 준다. 본문은 작성자가 evidence 칸에서 읽는다 (search_law와 같다)
        lines = [f"[{e.unit_id}] {e.heading}" for e in found]
        return _reply(runtime, "\n".join(lines), evidence=[e.model_dump(mode="json") for e in found])

    @tool
    def calc_deadlines(runtime: ToolRuntime) -> Command:
        """Compute the legal deadlines (import declaration, duty payment, late-declaration surcharge) for
        the cargo lines. Use it for "by when" questions about the user's cargo. Dates come only from
        this tool.
        """
        deadlines = cargo_deadlines(runtime.state.get("cargos", []), today())
        text = json.dumps(deadlines, ensure_ascii=False) if deadlines else "기한을 셀 화물 단계가 없어요."
        return _reply(runtime, text, calc={"deadlines": deadlines})

    # [왜] facts.flags에는 rules/reimport.yaml의 이름표만 들어간다. 모델이 이름표를 알아야 하므로
    #      설명에 붙인다 (계획자 길의 extract_item 프롬프트와 같은 글)
    reimport_description = (
        "Check whether a re-imported food item meets the document-inspection conditions instead of a "
        "precise inspection. Fill facts only with what the user said; unknown fields stay 모름 or empty. "
        f"facts.flags takes only these labels:\n{flag_labels()}"
    )

    @tool(description=reimport_description)
    def check_reimport(facts: ItemFacts, runtime: ToolRuntime) -> Command:
        result = reimport_check(facts, today())
        return _reply(
            runtime,
            result.model_dump_json(),
            calc={"reimport": result.model_dump(mode="json")},
            item=facts.model_dump(mode="json"),
        )

    @tool
    def lookup_cargo(tokens: list[str], runtime: ToolRuntime) -> Command:
        """Look up the customs status of cargo tokens such as [BL1] (for example a number the user gave in
        an answer). Returns one line per cargo.
        """
        mask_map = dict(runtime.state.get("mask_map", {}))
        known = [token for token in tokens if token in mask_map]
        # [왜] 이미 사실을 얻은 화물은 다시 조회하지 않고 지금 줄을 돌려준다 (같은 조회에 돈과 시간이 든다)
        have = {c["token"]: c for c in runtime.state.get("cargos", []) if c["facts"]}
        # [주의] 실제 번호는 여기서만 꺼낸다. 결과 줄(cargo_lines)은 토큰으로 쓴다
        cargos = [have.get(token) or identify_number(mask_map[token], mask_map) for token in known]
        lines = cargo_lines(cargos) + [
            f"{token}: 모르는 토큰이에요" for token in tokens if token not in mask_map
        ]
        return _reply(runtime, "\n".join(lines), cargos=cargos)

    @tool
    def ask_user(
        question: str,
        # [왜] 2~3개는 설계 6.3의 고정값이다. 어노테이션은 import 때 평가돼 yaml을 읽을 수 없어
        #      숫자로 둔다
        options: Annotated[list[Choice], Field(min_length=2, max_length=3)],
        runtime: ToolRuntime,
    ) -> Command:
        """Ask the user one question with 2-3 options, the recommended option first. Use it only when you
        cannot go on without the answer. Call it alone, with no other tool in the same turn.
        """
        payload = {
            "kind": "choice",
            "question": question,
            "options": [option.model_dump() for option in options],
            "recommended": 0,  # [왜] 권장안을 맨 앞에 둔다 (설계 결정 4의 ②)
        }
        # [주의] 재개하면 이 도구가 처음부터 다시 돈다. 그래서 interrupt 앞에는 바깥 일을 두지 않는다
        reply = interrupt(payload) or {}
        # [왜] 화면에서 온 값이라 dict가 아니면 답이 없는 것으로 본다 (문자열 응답은 AttributeError를 낸다)
        reply = reply if isinstance(reply, dict) else {}
        # [왜] 공백만 쓴 답은 답이 없는 것으로 본다
        custom = str(reply.get("custom") or "").strip()
        if custom:
            # [주의] 직접 쓴 답에 실제 번호가 있을 수 있다. 이번 차례 표에 이어 가린 뒤에만 모델에게 준다
            masked, mask_map = mask_text(custom, runtime.state.get("mask_map", {}))
            return _reply(
                runtime,
                f"사용자 답(직접 입력): {masked}",
                mask_map=mask_map,
                clarifications=[f"{question} → {masked}"],
            )
        selected = reply.get("selected")
        # [왜] 화면에서 온 값이라 범위를 확인한다. 범위 밖과 True(1이 아니다)는 답이 없는 것으로 본다
        if isinstance(selected, int) and not isinstance(selected, bool) and 0 <= selected < len(options):
            label = options[selected].label
            return _reply(runtime, f"사용자 답: {label}", clarifications=[f"{question} → {label}"])
        # [왜] 답이 없거나 시간이 지나면 권장안으로 진행하고 가정으로 남긴다 (설계 결정 4의 ②)
        label = options[0].label
        assumption = f"'{question}'에 답이 없어 권장안 '{label}'으로 진행했어요."
        return _reply(
            runtime,
            f"답이 없어 권장안으로 진행해요: {label}",
            assumptions=[assumption],
            clarifications=[f"{question} → (답 없음, 권장안 '{label}'으로 진행)"],
        )

    @tool
    def save_item_card(name: str, runtime: ToolRuntime) -> Command:
        """Save the item facts checked with check_reimport as an item card for the next import. Needs the
        user's approval. name: a short Korean item name without any cargo number.
        """
        item = runtime.state.get("item")
        if not item:
            return _reply(runtime, "저장할 품목 사실이 없어요. check_reimport를 먼저 부르세요.")
        # [주의] 장기 기억에는 화물 번호(실제 번호나 토큰)를 넣지 않는다 (설계 8절 저장 기준)
        if TOKEN.search(name) or read_numbers(name):
            return _reply(runtime, "품목 이름에 화물 번호를 넣을 수 없어요. 품목 이름만 쓰세요.")
        name = name.strip()
        memory = load_rules("agent")["memory"]
        max_name = memory["max_item_name"]
        # [주의] 장기 기억에는 문장처럼 생긴 글을 넣지 않는다 (설계 8절 저장 기준)
        if len(name) > max_name or any(mark in name for mark in memory["forbidden_marks"]):
            return _reply(
                runtime, f"품목 이름은 {max_name}자 안의 짧은 이름만 쓸 수 있어요. 문장은 저장하지 않아요."
            )
        if runtime.store is None:
            return _reply(runtime, "장기 기억 저장소가 연결되지 않았어요.")
        # [왜] 사용자마다 칸을 나눈다. 첫 칸을 사용자로 두어야 남의 기억을 읽지 않는다 (설계 8절)
        user = runtime.config.get("configurable", {}).get("user_id", "local")
        runtime.store.put(("users", user, "items"), name, {"name": name, "facts": item})
        return _reply(runtime, f"품목 카드 '{name}'을 저장했어요.")

    # [왜] return_direct: 이 도구를 부르면 모델을 다시 부르지 않고 루프를 끝낸다. 거절 글은 코드가 쓴다
    @tool(return_direct=True)
    def decline(reason: str, runtime: ToolRuntime) -> Command:
        """Use when the question is not about import cargo, customs procedures, or imported-food rules.
        reason: one short Korean sentence.
        """
        return _reply(runtime, f"도메인 밖 질문: {reason}", out_of_scope=True)

    tools = [search_law, calc_deadlines, check_reimport, lookup_cargo, ask_user, save_item_card, decline]
    return tools + [get_provision] if provision else tools
