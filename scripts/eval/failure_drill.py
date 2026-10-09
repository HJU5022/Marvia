"""에러 로깅 실패 훈련 (D6 에러 로깅 확인).

    python -m scripts.eval.failure_drill --list            # 시나리오 목록: 무엇을 바꾸나 · 기대 줄 · LLM 필요 여부
    python -m scripts.eval.failure_drill --no-llm          # LLM 없이 도는 것만 (비용 0, 외부 API 호출 0)
    python -m scripts.eval.failure_drill                   # 전부. LLM 시나리오는 .env의 LLM_MODEL을 실제로 부른다 (비용이 든다)
    python -m scripts.eval.failure_drill --only judge_truncated judge_connection

책임:
  실패 경로를 하나씩 일부러 일으키고, 그때 log_failure()가 기대한 줄
  "failure stage=<단계> error=<종류>"를 실제로 남기는지 확인한다 (backend/app/observability/logging.py).
  결과는 터미널과 evals/results/failure_drill.txt(깃에서 빠지는 폴더)에 같은 내용으로 쓴다.

왜 필요한가:
  단위 테스트는 가짜 LLM·가짜 응답으로 함수 하나씩 본다. 실제 모델(LLM_MODEL)이 진짜로 실패했을 때
  라우터까지 올라와 같은 줄이 찍히는지는 요청 하나를 끝까지 돌려 봐야 안다.
  평가 실행에서 터미널에 "failure" 한 단어만 찍혀 원인을 몰랐던 일(logging.py log_failure 설명)이
  다시 없는지, 명령 하나로 다시 확인하려는 장치다.

어떻게:
  평가 실행기(evals/run_eval.py)를 그대로 다시 쓴다. 외부 API는 REPLAY 재생, 시계는 문항의 clock, DB는 끈다.
  시나리오마다 딱 하나만 바꾸고(환경변수 또는 함수 바꿔 끼우기) 요청 하나를 돌린 다음 원래대로 되돌린다.
  바꾸는 것은 이 프로세스 안에서만 유효하다. 서버 코드와 .env는 고치지 않는다.
  - LLM 시나리오: 실제 LLM_MODEL을 부른다. --no-llm이면 돌리지 않는다
  - LLM 없는 시나리오: 그 시나리오 동안 LLM·Langfuse 키를 비운다. 실수로 LLM 길을 타도 not_configured로 끝나고 밖으로 나가지 않는다
  - 출처 "평가셋": 평가셋 문항의 재생 자료에서 자연히 나오는 실패
  - 출처 "constructed": 평가셋에서는 안 나와서 작은 가짜 응답(httpx.MockTransport·가짜 chat)으로 만든 것. 단위 테스트와 같은 방식
  - SKIP: 억지로 만들 수 없는 것. 이유를 적는다. 흉내 내서 O를 만들지 않는다

판정: 기대한 줄이 전부 잡히면 O, 하나라도 없으면 X. 잡힌 줄은 기대 밖의 것(db_write not_configured 등)까지 전부 보여 준다.

참고: SDD 5.11 observability, SDD 8절 실패 처리, SDD 5.7 재시도 3회, SDD 3.5 로그에 키·B/L을 넣지 않는다.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable
from unittest import mock

import httpx

from evals import run_eval  # 이 모듈은 import할 때 서버 코드를 부르지 않는다. 서버 코드는 환경변수를 정한 뒤에 import한다

ROOT = run_eval.ROOT
OUTPUT = run_eval.RESULTS / "failure_drill.txt"

BASE_CASE = "N02"  # 기본 요청. 배 1척 확정 → 위치·일정 → 판정까지 다 가는 정상 문항이라 judge가 꼭 불린다
SMALL_MAX_TOKENS = 50  # judge 답이 토큰 한도에서 잘리게 할 상한 (finish_reason=length → truncated)
BAD_MODEL = "vertex/google/gemini-drill-no-such-model"  # 없는 모델 이름. Vertex가 4xx로 답한다
BAD_PROJECT = "marvia-drill-no-such-project"  # 없는 GCP 프로젝트. 어떤 kind가 나오는지 그대로 기록한다
# 아무도 듣지 않는 포트. 연결이 바로 거절돼 오래 기다리지 않는다. 혹시 몰라 연결 대기도 2초로 묶는다
BAD_DB_URL = "postgresql://127.0.0.1:1/drill?connect_timeout=2"

# LLM 없는 시나리오에서 비워 두는 키. 비우면 LLM은 not_configured, Langfuse는 로컬 파일로 가서 밖으로 나가는 호출이 없다
NO_LLM_ENV = ("LLM_MODEL", "EVAL_COMPARE_MODEL", "EVAL_GRADER_MODEL", "OPENROUTER_API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")

SHIPFINDER_FIXTURES = ROOT / "evals" / "fixtures" / "shipfinder"
MOF_FIXTURES = ROOT / "evals" / "fixtures" / "mof"


@dataclass
class Scenario:
    id: str
    changed: str                    # 무엇 하나를 바꾸나
    expected: list[tuple[str, str]]  # 꼭 잡혀야 하는 (stage, error에 들어 있어야 할 글자)
    needs_llm: bool
    source: str                     # 평가셋 문항 / constructed / SKIP
    run: Callable[[], dict | str | None] | None = None  # 요청 하나를 돌린다. 평가 실행기의 결과 한 줄(row)이나 응답 요약 글을 돌려주면 같이 찍는다
    skip: str | None = None         # 돌리지 않는 이유
    note: str | None = None         # 목록과 결과에 같이 찍을 설명


# ── 잡기: marvia.failure 로거에 붙는 수집기 ─────────────────────────

class FailureCatcher(logging.Handler):
    """log_failure()가 남긴 줄의 (stage, error)를 모은다. 시나리오마다 비운다."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.lines: list[tuple[str, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append((getattr(record, "stage", "?"), getattr(record, "error", "?")))


def _setup_logging() -> FailureCatcher:
    catcher = FailureCatcher()
    failure = logging.getLogger("marvia.failure")
    failure.setLevel(logging.WARNING)
    failure.addHandler(catcher)
    # 루트에 빈 핸들러를 달아 재시도 경고(clients/retry.py 등)가 터미널을 덮지 않게 한다.
    # 확인할 것은 marvia.failure 줄뿐이고, 그 줄은 위 수집기가 다 받는다
    logging.getLogger().addHandler(logging.NullHandler())
    return catcher


# ── 평가 실행기 재사용 ─────────────────────────────────────────────

def _case(case_id: str) -> dict:
    """dataset.jsonl에서 문항 하나를 꺼낸다."""
    for line in run_eval.DATASET.read_text(encoding="utf-8").splitlines():
        if line.strip() and json.loads(line)["id"] == case_id:
            return json.loads(line)
    raise SystemExit(f"평가셋에 {case_id}가 없습니다")


def _run_case(case_id: str, config: str) -> dict:
    """평가 실행기의 문항 하나 돌리기(run_eval._run_one)를 그대로 부른다. 재생·시계·위치 엿보기가 같다.
    _run_one이 바꿔 두고 안 되돌리는 두 값(재생 폴더, ShipFinder 캐시)은 여기서 되돌린다. 시나리오끼리 섞이지 않게."""
    from backend.app.clients import replay
    from backend.app.clients.shipfinder import ShipFinderClient

    work = Path(tempfile.mkdtemp(prefix="marvia_drill_"))
    try:
        # 지금 값으로 patch하면 블록을 나갈 때 그 값으로 되돌려 준다
        with mock.patch.object(replay, "REPLAY_DIR", replay.REPLAY_DIR), \
                mock.patch.object(ShipFinderClient, "cache", ShipFinderClient.cache):
            return run_eval._run_one(_case(case_id), config, work)
    finally:
        shutil.rmtree(work, ignore_errors=True)


@contextmanager
def _rules_only():
    """평가 구성 (a)처럼 판정기를 규칙(evals/baseline_rules.py)으로 바꾼다. LLM을 한 번도 부르지 않는다.
    run_eval._setup_config("a")를 그대로 쓰고, patch가 블록을 나갈 때 원래 llm 함수 셋을 되돌려 놓는다."""
    from backend.app.services import llm

    with mock.patch.object(llm, "judge", llm.judge), \
            mock.patch.object(llm, "pick_vessel", llm.pick_vessel), \
            mock.patch.object(llm, "answer_follow_up", llm.answer_follow_up):
        run_eval._setup_config("a")
        yield


def _rules_case(case_id: str) -> Callable[[], dict]:
    """규칙 판정기로 평가셋 문항 하나를 돌리는 함수를 만든다 (도구·DB 실패 시나리오용)."""
    def run() -> dict:
        with _rules_only():
            return _run_case(case_id, "a")
    return run


# ── LLM 시나리오 (실제 LLM_MODEL을 부른다) ───────────────────────────

def _judge_truncated() -> dict:
    """llm.chat을 감싸 max_tokens만 작게 넣는다. 모델·프롬프트·자료는 그대로다."""
    from backend.app.services import llm

    real_chat = llm.chat

    def small_chat(*args, **kwargs):
        kwargs["max_tokens"] = SMALL_MAX_TOKENS
        return real_chat(*args, **kwargs)

    with mock.patch.object(llm, "chat", small_chat):
        return _run_case(BASE_CASE, "b")


def _judge_bad_request() -> dict:
    os.environ["LLM_MODEL"] = BAD_MODEL  # 환경변수는 시나리오가 끝나면 _run_scenario가 되돌린다
    return _run_case(BASE_CASE, "b")


def _judge_auth() -> dict:
    """GCP 프로젝트만 없는 것으로 바꾼다. llm.py가 처음 읽은 로그인 정보·프로젝트를 모듈에 담아 두므로
    그 둘을 비워야 새 프로젝트를 읽는다. 끝나면 원래 담겨 있던 값으로 되돌린다."""
    from backend.app.services import llm

    os.environ["GOOGLE_CLOUD_PROJECT"] = BAD_PROJECT
    with mock.patch.object(llm, "_vertex_creds", None), mock.patch.object(llm, "_vertex_project", None):
        return _run_case(BASE_CASE, "b")


def _judge_connection() -> dict:
    """LLM 호출 시간 상한만 0.001초로. 응답을 기다리지 못하고 연결 실패(시간 초과)가 된다."""
    from backend.app.services import llm

    with mock.patch.object(llm, "TIMEOUT_SEC", 0.001):
        return _run_case(BASE_CASE, "b")


# ── LLM 없는 시나리오 ──────────────────────────────────────────────

def _judge_not_configured() -> dict:
    # LLM_MODEL은 _run_scenario가 이미 비웠다 (NO_LLM_ENV). 판정기는 실제 llm.judge 그대로다
    return _run_case(BASE_CASE, "b")


def _judge_gave_up_f08() -> dict:
    # 평가 실행기가 F08에서 llm.chat을 "{}"를 돌려주는 가짜로 바꾼다 (run_eval._llm_failure_replay).
    # 실제 LLM은 부르지 않지만 judge의 JSON 검사와 라우터의 3회 재시도 경로는 진짜다
    return _run_case("F08", "b")


def _validate_gave_up() -> dict:
    """모양은 맞지만 7규칙 중 V7(근거에 없는 숫자)을 어기는 답을 세 번 내는 가짜 chat.
    실제 모델로는 위반을 마음대로 일으킬 수 없어서 만든 것이다. 검증(validate.check)과 재시도는 진짜다."""
    from backend.app.services import llm

    violating = json.dumps({
        "verdict": "watch", "reasons": [], "conflicts": [], "actions": [],
        "answer": "도착까지 987654일 남았습니다.",  # 근거 카드에 없는 숫자 → V7
        "customs": None,
    }, ensure_ascii=False)

    def fake_chat(*args, **kwargs):
        return llm.LLMResult(content=violating, model="drill/violating", finish_reason="stop")

    with mock.patch.object(llm, "chat", fake_chat):
        return _run_case(BASE_CASE, "b")


def _db_bad_url(case_id: str) -> Callable[[], dict]:
    def run() -> dict:
        # psycopg를 시계 멈춤(freeze_time) 밖에서 먼저 불러 둔다. 안에서 처음 불리면 가짜 datetime 때문에
        # "datetime.date size changed" 경고가 찍힌다 (이 스크립트 첫 실행에서 봄)
        import psycopg  # noqa: F401

        os.environ["DATABASE_URL"] = BAD_DB_URL
        with _rules_only():
            return _run_case(case_id, "a")
    return run


def _history(bad_url: bool) -> Callable[[], str]:
    """GET /api/history를 TestClient로 한 번 부른다.
    main.py의 app은 import할 때 루트 로거를 JSON 출력으로 바꿔 버려서(setup_logging) 이력 라우터만 단 앱을 쓴다."""
    def run() -> str:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from backend.app.routers import history

        if bad_url:
            os.environ["DATABASE_URL"] = BAD_DB_URL
        app = FastAPI()
        app.include_router(history.router)
        body = TestClient(app).get("/api/history", params={"session_id": "drill"}).json()
        return f"available={body.get('available')}, items={len(body.get('items', []))}"
    return run


def _langfuse_fallback() -> dict:
    """Langfuse 키는 가짜 값으로 채우고 langfuse 패키지 import만 실패하게 한다. Langfuse 서버에 붙지 않는다.
    LLM_MODEL은 비워 둔 채라 판정은 not_configured로 끝난다 (LLM을 부르지 않으려는 것)."""
    os.environ["LANGFUSE_PUBLIC_KEY"] = "drill-dummy"
    os.environ["LANGFUSE_SECRET_KEY"] = "drill-dummy"
    # sys.modules에 None을 넣으면 그 이름의 import가 ModuleNotFoundError로 막힌다. 끝나면 원래대로 둔다
    saved = sys.modules.get("langfuse")
    sys.modules["langfuse"] = None
    try:
        return _run_case(BASE_CASE, "b")
    finally:
        if saved is None:
            sys.modules.pop("langfuse", None)
        else:
            sys.modules["langfuse"] = saved


def _langfuse_trace_end() -> None:
    """generation 기록을 닫다가 실패하는 경우. Langfuse 서버 없이 만들 수 없어서 update가 실패하는 가짜 기록을 넘긴다."""
    from backend.app.observability.langfuse import end_generation

    class BrokenGeneration:
        def update(self, **fields):
            raise RuntimeError("drill")

        def end(self):
            pass

    end_generation(BrokenGeneration(), None, "local")


def _shipfinder_served_from_cache() -> None:
    """첫 위치 조회는 성공, 두 번째는 빈도 초과(status 29). 두 번째를 캐시가 받아 주며 줄을 남긴다.
    backend/tests/unit/test_cache.py와 같은 방식이다. 캐시는 새로 만들어 쓰고 끝나면 원래 캐시로 되돌린다."""
    from backend.app.clients.cache import ResponseCache
    from backend.app.clients.shipfinder import ShipFinderClient

    answers = ["position_busan_anchored.json", "rate_limited.json"]

    def handler(request: httpx.Request) -> httpx.Response:
        name = answers.pop(0) if len(answers) > 1 else answers[0]
        return httpx.Response(200, json=json.loads((SHIPFINDER_FIXTURES / name).read_text(encoding="utf-8")))

    with mock.patch.object(ShipFinderClient, "cache", ResponseCache()):
        client = ShipFinderClient(key="drill", transport=httpx.MockTransport(handler))
        client.position(440999001)
        client.position(440999001)


def _mof_page_cap_hit() -> None:
    """해수부 두 API를 한 페이지 2건, 최대 2페이지로 부르고 매번 꽉 찬 페이지(2건)를 준다.
    마지막 페이지까지 꽉 차 있으니 뒤를 못 본 것 → page_cap_hit. backend/tests/unit/test_mof.py와 같은 방식이다."""
    from backend.app.clients.mof import MofClient

    def client(fixture: str) -> MofClient:
        text = (MOF_FIXTURES / fixture).read_text(encoding="utf-8")
        return MofClient(key="drill", transport=httpx.MockTransport(lambda request: httpx.Response(200, text=text)))

    client("control_busan.xml").control_records(date(2026, 9, 22), date(2026, 9, 23), rows=2, max_pages=2)
    client("sailing_busan.xml").sailing_plans(date(2026, 9, 22), date(2026, 9, 26), rows=2, max_pages=2)


# ── 시나리오 목록 ─────────────────────────────────────────────────

SCENARIOS = [
    # LLM 시나리오: 실제 LLM_MODEL. 사용자가 직접 돌린다
    Scenario("judge_truncated", f"llm.chat에 max_tokens={SMALL_MAX_TOKENS}을 끼워 넣음", [("judge", "truncated")],
             True, f"평가셋 {BASE_CASE}", _judge_truncated,
             note="Gemini 생각(reasoning) 토큰이 한도를 먼저 먹으면 본문 없이 잘린다. 3번 다 잘리면 gave up 줄도 나온다"),
    Scenario("judge_bad_request", f"LLM_MODEL={BAD_MODEL}", [("judge", "bad_request")],
             True, f"평가셋 {BASE_CASE}", _judge_bad_request),
    Scenario("judge_auth", f"GOOGLE_CLOUD_PROJECT={BAD_PROJECT} (Vertex 로그인 캐시 비움)", [("judge", "")],
             True, f"평가셋 {BASE_CASE}", _judge_auth,
             note="auth 403을 예상하지만 Vertex가 다른 코드로 답할 수 있다. 억지로 맞추지 않고 나온 kind를 그대로 기록한다 (judge 줄이 있으면 O)"),
    Scenario("judge_connection", "llm.TIMEOUT_SEC=0.001", [("judge", "connection")],
             True, f"평가셋 {BASE_CASE}", _judge_connection),
    Scenario("judge_rate_limited", "없음 (일부러 만들 수 없다)", [("judge", "rate_limited 429")],
             True, "SKIP", skip="natural only: 요청이 몰릴 때만 Vertex·OpenRouter가 429를 준다. 부하 중 평가 실행(run_eval b·c) 로그에서 확인"),

    # LLM 없는 시나리오: 판정 LLM 경로
    Scenario("judge_not_configured", "LLM_MODEL 비움", [("judge", "not_configured")],
             False, f"평가셋 {BASE_CASE}", _judge_not_configured),
    Scenario("judge_gave_up_f08", "평가셋 F08 (평가 실행기가 llm.chat을 '{}' 가짜로 바꿈)",
             [("judge", "bad_format attempt 1"), ("judge", "gave up after 3 attempts")],
             False, "평가셋 F08 (가짜 chat)", _judge_gave_up_f08,
             note="F08은 실제 LLM이 아니라 가짜 chat이다. JSON 검사와 3회 재시도 경로만 진짜"),
    Scenario("validate_gave_up", "llm.chat을 V7 위반 답(근거에 없는 숫자)을 주는 가짜로",
             [("validate", "V7"), ("judge", "gave up after 3 attempts")],
             False, "constructed", _validate_gave_up,
             note="실제 모델의 validate 위반은 마음대로 일으킬 수 없다 (natural only). 검증·재시도 경로는 진짜"),

    # DB
    Scenario("db_write_not_configured", "DATABASE_URL 비움 (규칙 판정기)", [("db_write", "not_configured")],
             False, f"평가셋 {BASE_CASE}", _rules_case(BASE_CASE)),
    Scenario("db_write_bad_url", f"DATABASE_URL={BAD_DB_URL} (규칙 판정기)", [("db_write", "OperationalError")],
             False, f"평가셋 {BASE_CASE}", _db_bad_url(BASE_CASE)),
    Scenario("history_read_not_configured", "DATABASE_URL 비움, GET /api/history", [("history_read", "not_configured")],
             False, "constructed (TestClient)", _history(bad_url=False)),
    Scenario("history_read_bad_url", f"DATABASE_URL={BAD_DB_URL}, GET /api/history", [("history_read", "OperationalError")],
             False, "constructed (TestClient)", _history(bad_url=True)),

    # 도구 실패: 평가셋 재생 자료에서 자연히 나온다
    # 시간 초과는 평가셋에 있는 예전 위치(캐시)로 대신하고 partial로 판정한다. 그래서 도구 실패
    # 대신 "캐시로 대체" 줄이 남는다. 캐시도 없는 시간 초과는 backend/tests/unit/test_cache.py가 본다
    Scenario("tool_timeout_f02", "평가셋 F02 (위치 조회 타임아웃 재생, 캐시 위치로 대체, 규칙 판정기)",
             [("shipfinder:pos", "timeout served_from_cache")],
             False, "평가셋 F02", _rules_case("F02")),
    Scenario("tool_no_permission_f04", "평가셋 F04 (위치 조회 권한 없음 status 21, 규칙 판정기)",
             [("live_position", "no_permission"), ("candidate_detail", "position no_permission")],
             False, "평가셋 F04", _rules_case("F04")),
    Scenario("identify_mrn_not_found", "평가셋 B14 (MRN에 맞는 입항 신고 없음, 규칙 판정기)", [("identify_mrn", "not_found")],
             False, "평가셋 B14", _rules_case("B14")),
    Scenario("candidate_detail_not_found", "평가셋 B13 (후보 위치 재생 파일 없음, 규칙 판정기)",
             [("candidate_detail", "position not_found")],
             False, "평가셋 B13", _rules_case("B13")),

    # Langfuse
    Scenario("langfuse_fallback", "Langfuse 키는 가짜 값, langfuse import만 실패 (LLM_MODEL 비움)",
             [("langfuse_prompt", "fallback=local_file"), ("langfuse_trace_start", "no_trace")],
             False, f"평가셋 {BASE_CASE}", _langfuse_fallback),
    Scenario("langfuse_trace_end", "update가 실패하는 가짜 generation을 end_generation에 넘김", [("langfuse_trace_end", "RuntimeError")],
             False, "constructed", _langfuse_trace_end),

    # 외부 API 클라이언트: 평가셋에서 안 나와서 만든다
    Scenario("shipfinder_served_from_cache", "ShipFinder 위치: 성공 → 빈도 초과(29) (MockTransport)",
             [("shipfinder:pos", "rate_limited served_from_cache")],
             False, "constructed", _shipfinder_served_from_cache),
    Scenario("mof_page_cap_hit", "해수부 두 API: 페이지 2건·최대 2페이지, 매번 꽉 찬 페이지 (MockTransport)",
             [("mof_control", "page_cap_hit 2"), ("mof_sailing", "page_cap_hit 2")],
             False, "constructed", _mof_page_cap_hit),

    # 만들 수 없는 것
    Scenario("llm_overloaded", "없음", [("judge", "overloaded 5xx")], False, "SKIP",
             skip="Gemini/Vertex의 5xx는 일부러 일으킬 수 없다. kind 매핑은 단위 테스트(_status_kind)가 본다"),
    Scenario("llm_no_choices", "없음", [("judge", "no_choices")], False, "SKIP",
             skip="200 안에 choices 없이 error만 오는 것은 OpenRouter 전용이다. LLM_MODEL은 Vertex라 나올 수 없다. 단위 테스트가 본다"),
]


# ── 실행과 출력 ───────────────────────────────────────────────────

def _fmt(stage: str, error: str) -> str:
    # 기대 글자가 빈 칸이면 어떤 kind든 받는다는 뜻이다 (judge_auth)
    return f"stage={stage} error={error or '<나온 kind 그대로 기록>'}"


def _passed(expected: list[tuple[str, str]], caught: list[tuple[str, str]]) -> bool:
    """기대한 줄마다, stage가 같고 error에 기대 글자가 들어 있는 줄이 하나라도 있으면 통과."""
    return all(any(stage == want_stage and want in error for stage, error in caught) for want_stage, want in expected)


def _run_scenario(s: Scenario, catcher: FailureCatcher, out: Callable[[str], None]) -> str:
    """시나리오 하나를 돌리고 O / X / SKIP 중 하나를 돌려준다."""
    out(f"\n[{s.id}]  LLM {'필요' if s.needs_llm else '불필요'} · 출처: {s.source}")
    out(f"  바꾼 것 : {s.changed}")
    out("  기대    : " + " / ".join(_fmt(st, er) for st, er in s.expected))
    if s.note:
        out(f"  참고    : {s.note}")
    if s.skip:
        out(f"  결과    : SKIP ({s.skip})")
        return "SKIP"

    catcher.lines.clear()
    row, crash = None, None
    # 환경변수는 블록을 나갈 때 시작 전 모습으로 통째로 되돌아간다. 시나리오끼리 새지 않게
    with mock.patch.dict(os.environ):
        if not s.needs_llm:
            for key in NO_LLM_ENV:
                os.environ.pop(key, None)
        try:
            row = s.run()
        except Exception as e:  # 한 시나리오가 터져도 나머지는 돈다
            crash = f"{type(e).__name__}: {e}"

    caught = list(catcher.lines)
    out("  잡힌 줄 : " + ("\n            ".join(_fmt(st, er) for st, er in caught) if caught else "(없음)"))
    if isinstance(row, dict):
        out(f"  응답    : status={row['got']['status']}" + (f"  실행 오류={row['error']}" if row["error"] else ""))
    elif row:
        out(f"  응답    : {row}")
    if crash:
        out(f"  실행 오류: {crash}")
    result = "O" if _passed(s.expected, caught) and not crash else "X"
    out(f"  결과    : {result}")
    return result


def _print_list() -> None:
    print(f"{'id':30} {'LLM':4} {'출처':26} 바꾼 것  →  기대 줄")
    for s in SCENARIOS:
        llm_flag = "yes" if s.needs_llm else "no"
        expected = " / ".join(_fmt(st, er) for st, er in s.expected)
        print(f"{s.id:30} {llm_flag:4} {s.source:26} {s.changed}  →  {expected}" + (f"  [SKIP: {s.skip}]" if s.skip else ""))


def main() -> None:
    parser = argparse.ArgumentParser(description="에러 로깅(log_failure) 실패 훈련")
    parser.add_argument("--list", action="store_true", help="시나리오 목록만 찍는다")
    parser.add_argument("--no-llm", action="store_true", help="LLM이 필요 없는 시나리오만 돌린다")
    parser.add_argument("--only", nargs="*", help="이 id만 돌린다")
    args = parser.parse_args()

    if args.list:
        _print_list()
        return

    known = {s.id for s in SCENARIOS}
    unknown = [i for i in args.only or [] if i not in known]
    if unknown:
        raise SystemExit(f"없는 시나리오: {unknown}. --list로 확인하세요")

    # 평가 실행기와 같은 환경: .env 읽기(키는 찍지 않는다), REPLAY_MODE, DB 끔, 재시도 대기 0.
    # 서버 코드는 이 뒤에 import해야 한다. 클라이언트가 import·생성 때 이 값들을 읽는다
    run_eval._setup_env()
    from evals.replay_fixtures import use_error_replay
    use_error_replay()  # F02 타임아웃 재생 (평가 실행기와 같다)
    catcher = _setup_logging()

    # --no-llm은 LLM을 실제로 부르는 시나리오만 뺀다. SKIP은 아무것도 부르지 않으니 이유를 보이게 남긴다
    runs_llm = lambda s: s.needs_llm and not s.skip  # noqa: E731
    chosen = [s for s in SCENARIOS if (not args.only or s.id in args.only) and not (args.no_llm and runs_llm(s))]
    lines: list[str] = []

    def out(text: str) -> None:
        print(text, flush=True)
        lines.append(text)

    mode = "--no-llm (LLM 시나리오 제외)" if args.no_llm else "전체 (LLM 시나리오는 LLM_MODEL을 실제로 부른다)"
    out(f"에러 로깅 실패 훈련 · {mode} · 기본 문항 {BASE_CASE}")
    results = [_run_scenario(s, catcher, out) for s in chosen]

    skipped_llm = sum(1 for s in SCENARIOS if args.no_llm and runs_llm(s) and (not args.only or s.id in args.only))
    out(f"\n요약: O {results.count('O')} · X {results.count('X')} · SKIP {results.count('SKIP')} (총 {len(results)})"
        + (f" · --no-llm으로 안 돌린 LLM 시나리오 {skipped_llm}" if skipped_llm else ""))
    failed = [s.id for s, r in zip(chosen, results) if r == "X"]
    if failed:
        out(f"X: {', '.join(failed)}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n결과 파일: {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
