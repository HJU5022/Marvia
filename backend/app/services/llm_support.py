"""LLM 입력을 만들고 출력을 다듬는 순수 함수: 판정 입력 조립, 통관 정제, 컨테이너 가리기, 느슨한 JSON 읽기 (services/llm.py에서 옮김). SDK 호출은 llm.py에 있다."""
from __future__ import annotations

import json
import os
import re
from dataclasses import replace
from datetime import datetime, date, timezone
from pydantic import ValidationError, BaseModel
from backend.app.schemas.customs import CustomsRecord
from backend.app.schemas.signals import SignalSet
from backend.app.services.judge.evidence import KST
from backend.app.services.judge import guard
from backend.app.services.judge.signals import needs_broker
from backend.app.services.llm_config import JUDGE_CUSTOMS_EXCLUDE, STAGE_SUSPECT
from backend.app.services.llm_types import LLMResult

def _vertex_thinking() -> dict | None:
    """VERTEX_THINKING_BUDGET이 있으면 Gemini의 생각(thinking) 토큰 상한을 요청에 붙인다. 없으면 None(모델 기본값).

    평가: Gemini 2.5 Flash는 답 전에 호출당 평균 1,863토큰을 생각에 써서 정상 질문 평균 10.1초였다
    (gpt-4o-mini 3.3초). 0이면 생각을 끈다. 실측 1회: 생각 597 → 0토큰, 5.3초 → 1.1초.
    OpenAI 형식의 reasoning_effort="none"은 Vertex가 400으로 거부해서(high·low·max·medium·minimal만 받음)
    Google 전용 칸 thinking_config를 쓴다. 이 SDK 호출에서는 extra_body 안에 한 겹 더 extra_body로 넣어야
    Vertex에 전달된다 (Vertex AI "OpenAI 라이브러리 사용" 문서 형식, 실측으로 확인).
    """
    budget = os.environ.get("VERTEX_THINKING_BUDGET")
    if budget is None or budget == "":
        return None
    return {"extra_body": {"google": {"thinking_config": {"thinking_budget": int(budget)}}}}

def _status_kind(status: int) -> str:
    """HTTP 상태 코드를 LLMError.kind로 바꾼다."""
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "overloaded"
    if status in (401, 403):
        return "auth"
    return "bad_request"

def _judge_input(signals: SignalSet, customs: CustomsRecord | None, days_margin: int | None,
                 trusted_eta: datetime | None = None, sale_due_date: date | None = None,
                 table_verdict: str | None = None, verdict_mode: str | None = None) -> str:
    """LLM에 넘길 자료를 JSON 문자열로 만든다. B/L 번호(bl_masked)와 MRN은 판정에 필요 없어 뺀다 (CLAUDE.md, SDD 3.5).

    날짜는 한국 시각으로 준다. 전에는 여유 일수 숫자만 줘서 "언제 와요?"에 날짜로 답하지 못했고,
    사용자가 말한 판매일을 근거에 없는 숫자로 보고 검증(V7)이 막기도 했다 (평가 F06 "9월 23일"). 판매일이 없으면 null이다 (선택 입력).
    calc_eta는 남은 거리 ÷ 현재 속도로 코드가 계산한 대략값이다. 참고용이라 판정 근거로 쓰지 않게 지시문에 적는다.
    table_verdict·verdict_mode (services/judge/verdict.py): 코드가 판정 표로 낸 등급과, LLM이 그 등급을
    그대로 써야 하는지(fixed) 표 이상에서 고를 수 있는지(raise_only, 회색 지대)를 알려 준다.
    needs_broker: 관세사가 봐야 하는 단계인지 코드가 정한 값. LLM은 이 값에 맞춰 설명만 한다. 통관 정보가 없으면 null.
    """
    data = {
        "table_verdict": table_verdict,
        "verdict_mode": verdict_mode,
        "signals": [s.model_dump() for s in signals.signals],
        "freshness": signals.freshness,
        "distance_nm": signals.distance_nm,
        "trusted_eta": _kst(trusted_eta),
        "sale_due_date": sale_due_date.isoformat() if sale_due_date else None,
        "calc_eta": _kst(signals.calc_eta),
        "days_margin": days_margin,
        "customs": _clean_customs(customs.model_dump(mode="json", exclude=JUDGE_CUSTOMS_EXCLUDE)) if customs else None,
        "needs_broker": needs_broker(customs.stage_name) if customs and customs.stage_name else None,
    }
    return json.dumps(data, ensure_ascii=False)

def _clean_customs(data: dict) -> dict:
    """통관 단계명(UNI-PASS 외부 글자)이 주입 모양이면 LLM에 넘기기 전에 바꾼다 (SDD 7절).
    단계명은 외부에서 온 글자라 주입이 들어올 수 있는 길이다. 판정 LLM이 그 문장을 보지 않게 한다 (예방 조치).
    화면의 근거 카드에는 원래 글자가 그대로 있다. 여기서 바꾸는 것은 LLM 입력뿐이다."""
    if guard.looks_like_injection(data.get("stage_name")):
        data["stage_name"] = STAGE_SUSPECT
    for stage in data.get("stage_history") or []:
        if guard.looks_like_injection(stage.get("name")):
            stage["name"] = STAGE_SUSPECT
    return data

def _kst(moment: datetime | None) -> str | None:
    """시각을 한국 시각 "YYYY-MM-DD HH:MM"으로. 근거 카드(services/judge/evidence.py)와 같은 모양이라 V7 대조가 맞는다."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(KST).strftime("%Y-%m-%d %H:%M")

def _loose_json(content: str | None, output_model: type[BaseModel]) -> str | None:
    """도구 라운드에서 모델이 response_format 없이 낸 본문을 output_model JSON으로 읽는다. 읽히면 깨끗한 JSON 문자열, 아니면 None.

    ```json 코드 울타리와 앞뒤 공백만 벗긴다. 그 이상은 하지 않는다: 여기서 못 읽으면 _ask_json이
    response_format을 붙여 한 번 더 묻는 쪽이 더 믿을 만하다.
    """
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0].strip()
    try:
        output_model.model_validate_json(text)
    except ValidationError:
        return None
    return text

def _summed(rounds: list[LLMResult]) -> LLMResult:
    """도구 고리 여러 라운드의 chat() 결과를 하나로 합친다 (점검: Langfuse에 마지막 라운드 토큰만 남았다).
    본문·도구 호출·모델·finish_reason·request_id는 마지막 라운드 것이고, 토큰·캐시 토큰·비용은 모든 라운드의 합이다.
    값을 하나도 안 준 칸(None)은 합도 None으로 둔다(Vertex는 cost를 안 준다). 재시도 수는 라운드마다의 재시도(attempts-1)를 더한다.
    지연은 마지막 시도의 것을 그대로 둔다 (LLMResult.latency_ms 정의). 한 라운드면 그 결과를 그대로 돌려준다."""
    if len(rounds) == 1:
        return rounds[0]

    def total(name: str):
        values = [getattr(r, name) for r in rounds if getattr(r, name) is not None]
        return sum(values) if values else None

    return replace(rounds[-1], prompt_tokens=total("prompt_tokens"), completion_tokens=total("completion_tokens"),
                   cached_tokens=total("cached_tokens"), cost=total("cost"),
                   attempts=1 + sum(r.attempts - 1 for r in rounds))

def _replay_matches(expected: dict, data: dict) -> bool:
    """녹화의 match 칸이 이번 입력과 같은가. signals는 {신호 id: 상태}로 줄여서 비교한다 (값·거리는 시각에 따라 조금씩 달라진다)."""
    for key, value in expected.items():
        actual = data.get(key)
        if key == "signals":
            actual = {s["id"]: s["state"] for s in actual or []}
        if actual != value:
            return False
    return True

def _hours_since(then: datetime, now: datetime) -> float:
    """then부터 now까지 몇 시간 지났나 (소수 한 자리). 시간대가 없으면 UTC로 본다."""
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return round((now - then).total_seconds() / 3600, 1)

# 컨테이너 번호 토큰 (CLAUDE.md "컨테이너 번호는 B/L처럼 LLM에 원문을 넘기지 않는다").
# 컨테이너 번호도 화물을 특정하는 번호라 LLM은 [CNTR1], [CNTR2] 번호표만 본다. 화면에 나가는 답에서는 코드가 원래 번호로 되돌린다
CONTAINER_TOKEN = re.compile(r"\[CNTR\d+\]")

def container_tokens(container_no: str | None) -> dict[str, str]:
    """컨테이너 번호 문자열(여러 개면 ', '로 이음)을 {"[CNTR1]": 번호, "[CNTR2]": 번호}로 만든다. 없으면 빈 dict.

    왜 한 함수인가: LLM에 넘기는 쪽(answer_follow_up)과 답을 되돌리는 쪽(routers/agent.py _follow_up)이 같은 번호표를
    써야 해서, 둘 다 이 함수로 같은 값(response.customs.container_no)에서 다시 만든다. 순서가 같으면 번호표도 같다.
    같은 번호가 두 번 나오면 하나로 본다."""
    numbers = list(dict.fromkeys(n.strip() for n in (container_no or "").split(", ") if n.strip()))
    return {f"[CNTR{i}]": number for i, number in enumerate(numbers, start=1)}

def hide_containers(value, tokens: dict[str, str]):
    """dict·list 안 모든 글자에서 컨테이너 번호를 번호표로 바꾼다. 통관 칸뿐 아니라 근거 카드 값, 지난 답(answer)에
    번호가 섞여 있어도 LLM에는 안 가게 하는 안전망이다 (지난 후속 답은 화면용으로 되돌린 번호를 담은 채 저장된다)."""
    if isinstance(value, str):
        for token, number in tokens.items():
            value = value.replace(number, token)
        return value
    if isinstance(value, dict):
        return {k: hide_containers(v, tokens) for k, v in value.items()}
    if isinstance(value, list):
        return [hide_containers(v, tokens) for v in value]
    return value

def restore_containers(text: str, tokens: dict[str, str]) -> str:
    """답 글자 속 [CNTR1]을 원래 컨테이너 번호로 되돌린다. 화면에만 가는 글자에 쓴다 (LLM에는 되돌린 글이 안 간다).
    모르는 번호표(LLM이 지어낸 [CNTR9])는 그대로 둔다."""
    return CONTAINER_TOKEN.sub(lambda m: tokens.get(m.group(0), m.group(0)), text)
