"""tests/graph 공용 준비물. 이 폴더의 테스트 함수가 인자 이름(evidence, calc, cargos)으로 받아 쓴다."""

import pytest


@pytest.fixture
def evidence() -> list[dict]:
    """근거 묶음 한 건 (관세법 제241조제3항). RAG 서브그래프가 state에 넣는 dict 모양 그대로."""
    return [
        {
            "unit_id": "L001556@20261002#제241조.3항",
            "law_name": "관세법",
            "heading": "관세법 > 제9장 통관 > 제241조(수출ㆍ수입 또는 반송의 신고)",
            "effective": "2026-10-02",
            "source_url": "https://www.law.go.kr/test",
            "text": "제241조 ③ 물품을 보세창고에 반입한 자는 반입일부터 30일 이내에 신고해야 한다.",
            "score": 0.9,
        }
    ]


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
