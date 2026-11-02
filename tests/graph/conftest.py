"""tests/graph 공용 준비물. 테스트 함수가 인자 이름(evidence, cargos, fake_rag, agent_deps 등)으로 받는다."""

from datetime import date

import pytest

from marvia.graph.main import AgentDeps
from marvia.graph.rag import RagDeps
from marvia.graph.schemas import Draft, Plan, Step
from marvia.rag.models import Evidence
from marvia.rag.schemas import Grade, QueryAnalysis, Rewrite
from marvia.tools.reimport import ItemFacts

# 근거 한 건 (관세법 제241조제3항). 가짜 RAG가 찾아 주고, evidence 준비물이 dict로 바꿔 준다
UNIT = Evidence(
    unit_id="L001556@20261002#제241조.3항",
    law_name="관세법",
    heading="관세법 > 제9장 통관 > 제241조(수출ㆍ수입 또는 반송의 신고)",
    effective=date(2026, 10, 2),
    source_url="https://www.law.go.kr/test",
    text="제241조 ③ 물품을 보세창고에 반입한 자는 반입일부터 30일 이내에 신고해야 한다.",
    score=0.9,
)


@pytest.fixture
def evidence() -> list[dict]:
    """근거 묶음 한 건. RAG 서브그래프가 state에 넣는 dict 모양 그대로."""
    return [UNIT.model_dump(mode="json")]


@pytest.fixture
def calc() -> dict:
    """계산 결과: [BL1]의 수입신고 기한 (calc 노드가 state에 넣는 모양)."""
    return {
        "deadlines": [
            {
                "cargo": "[BL1]",
                "name": "수입신고 기한",
                "start_stage": "반입신고",
                "start": "2026-10-27",
                "due": "2026-11-26",
                "days_left": 24,
                "basis": "관세법 제241조제3항",
                "surcharge": None,
            }
        ]
    }


@pytest.fixture
def cargos() -> list[dict]:
    """화물 두 건: [BL1]은 조회 성공, [BL2]는 실패 (식별 서브그래프가 넣는 모양)."""
    return [
        {
            "token": "[BL1]",
            "facts": {"stage": "반입신고", "stage_at": "2026-10-27T09:00:00+09:00", "port": "부산"},
            "error": None,
        },
        {
            "token": "[BL2]",
            "facts": None,
            "error": {"code": "not_found", "message": "재생 데이터에 없는 번호입니다", "retryable": False},
        },
    ]


TODAY = date(2026, 11, 2)
# 가짜 작성자가 늘 돌려주는 초안. 인용·날짜·번호가 없어 근거 묶음이 비어 있으면 검증을 통과한다
PLAIN = Draft(
    answer="시험 답이에요.", citations=[], next_options=["관세사에게 물어보기"], forwarder_message=""
)
# 가짜 계획자가 늘 돌려주는 계획: 바로 답 쓰기
WRITE_NOW = Plan(steps=[Step(action="write", query="", reason="모은 것으로 답한다")])
# 가짜 품목 사실: 사용자가 아무것도 말하지 않은 경우
NO_FACTS = ItemFacts(
    category="모름",
    same=[],
    different=[],
    prior_precise="모름",
    prior_result="모름",
    prior_cert_on=None,
    flags=[],
)


@pytest.fixture
def fake_rag():
    """가짜 RagDeps를 만드는 함수. 질의와 상관없이 UNIT을 찾고, sufficient대로 채점한다."""

    def make(sufficient: bool = True) -> RagDeps:
        missing = "" if sufficient else "가산세 대상 보세구역 목록"
        return RagDeps(
            analyze=lambda prompt: QueryAnalysis(
                question_type="문구 해석", as_of=None, search_query="수입신고 기한"
            ),
            search=lambda query, as_of: [UNIT],
            rerank=lambda query, texts: [UNIT.score] * len(texts),
            grade=lambda prompt: Grade(sufficient=sufficient, reason="시험", missing=missing),
            rewrite=lambda prompt: Rewrite(search_query="수입신고 기한 가산세"),
        )

    return make


@pytest.fixture
def agent_deps(fake_rag):
    """가짜 AgentDeps를 만드는 함수. 바꿀 칸만 키워드로 넘긴다: agent_deps(write=...)."""

    def make(**changes) -> AgentDeps:
        base = {
            "rag": fake_rag(),
            "plan": lambda prompt: WRITE_NOW,
            "item": lambda prompt: NO_FACTS,
            "write": lambda prompt: PLAIN,
            "today": lambda: TODAY,
        }
        return AgentDeps(**(base | changes))

    return make
