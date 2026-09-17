"""FastAPI 진입점.

LLM 호출은 여기가 아니라 services/ 아래 한곳에 모으세요.
3차 프로젝트에서 그 자리에 RAG 그래프가 들어옵니다 — 호출부가 흩어져 있으면 그때 전부 뜯어야 합니다.
"""
from fastapi import FastAPI

app = FastAPI(title="2차 프로젝트 API")


@app.get("/health")
def health() -> dict:
    """채점자와 배포 환경이 서비스 상태를 확인하는 곳."""
    return {"status": "ok"}


# TODO: 도메인 엔드포인트를 여기에 추가하세요.
#   - 요청·응답은 Pydantic 모델로 정의합니다 (필수 조건 3: 출력 계약)
#   - 요청 ID·사용 모델·토큰 수·지연 시간을 로그에 남깁니다 (축 ③ 구조화 로그)
