"""집결지 판정. 후보 표와 규칙을 대형 모델에 주고 순위를 받는다. (SDD 5절 6단계, 8절)

대형 모델이 만드는 것은 rank·reason·rejected_reason·switched_from 뿐이다. 숫자와 access_ok 는
코드가 이미 넣었고 여기서는 바꾸지 않는다 (docs/PRD.md 3절).

스키마를 어기면 한 번 더 시도하고, 그래도 어기면 예외를 올린다. 부르는 쪽(pipeline)이 규칙 점수 순서로
대신 채운다 (SDD 5절 6단계 "실패면 rules.apply 순으로 rank, reason 은 규칙 문구 그대로").
"""
from __future__ import annotations

import json
from typing import Any

from backend.app.domain import rules as domain_rules
from backend.app.observability import langfuse
from backend.app.schemas.slots import Slots
from backend.app.services.llm import _client, _parse_json_block, model_large

PROMPT_BY_PRESET = {
    "ship_maintenance": "converge/judge-ship",
    "si_deploy": "converge/judge-si",
}

# 프롬프트에 붙이는 규칙 파일. 값이 아니라 문서를 그대로 넣는다 (RAG 없이 통째로, CLAUDE.md)
RULE_FILES = ("access", "transport")


def _rules_text() -> str:
    lines: list[str] = []
    for name in RULE_FILES:
        values = domain_rules.load_rule(name)
        lines.append(f"[{name}.md]")
        lines.extend(f"- {key}: {value}" for key, value in values.items())
    return "\n".join(lines)


def _situation_text(slots: Slots) -> str:
    access = slots.access
    return "\n".join(
        [
            f"- 목적지: {slots.destination}",
            f"- 목적: {slots.purpose}",
            f"- 약속: {slots.datetime}",
            f"- 출입 절차: 필요={access.required if access else None}, 신청={access.applied if access else None}",
            f"- 제약: {', '.join(slots.constraints) if slots.constraints else '없음'}",
            f"- 집결지 언급: {slots.rendezvous.name if slots.rendezvous else '없음'}",
            "- 참석자: "
            + ", ".join(
                f"{p.name}({p.role}, {p.transport or '미정'}"
                + (f", {p.pickup} 차로 {p.pickup_at} 탑승" if p.pickup else "")
                + (", 지리 모름" if p.unfamiliar else "")
                + ")"
                for p in slots.participants
            ),
        ]
    )


def _candidates_text(candidates: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"{i}. {c['name']} (kind={c['kind']}, access_ok={c.get('access_ok', True)}, 주소={c['address'] or '미상'})"
        for i, c in enumerate(candidates)
    )


def _participants_text(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "(경로 조회 결과 없음)"
    return "\n".join(
        f"- 후보{r['candidate_idx']} {r['name']}: {r['transport']}, 경로 {r['raw_duration_min']}분"
        + (f", 환승 {r['transfer_count']}회" if r.get("transfer_count") else "")
        for r in rows
    )


async def rank(
    slots: Slots, candidates: list[dict[str, Any]], participant_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """후보 순위를 대형 모델에 맡긴다. 돌려주는 항목은 rankings 배열 그대로.

    candidates 항목에는 name·kind·address·access_ok 가, participant_rows 에는 candidate_idx·name·
    transport·raw_duration_min·transfer_count 가 있어야 한다.
    """
    prompt_name = PROMPT_BY_PRESET.get(slots.preset or "", "converge/judge-si")
    prompt, version = langfuse.get_prompt(prompt_name)
    filled = (
        prompt.replace("{{rules}}", _rules_text())
        .replace("{{situation}}", _situation_text(slots))
        .replace("{{candidates}}", _candidates_text(candidates))
        .replace("{{participants}}", _participants_text(participant_rows))
    )

    client = _client()
    model = model_large()
    last_error: Exception | None = None

    for attempt in (1, 2):
        messages = [{"role": "user", "content": filled}]
        if attempt == 2 and last_error is not None:
            messages.append(
                {
                    "role": "user",
                    "content": f"방금 출력이 형식을 어겼습니다: {last_error}. rankings 배열만 다시 JSON 으로 출력하세요.",
                }
            )
        res = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0,
            response_format={"type": "json_object"},
        )
        try:
            data = _parse_json_block(res.choices[0].message.content or "")
            rankings = _validate(data, len(candidates))
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            last_error = e
            continue
        return [{**row, "model": model, "prompt_version": f"{prompt_name}@{version}"} for row in rankings]

    raise last_error if last_error else RuntimeError("판정에 실패했습니다")


def _validate(data: dict[str, Any], count: int) -> list[dict[str, Any]]:
    """모델 출력이 쓸 수 있는 모양인지 본다. 어기면 ValueError.

    후보 수와 답 수가 같아야 하고, 순위는 1부터 겹치지 않아야 한다. 하나라도 어긋나면 재시도한다.
    화면과 저장 스키마(SDD 4절)가 이 전제를 그대로 믿기 때문이다.
    """
    rankings = data.get("rankings")
    if not isinstance(rankings, list) or len(rankings) != count:
        raise ValueError(f"rankings 가 후보 수({count})와 다릅니다: {rankings!r}")

    seen_idx: set[int] = set()
    seen_rank: set[int] = set()
    out: list[dict[str, Any]] = []
    for row in rankings:
        idx, rank_value = row.get("candidate_idx"), row.get("rank")
        if not isinstance(idx, int) or not 0 <= idx < count or idx in seen_idx:
            raise ValueError(f"candidate_idx 가 잘못됐습니다: {idx!r}")
        if not isinstance(rank_value, int) or not 1 <= rank_value <= count or rank_value in seen_rank:
            raise ValueError(f"rank 가 잘못됐습니다: {rank_value!r}")
        seen_idx.add(idx)
        seen_rank.add(rank_value)
        out.append(
            {
                "candidate_idx": idx,
                "rank": rank_value,
                "reason": str(row.get("reason") or "").strip() or "판정 이유가 비어 있습니다",
                "rejected_reason": row.get("rejected_reason") or None,
                "switched_from": row.get("switched_from") or None,
            }
        )
    return out
