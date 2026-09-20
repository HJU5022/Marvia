"""AUTH_REQUIRED=false 우회 경로 (SDD 2절·9절). 키 없이 돈다 (TEST_GUIDE).

로컬 채점 모드의 user_id 가 uuid 인지 본다. uuid 가 아니면 sessions.user_id(uuid 컬럼)에 들어가지
못해 계산은 되는데 저장만 조용히 실패한다. 실제로 겪은 일이라 테스트로 막는다.
"""
from __future__ import annotations

import os
import uuid

import pytest

from backend.app.services import auth


@pytest.fixture(autouse=True)
def _restore():
    before = os.environ.get("AUTH_REQUIRED")
    yield
    if before is None:
        os.environ.pop("AUTH_REQUIRED", None)
    else:
        os.environ["AUTH_REQUIRED"] = before


def test_로컬_채점_사용자는_uuid_다():
    assert uuid.UUID(auth.LOCAL_GRADER_USER_ID)


def test_기본값은_로그인_필수():
    os.environ.pop("AUTH_REQUIRED", None)
    assert auth.auth_required() is True


def test_false_일_때만_검사를_건너뛴다():
    for value, expected in (("false", False), ("FALSE", False), ("true", True), ("0", True), ("", True)):
        os.environ["AUTH_REQUIRED"] = value
        assert auth.auth_required() is expected
