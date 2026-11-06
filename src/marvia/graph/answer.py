"""답에서 코드가 쓰는 부분: 화물 상태 줄, 최종 답 조립, 부분 답 (설계 6.4, 6.5, 4.1의 ③).

하지 않는 일: LLM 호출, 번호 되돌리기(노드가 unmask로 한다). 여기서 만드는 글은 모두 가린 토큰을 쓴다.
[왜] 화물 상태·인용 목록·부분 답은 LLM이 아니라 코드가 쓴다. 숫자와 인용이 state 값과 어긋날 수 없다.
"""

from __future__ import annotations

from collections.abc import Sequence

from marvia.tools.deadlines import kst_date
from marvia.tools.rules import load_rules

# 번호 없을 때 안내 (설계 4.1의 ③). 포워더에게 보낼 문장은 작성자가 쓰고, 이 줄은 코드가 늘 같게 쓴다
FORWARDER_LEAD = (
    "번호가 있어야 화물을 찾을 수 있어요. 포워더에게 B/L 번호나 화물관리번호를 물을 때 이렇게 보내 보세요."
)
DONE_TITLE = "이번 차례에 한 일"  # 최종 답과 부분 답이 같은 제목을 쓴다


def cargo_lines(cargos: list[dict]) -> list[str]:
    """화물마다 한 줄: 토큰, 통관 단계, 항구, 단계 날짜. 조회에 실패했으면 이유."""
    lines = []
    for cargo in cargos:
        facts = cargo["facts"]
        if facts:
            day = kst_date(facts["stage_at"]).isoformat() if facts.get("stage_at") else ""  # 한국 날짜
            port = f" ({facts['port']})" if facts.get("port") else ""  # [왜] 항구를 모르면 "(None)" 대신 뺀다
            lines.append(f"{cargo['token']}: {facts['stage']}{port} {day}".rstrip())
        else:
            error = cargo["error"]
            lines.append(f"{cargo['token']}: 조회하지 못했어요 ({error['message']}, {error['code']})")
    return lines


def _header(cargos: list[dict]) -> str:
    """읽은 건수(여럿일 때)와 화물 상태 줄."""
    # [왜] 붙여 쓴 번호를 나눴으면 "몇 건으로 읽었는지" 먼저 보여 준다 (설계 결정 7: 읽은 대로 보여 준다)
    reading = [f"{len(cargos)}건으로 읽었어요."] if len(cargos) > 1 else []
    return "\n".join(reading + cargo_lines(cargos))


def _bullets(title: str, items: list[str]) -> str:
    """제목 줄 아래 "- " 목록. 항목이 없으면 빈 글."""
    return f"{title}:\n" + "\n".join(f"- {item}" for item in items) if items else ""


def _official(sources: Sequence[dict]) -> str:
    """색인 밖 공식 출처 목록 (계획 3d). 근거(인용)와 다른 이름표로 따로 보인다."""
    lines = [f"{s['name']} (시행 {s['effective']}) {s['url']}" for s in sources]
    return _bullets("공식 출처(색인 밖)", lines)


def final_answer(
    draft: dict,
    cargos: list[dict],
    evidence: list[dict],
    assumptions: Sequence[str] = (),
    official: Sequence[dict] = (),
    actions: Sequence[str] = (),
) -> str:
    """검증을 통과한 초안으로 최종 답을 만든다 (가린 토큰 그대로). 권장안으로 진행한 가정도 보여 준다."""
    # [주의] 검증을 통과한 초안만 넣는다. 그래서 인용은 모두 근거 묶음에 있다
    by_id = {e["unit_id"]: e for e in evidence}
    citations = [
        f"{e['heading']} (시행 {e['effective']}) {e['source_url']} [{e['unit_id']}]"
        for e in (by_id[c] for c in draft["citations"])
    ]
    forwarder = f"{FORWARDER_LEAD}\n{draft['forwarder_message']}" if draft["forwarder_message"] else ""
    parts = [
        _header(cargos),
        draft["answer"],
        # [왜] 승인 뒤 실제로 한 일은 코드가 쓴다. 작성자 글이 틀려도 한 일은 바르게 보인다
        _bullets(DONE_TITLE, list(actions)),
        # [왜] 사용자가 답하지 않아 권장안으로 진행했으면 그 사실을 숨기지 않는다
        _bullets("가정", list(assumptions)),
        _bullets("다음에 할 수 있는 일", draft["next_options"]),
        forwarder,
        _bullets("근거", citations),
        # [왜] 공식 사이트에서 이름으로 찾은 출처는 코퍼스 근거보다 믿음 단계가 낮다. 인용과 섞지 않는다
        _official(official),
    ]
    return "\n\n".join(part for part in parts if part)


def partial_answer(
    cargos: list[dict],
    calc: dict,
    evidence: list[dict],
    gaps: list[str],
    failed_tools: list[dict],
    assumptions: Sequence[str] = (),
    official: Sequence[dict] = (),
    actions: Sequence[str] = (),
) -> str:
    """한도에 걸리거나 검증을 두 번 넘지 못했을 때의 부분 답 (설계 6.4, 결정 4의 ③). 초안은 쓰지 않는다."""
    calc_lines = [
        f"{d['cargo']} {d['name']}: {d['due']}까지 ({d['basis']})" for d in calc.get("deadlines", [])
    ]
    if calc.get("reimport"):
        reimport = calc["reimport"]
        # [왜] "대상 아님"이면 이름표가 없다. 빈 괄호를 쓰지 않는다
        basis = f" ({', '.join(reimport['basis'])})" if reimport["basis"] else ""
        calc_lines.append(f"재수입 검사: {reimport['verdict']}{basis}")
    parts = [
        _header(cargos),
        "끝까지 확인하지 못했어요. 지금까지 확인한 것만 적어요.",
        _bullets(DONE_TITLE, list(actions)),
        _bullets("계산한 것", calc_lines),
        _bullets("찾은 근거", [f"{e['heading']} [{e['unit_id']}]" for e in evidence]),
        _official(official),
        _bullets("빠진 근거", gaps),
        _bullets("실패한 도구", [f"{t['tool']}: {t['message']}" for t in failed_tools]),
        _bullets("가정", list(assumptions)),
        _bullets("다음에 할 수 있는 일", load_rules("agent")["finish"]["next_options"]),
    ]
    return "\n\n".join(part for part in parts if part)


def with_news(news: Sequence[str], text: str) -> str:
    """답 맨 앞에 감시 중인 화물의 새 변화를 붙인다 (계획 3d). 변화가 없으면 답 그대로."""
    block = _bullets("감시 중인 화물 변화", list(news))
    return f"{block}\n\n{text}" if block else text


def decline_answer() -> str:
    """도메인 밖 거절과 할 수 있는 일을 코드가 쓴다 (설계 1절 범위: 해상 수입 화물·통관·수입식품)."""
    scope = load_rules("agent")["scope"]
    return f"{scope['decline']}\n\n" + _bullets("Marvia가 할 수 있는 일", scope["can_do"])
