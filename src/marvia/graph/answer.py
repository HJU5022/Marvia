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


def final_answer(
    draft: dict, cargos: list[dict], evidence: list[dict], assumptions: Sequence[str] = ()
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
        # [왜] 사용자가 답하지 않아 권장안으로 진행했으면 그 사실을 숨기지 않는다
        _bullets("가정", list(assumptions)),
        _bullets("다음에 할 수 있는 일", draft["next_options"]),
        forwarder,
        _bullets("근거", citations),
    ]
    return "\n\n".join(part for part in parts if part)


def partial_answer(
    cargos: list[dict],
    calc: dict,
    evidence: list[dict],
    gaps: list[str],
    failed_tools: list[dict],
    assumptions: Sequence[str] = (),
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
        _bullets("계산한 것", calc_lines),
        _bullets("찾은 근거", [f"{e['heading']} [{e['unit_id']}]" for e in evidence]),
        _bullets("빠진 근거", gaps),
        _bullets("실패한 도구", [f"{t['tool']}: {t['message']}" for t in failed_tools]),
        _bullets("가정", list(assumptions)),
        _bullets("다음에 할 수 있는 일", load_rules("agent")["finish"]["next_options"]),
    ]
    return "\n\n".join(part for part in parts if part)
