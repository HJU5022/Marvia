"""설정: 환경 변수와 .env에서 값을 읽는다 (설계 8절·13절, 계획 1 Task 8, 계획 2 Task 1).

하지 않는 일: 키·비밀번호 보관. 값은 환경 변수나 .env에만 두고 코드에는 기본값(로컬 DB, 모델 이름)만 둔다.
[주의] MARVIA_ 접두어가 붙은 이름만 읽는다. 루트 .env의 DATABASE_URL은 v1 운영 DB라,
읽으면 시험 데이터가 운영 DB에 쌓인다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Marvia v2 설정. Settings()로 만들면 환경 변수 → .env → 기본값 순서로 값을 찾는다."""

    model_config = SettingsConfigDict(
        env_prefix="MARVIA_",  # database_url 칸은 MARVIA_DATABASE_URL에서 읽는다
        env_file=".env",  # 환경 변수에 없으면 루트 .env 파일에서 찾는다
        extra="ignore",  # [왜] .env에 v1 키가 섞여 있어도 오류 없이 무시한다
        env_ignore_empty=True,  # [왜] .env에 값 없이 "MARVIA_DATABASE_URL="만 적혀 있으면 기본값을 쓴다
    )

    # 기본값은 docker-compose.yml의 로컬 Postgres (포트 5433)
    database_url: str = "postgresql://marvia:marvia@localhost:5433/marvia"

    # 키 (설계 12절: 저장소에는 이름만 둔다)
    # [왜] SecretStr은 print나 로그에 '**********'로만 보인다. 실제 값은 .get_secret_value()로만 꺼낸다
    anthropic_api_key: SecretStr = SecretStr("")  # MARVIA_ANTHROPIC_API_KEY
    voyage_api_key: SecretStr = SecretStr("")  # MARVIA_VOYAGE_API_KEY
    # [왜] 이 키가 저장 데이터(감시 표의 실제 화물 번호, 대화 기록)를 암호화한다.
    #      비어 있으면 감시 기능을 끄고, 대화 기록을 여는 live_memory는 멈춘다
    data_key: SecretStr = SecretStr("")  # MARVIA_DATA_KEY

    # 모델 (설계 2절 결정 14). [왜] 이름을 설정에 두면 평가 때 환경 변수만 바꿔 다른 모델과 비교할 수 있다
    chat_model: str = "claude-haiku-5-5"  # 대화 LLM (Anthropic API)
    # [왜] cli면 API 키 없이 구독의 `claude -p`로 부른다(cli_model.py). API와 조건이 달라 이 길로 잰 값은
    #      결과에 따로 표시하고(meta.llm_via) API로 잰 값과 섞어 견주지 않는다. 다른 값이면 설정이 거절한다
    llm_via: Literal["api", "cli"] = "api"  # MARVIA_LLM_VIA
    cli_log: str = ""  # MARVIA_CLI_LOG. cli 길의 호출별 원본 출력을 남길 폴더(저장소 밖). 비면 남기지 않는다
    embed_model: str = "voyage-4"  # 임베딩 (Voyage AI)
    embed_dim: int = 1024  # [주의] migrations/001_corpus_units.sql의 vector(1024)와 같아야 한다
    rerank_model: str = "rerank-3"  # 리랭커 (Voyage AI)
    voyage_url: str = "https://api.voyageai.com/v1"

    # 에이전트 (계획 3c). [왜] 고정 계획자(planner)를 기준선·대피로로 남기고, 같은 평가셋으로 둘을 비교한다
    # [왜] 기본값 agent: 평가셋 v1 기준 실행에서 미리 정한 기준을 넘었다 (계획 4a Task 4)
    # [왜] supervisor(계획 7b)는 스위치 뒤의 셋째 길이다. 에이전트 길을 이길 때만 기본값을 바꾼다
    loop: Literal["planner", "agent", "supervisor"] = "agent"  # MARVIA_LOOP
    permission_mode: Literal["ask", "auto"] = "ask"  # MARVIA_PERMISSION_MODE. auto여도 바깥 발송은 늘 묻는다

    # 법령 그래프 (계획 3b). 기본값은 docker-compose.yml의 로컬 Neo4j(비밀번호는 내 컴퓨터에서만 쓰는 값)
    neo4j_url: str = "bolt://localhost:7688"  # MARVIA_NEO4J_URL
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr = SecretStr("marvia-local")  # MARVIA_NEO4J_PASSWORD
    # [왜] 시험은 개발 그래프와 다른 Neo4j(docker compose의 neo4j-test)만 쓴다. 같은 주소면 시험이 거절한다
    neo4j_test_url: str = "bolt://localhost:7689"  # MARVIA_NEO4J_TEST_URL
    # [왜] 끄고 켜서 같은 커밋으로 비교한다(계획 3b Task 6). 켜고 Neo4j에 못 닿으면 검색 실패로 남는다
    graph: Literal["off", "on"] = "off"  # MARVIA_GRAPH

    # UNI-PASS 조회 (계획 3b Task 7). [왜] 기본이 재생이라 키가 있어도 시험·평가는 실제 API를 부르지 않는다
    unipass_mode: Literal["replay", "live"] = "replay"  # MARVIA_UNIPASS_MODE
    unipass_key: SecretStr = SecretStr("")  # MARVIA_UNIPASS_KEY (crkyCn). 실제 키는 직접 넣는다

    # 해수부 입항 일정 조회 (계획 8a). [왜] 기본이 재생이라 키가 있어도 시험·평가는 실제 API를 부르지 않는다
    mof_mode: Literal["replay", "live"] = "replay"  # MARVIA_MOF_MODE
    # 공공데이터포털 키(serviceKey). [주의] MARVIA_DATA_KEY(저장 데이터 암호화 키)와 다른 값이다
    mof_key: SecretStr = SecretStr("")  # MARVIA_MOF_KEY
    mof_base_url: str = ""  # MARVIA_MOF_BASE_URL. 해외 서버에서는 서울 릴레이 주소(relay/). 비면 직접 부른다
    mof_relay_token: SecretStr = SecretStr("")  # MARVIA_MOF_RELAY_TOKEN. 릴레이의 RELAY_TOKEN과 같은 값

    # 배 위치 조회 ShipFinder (계획 8a). 기본은 재생이다
    shipfinder_mode: Literal["replay", "live"] = "replay"  # MARVIA_SHIPFINDER_MODE
    shipfinder_key: SecretStr = SecretStr("")  # MARVIA_SHIPFINDER_KEY

    # 규정 검색 MCP (계획 3b Task 8). [왜] mcp면 에이전트 RAG가 같은 MCP 서버를 메모리 통로로 부른다(설계 9절)
    rag_via: Literal["direct", "mcp"] = "mcp"  # MARVIA_RAG_VIA
    mcp_token: SecretStr = SecretStr("")  # MARVIA_MCP_TOKEN. 비면 scripts/serve_mcp.py가 뜨지 않는다

    # 화면 서버 (계획 4b, 설계 10절·12절).
    # [왜] 사용자는 서명을 확인한 토큰에서만 꺼낸다. 화면이 보낸 값은 믿지 않는다
    # MARVIA_AUTH. dev는 이 컴퓨터에서만 쓴다(Cloud Run이면 시작을 거절한다)
    auth: Literal["supabase", "dev"] = "supabase"
    supabase_url: str = ""  # MARVIA_SUPABASE_URL (https://<프로젝트>.supabase.co). 비밀이 아니다
    # MARVIA_OWNER_IDS. 쓸 수 있는 사용자 id(토큰 sub)를 쉼표로. 비면 supabase 모드 서버가 뜨지 않는다
    owner_ids: str = ""
    dev_token: SecretStr = SecretStr("")  # MARVIA_DEV_TOKEN. auth=dev일 때만 받는 고정 토큰
    host: str = "127.0.0.1"  # MARVIA_HOST. 서버가 듣는 주소. 컨테이너(Dockerfile·compose)만 0.0.0.0으로 연다
    web_origin: str = "http://localhost:3000"  # MARVIA_WEB_ORIGIN. 화면 주소. CORS는 이 origin만 연다

    # 트레이스 (계획 6b, 설계 11절·12절). [왜] 셋이 모두 있을 때만 Langfuse로 보낸다. 하나라도 비면 SDK를
    # 불러오지도 않는다(trace.tracer_callbacks). 보내는 값은 모두 번호를 가린 값이다(langfuse_trace)
    langfuse_public_key: SecretStr = SecretStr("")  # MARVIA_LANGFUSE_PUBLIC_KEY
    langfuse_secret_key: SecretStr = SecretStr("")  # MARVIA_LANGFUSE_SECRET_KEY
    langfuse_host: str = ""  # MARVIA_LANGFUSE_HOST (예: https://cloud.langfuse.com). 비밀이 아니다
