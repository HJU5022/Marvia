"""지난 응답에 저장된 값 다루기: 컨테이너 번호 봉인·해제, B/L 지문, 날짜 입력 변경 판별 (routers/agent.py에서 옮김, 후속 질문 흐름)."""

import os
from backend.app import crypto
from backend.app.schemas.agent import AgentRequest, AgentResponse
from backend.app.services import llm

# 사용자가 준 날짜 중 바뀌면 여유 일수·등급이 달라지는 것. 지난 결과의 근거 카드(services/judge/evidence.py, source=rule)에 같은 이름으로 있다
_DATE_INPUTS = ("sale_due_date", "forwarder_eta")

def _inputs_changed(request: AgentRequest, previous: AgentResponse) -> bool:
    """이번 요청의 판매 예정일·포워더 입항 예정일이 지난 결과를 만들 때 쓴 값과 다른가.
    지난 값은 근거 카드에서 읽는다. 이번 요청에 값이 없으면 바뀐 것으로 보지 않는다(후속 질문은 보통 날짜를 다시 안 보낸다)."""
    used = {e.field: e.value for e in previous.evidence if e.source == "rule" and e.field in _DATE_INPUTS}
    for field in _DATE_INPUTS:
        value = getattr(request, field)
        if value is not None and used.get(field) != value.isoformat():
            return True
    return False

# 이력(query_log.response)에 컨테이너 번호를 잠가 두는 칸 이름. AgentResponse에는 없는 칸이라 읽을 때 꺼내고 지운다
SEALED_CONTAINER_KEY = "container_no_sealed"

# 이력에 B/L 지문을 두는 칸 이름. 원문이 아니라 BL_ENCRYPTION_KEY로 만든 HMAC이라 되돌릴 수 없다.
# 로그인 없이 남긴 줄도 가린 번호가 같은 다른 화물과 가를 수 있게 한다 (_cargo_rows). 읽을 때 지운다
BL_FINGERPRINT_KEY = "bl_fingerprint"

def _bl_fingerprint(bl_no: str) -> str | None:
    """B/L 지문. 열쇠가 없으면 None (그때는 지문 없이 저장하고, 찾을 때도 예전처럼 가린 번호로 찾는다).
    열쇠가 없는 채점 환경에서 요청마다 no_key 로그가 쌓이지 않게 먼저 열쇠를 본다."""
    if not os.environ.get(crypto.BL_KEY_ENV, "").strip():
        return None
    return crypto.fingerprint(bl_no, key_env=crypto.BL_KEY_ENV)

def _seal_containers(response: AgentResponse, bl_no: str | None = None) -> dict:
    """이력에 저장할 결과. 컨테이너 번호를 평문으로 남기지 않는다 (#69).

    - customs.container_no 칸은 빼고, 같은 번호를 B/L과 같은 열쇠로 잠가 SEALED_CONTAINER_KEY에 둔다 (crypto.encrypt, BL_ENCRYPTION_KEY).
      빼기만 하면 후속 질문이 이력을 읽을 때 번호를 몰라 "컨테이너 번호 뭐야?"에 답하지 못한다 (결정: 알아야 한다)
    - 다른 글자(후속 답 등)에 남은 번호는 [CNTR1] 번호표로 바꾼다. 풀린 번호로 같은 번호표가 다시 만들어진다 (llm.container_tokens)
    - 열쇠가 없으면(encrypt가 None) 잠근 칸 없이 저장한다. 그때는 번호를 잃는 쪽이 원문을 남기는 쪽보다 낫다
    """
    number = response.customs.container_no if response.customs else None
    data = llm.hide_containers(
        response.model_dump(mode="json", exclude={"customs_detail": True, "customs": {"container_no"}}),
        llm.container_tokens(number))
    sealed = crypto.encrypt(number) if number else None
    if sealed:
        data[SEALED_CONTAINER_KEY] = sealed
    fingerprint = _bl_fingerprint(bl_no) if bl_no else None
    if fingerprint:
        data[BL_FINGERPRINT_KEY] = fingerprint
    return data

def _open_containers(saved: dict) -> dict:
    """이력에서 꺼낸 결과에 잠가 둔 컨테이너 번호를 풀어 customs.container_no로 되돌린다. 못 풀면 칸 없이 둔다."""
    saved = dict(saved)
    saved.pop(BL_FINGERPRINT_KEY, None)
    sealed = saved.pop(SEALED_CONTAINER_KEY, None)
    number = crypto.decrypt(sealed) if sealed else None
    if number and isinstance(saved.get("customs"), dict):
        saved["customs"] = {**saved["customs"], "container_no": number}
    return saved

def _same_cargo(rows: list[tuple[dict, str | None]], bl_no: str) -> dict | None:
    """(결과, 잠긴 B/L) 줄들 중 이번 B/L과 같은 가장 최근 결과 (EC-05). 가르는 기준은 _cargo_rows."""
    matched = _cargo_rows(rows, bl_no)
    return matched[0] if matched else None

def _cargo_rows(rows: list[tuple[dict, str | None]], bl_no: str) -> list[dict]:
    """(결과, 잠긴 B/L) 줄들 중 이번 B/L의 결과만 최신순으로.

    줄마다 잠긴 원본(로그인 사용자, 007)을 열어 보고, 없으면 결과 JSON의 B/L 지문(BL_FINGERPRINT_KEY)과 비교한다.
    한 줄도 확인할 수 없으면(열쇠가 없어 원본도 지문도 없던 줄들) 예전처럼 모두 쓴다. 다른 화물로 확인된 줄은 쓰지 않는다."""
    import hmac

    mine = _bl_fingerprint(bl_no)
    checked, matched, unknown = False, [], []
    for response, sealed in rows:
        original = crypto.decrypt(sealed) if sealed else None
        if original is not None:
            checked = True
            if original == bl_no:
                matched.append(response)
            continue
        stored = response.get(BL_FINGERPRINT_KEY) if isinstance(response, dict) else None
        if stored and mine:
            checked = True
            if hmac.compare_digest(str(stored), mine):
                matched.append(response)
            continue
        unknown.append(response)
    return matched if checked else unknown
