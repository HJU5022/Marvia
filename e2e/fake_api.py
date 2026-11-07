"""화면 e2e용 가짜 API (계획 4b Task 9). 실제 모델·Voyage·DB 없이 화면 서버(marvia.server)를 띄운다.

질문 글로 각본을 고르는 가짜 모델, 가짜 RAG·조문 조회·작성자, 메모리 대화 기록으로 그래프를 만든다.
UNI-PASS는 재생 데이터(DEMO 번호)다. 로그인은 개발 로그인(MARVIA_AUTH=dev)만 쓴다.
[주의] 운영 이미지에는 이 파일이 들어가지 않는다(Dockerfile의 e2e 단계에만 복사한다). 바깥 호출 0건:
       Anthropic·Voyage 클라이언트를 만들지 않고, compose e2e 망은 바깥으로 나가지 못한다(internal).
실행(컨테이너 안): python e2e/fake_api.py
"""

from __future__ import annotations

import os
import time
from datetime import date
from typing import Any

import uvicorn
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from marvia.auth import verifier
from marvia.config import Settings
from marvia.graph.main import AgentDeps, build_main_graph
from marvia.graph.rag import RagDeps
from marvia.graph.schemas import Draft, Plan, Step
from marvia.rag.models import Evidence
from marvia.rag.schemas import Grade, QueryAnalysis, Rewrite
from marvia.server import build_app
from marvia.tools.reimport import ItemFacts

UNIT = Evidence(
    unit_id="L001556@20261002#제241조.3항",
    law_name="관세법",
    heading="관세법 > 제9장 통관 > 제241조(수출ㆍ수입 또는 반송의 신고)",
    effective=date(2026, 10, 2),
    source_url="https://www.law.go.kr/법령/관세법",
    text="제241조 ③ 물품을 보세창고에 반입한 자는 반입일부터 30일 이내에 신고해야 한다.",
    score=0.9,
)
TWO = [{"label": "부산", "description": "부산항 기준"}, {"label": "인천", "description": "인천항 기준"}]
# 질문 글에 든 낱말 → 모델이 차례로 낼 도구 호출 (각 줄이 모델 호출 한 번). 끝나면 빈 답으로 루프를 끝낸다
SCRIPTS: dict[str, list[tuple[str, dict]]] = {
    "수입신고": [
        ("write_todos", {"todos": [{"content": "수입신고 기한 근거 찾기", "status": "in_progress"}]}),
        ("search_law", {"query": "수입신고 기한"}),
        ("calc_deadlines", {}),
    ],
    "장치기간": [("ask_user", {"question": "어느 항구 기준으로 볼까요?", "options": TWO})],
    "설명": [("save_preference", {"depth": "자세히"})],
}


class ScriptModel(BaseChatModel):
    """질문 글로 각본을 고르고, 이번 차례에 이미 낸 모델 답 수로 다음 줄을 고르는 가짜 모델.

    [왜] 상태를 모델 객체가 아니라 메시지에서 읽는다. 여러 대화·재개가 섞여도 각본이 어긋나지 않는다.
    """

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptModel:  # type: ignore[override]
        return self

    @property
    def _llm_type(self) -> str:
        return "e2e-script"

    def _generate(
        self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs: Any
    ) -> ChatResult:
        last = max(i for i, m in enumerate(messages) if m.type == "human")
        question = str(messages[last].content)
        step = sum(m.type == "ai" for m in messages[last + 1 :])
        script = next((lines for key, lines in SCRIPTS.items() if key in question), [])
        if step < len(script):
            name, args = script[step]
            message = AIMessage("", tool_calls=[{"name": name, "args": args, "id": f"e2e-{name}-{step}"}])
        else:
            message = AIMessage("")
        return ChatResult(generations=[ChatGeneration(message=message)])


def search(query: str, as_of: date) -> list[Evidence]:
    # [왜] 검색을 늦춰 "진행 중인 할 일"이 답보다 먼저 보이는지 e2e가 본다 (C9 실시간 계획)
    time.sleep(float(os.environ.get("MARVIA_E2E_SEARCH_DELAY", "2")))
    return [UNIT]


def fake_deps() -> AgentDeps:
    rag = RagDeps(
        analyze=lambda prompt: QueryAnalysis(
            question_type="문구 해석", as_of=None, search_query="수입신고 기한"
        ),
        search=search,
        rerank=lambda query, texts: [0.9] * len(texts),
        grade=lambda prompt: Grade(sufficient=True, reason="e2e", missing=""),
        rewrite=lambda prompt: Rewrite(search_query="수입신고 기한"),
    )

    def write(prompt: str) -> Draft:
        # [왜] 작성자 프롬프트에 든 것만 쓴다. 근거가 없으면 인용하지 않고, 화물이 없으면 토큰을 쓰지 않는다
        #      (검증자를 통과한다)
        # [주의] 작성자 지시문 자체에 "[BL1]" 예가 있다. 화물 줄("[BL1]: 단계")이 있을 때만 토큰을 쓴다
        cargo = "[BL1]:" in prompt
        lead = "[BL1]의 수입신고 기한과 근거를 아래에 정리했어요." if cargo else "확인한 내용을 정리했어요."
        # [왜] 선택지 흐름이 고른 값(인천)이 서버를 지나 작성자까지 닿았는지 e2e가 본다
        lead += " 인천 기준이에요." if "인천" in prompt else ""
        cited = [UNIT.unit_id] if UNIT.unit_id in prompt else []
        return Draft(
            answer=lead, citations=cited, next_options=["관세사에게 신고 대행 묻기"], forwarder_message=""
        )

    nothing = ItemFacts(
        category="모름",
        same=[],
        different=[],
        prior_precise="모름",
        prior_result="모름",
        prior_cert_on=None,
        flags=[],
    )
    return AgentDeps(
        rag=rag,
        plan=lambda prompt: Plan(steps=[Step(action="write", query="", reason="e2e")]),
        item=lambda prompt: nothing,
        write=write,
        model=ScriptModel(),
        provision=lambda label, as_of: [UNIT] if label == "관세법 제241조제3항" else [],
    )


def main() -> None:
    settings = Settings()
    graph = build_main_graph(fake_deps(), InMemorySaver(), loop="agent", store=InMemoryStore())
    app = build_app(graph, verifier(settings), web_origin=settings.web_origin, forget=lambda user: None)
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":
    main()
