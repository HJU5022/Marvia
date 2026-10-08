"""마르비아가 답하지 않는 부분의 다음 행선지(안내처)를 코드가 붙인다 (docs/specs/referral-guide.md).

두 군데에 쓴다.
  1. 판정 응답: 켜진 신호마다 누구에게 무엇을 물을지 한 줄을 할 일(actions) 끝에 붙인다 (signal_lines)
  2. 채팅: 범위 밖 주제(항공·육상, 창고 수령일, 일정 변경, 날씨, 품목 요건)를 LLM 없이 고정 문장으로 답한다 (out_of_scope_reply)

문장·순서·주소는 skills/referrals/rules.md 프론트매터에만 있다. LLM은 안내처를 쓰지 않는다:
주소·전화번호를 지어내지 않게 하고, 판정 LLM 출력 검증(V1~V7)도 그대로 두려는 것이다.
"""
from __future__ import annotations

import re
from functools import cache

from backend.app.services.judge import verdict as verdict_table
from backend.app.services.judge.rules import rule


def signal_lines(signal_set) -> list[str]:
    """켜진 신호에서 확인처 줄을 만든다. 켜진 신호가 없으면(괜찮음) 빈 목록이다.

    순서는 rules.md referral_order(위험한 순서), 개수는 referral_max까지 한 줄로 묶는다.
    입력 오류로 세지 않는 신호(깨진·빈 목적지 등, verdict.input_error)는 판정에 안 들어갔으니 안내도 붙이지 않는다.
    통관 보류처럼 공식 창구가 있는 신호는 signal_referral_links 줄을 한 줄 더 붙인다.
    """
    if signal_set is None:
        return []
    on = {s.id for s in signal_set.signals if s.state == "triggered" and not verdict_table.input_error(s)}
    texts = rule("signal_referrals")
    picked = [sid for sid in rule("referral_order") if sid in on and texts.get(sid)][: rule("referral_max")]
    if not picked:
        return []
    lines = [rule("referral_prefix") + " ".join(texts[sid] for sid in picked)]
    links = rule("signal_referral_links") or {}
    lines += [links[sid] for sid in picked if links.get(sid)]
    return lines


def with_signal_lines(actions: list[str], signal_set) -> list[str]:
    """LLM이 쓴 할 일 뒤에 확인처 줄을 붙인 새 목록. 같은 줄이 이미 있으면 다시 붙이지 않는다."""
    extra = [line for line in signal_lines(signal_set) if line not in actions]
    return [*actions, *extra]


def broker_tail() -> str:
    """세액·통관 가부 고정 안내 뒤에 붙는 공식 창구 줄 (services/chat/chat.py BROKER_ONLY)."""
    return rule("broker_referral")


@cache
def _topics() -> list[tuple[str, re.Pattern, re.Pattern | None, str]]:
    """rules.md out_of_scope를 한 번만 정규식으로 만든다."""
    out = []
    for item in rule("out_of_scope"):
        require = re.compile(item["require"]) if item.get("require") else None
        out.append((item["topic"], re.compile(item["match"], re.IGNORECASE), require, item["reply"]))
    return out


def out_of_scope_topic(message: str) -> tuple[str, str] | None:
    """범위 밖 주제면 (주제 이름, 고정 답)을, 아니면 None을 돌려준다. 먼저 맞는 주제 하나만 본다.

    부르는 쪽(services/chat/chat.py)이 B/L이 없는 문장에만 쓴다. B/L이 있으면 그 화물을 조회하는 것이 먼저다.
    """
    text = message or ""
    for topic, match, require, reply in _topics():
        if match.search(text) and (require is None or require.search(text)):
            return topic, reply
    return None
