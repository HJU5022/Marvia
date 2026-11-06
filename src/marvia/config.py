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
    embed_model: str = "voyage-4"  # 임베딩 (Voyage AI)
    embed_dim: int = 1024  # [주의] migrations/001_corpus_units.sql의 vector(1024)와 같아야 한다
    rerank_model: str = "rerank-3"  # 리랭커 (Voyage AI)
    voyage_url: str = "https://api.voyageai.com/v1"

    # 에이전트 (계획 3c). [왜] 고정 계획자(planner)를 기준선·대피로로 남기고, 같은 평가셋으로 둘을 비교한다
    # [왜] 기본값 agent: 평가셋 v1 기준 실행에서 미리 정한 기준을 넘었다 (계획 4a Task 4)
    loop: Literal["planner", "agent"] = "agent"  # MARVIA_LOOP
    permission_mode: Literal["ask", "auto"] = "ask"  # MARVIA_PERMISSION_MODE. auto여도 바깥 발송은 늘 묻는다
