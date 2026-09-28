"""프롬프트를 이름으로 가져온다 (작업 D4, SDD 5.6·5.11).

코드에 프롬프트 문자열을 두지 않는다 (CLAUDE.md). 어디서 가져오나:
  1. Langfuse 키가 있으면 Langfuse Prompt에서 label(기본 production)이 붙은 버전
  2. 키가 없거나, 연결·등록·설치 중 하나라도 실패하면 backend/app/prompts/<이름>.md
     채점자가 키 없이 재현할 때(REPLAY_MODE)와 테스트가 이 길을 탄다.
     이 파일은 Langfuse에 처음 등록할 v1 원본이기도 하다 (C-11)
돌려주는 version은 트레이스의 prompt_version 자리에 들어간다 (SDD 5.11). 파일에서 왔으면 "local".

prompts/를 backend/app/ 안에 둔 이유: Dockerfile이 backend/를 통째로 복사하므로 이미지에도 들어간다.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
LOCAL_VERSION = "local"

logger = logging.getLogger(__name__)


@dataclass
class Prompt:
    name: str
    text: str
    version: str  # Langfuse 버전 번호(문자열) 또는 "local"


def get_prompt(name: str, label: str = "production") -> Prompt:
    """이름으로 프롬프트를 가져온다. Langfuse가 안 되면 로컬 파일로 간다. 판정을 막지 않기 위해서다."""
    if os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"):
        try:
            # 키 없는 테스트 환경에는 langfuse가 설치돼 있지 않을 수 있어 여기서 import한다
            from langfuse import Langfuse

            remote = Langfuse().get_prompt(name, label=label)
            return Prompt(name=name, text=remote.prompt, version=str(remote.version))
        except Exception as e:  # 미설치·연결 실패·미등록 모두 같은 처리: 로컬 파일
            logger.warning("langfuse 프롬프트 %s 가져오기 실패(%s), 로컬 파일을 씁니다", name, type(e).__name__)

    path = PROMPT_DIR / f"{name}.md"
    return Prompt(name=name, text=path.read_text(encoding="utf-8"), version=LOCAL_VERSION)
