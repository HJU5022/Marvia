"""설정: 환경 변수와 .env에서 값을 읽는다 (설계 8절, 계획 1 Task 8).

하지 않는 일: 키·비밀번호 보관. 값은 환경 변수나 .env에만 두고 코드에는 기본값(로컬 DB)만 둔다.
[주의] MARVIA_ 접두어가 붙은 이름만 읽는다. 루트 .env의 DATABASE_URL은 v1 운영 DB라,
읽으면 시험 데이터가 운영 DB에 쌓인다.
"""

from __future__ import annotations

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
