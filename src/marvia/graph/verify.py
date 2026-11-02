"""검증자: 작성자 초안을 코드 규칙으로 검사한다 (설계 6.5, 5.6 인용 규칙).

하지 않는 일: 고치기(위반 문장을 돌려주면 작성자가 고친다), 오래된 위치 검사(설계 6.5의 위치 규칙,
선박 위치 조회가 없는 계획 3a에서는 하지 않는다), 답의 뜻이 맞는지 판단(LLM 채점은 계획 4 평가).
금지 표현 목록은 rules/verify.yaml에서 읽는다.
"""

from __future__ import annotations

import json
import re
from datetime import date

from marvia.graph.schemas import Draft
from marvia.tools.rules import load_rules

_ARTICLE = re.compile(r"제\d+조(?:의\d+)?")  # 제241조, 제1조의4
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_KOREAN_DATE = re.compile(r"\d{1,2}월\s*\d{1,2}일")  # 11월 26일
_DAY_COUNT = re.compile(r"(\d+)\s*일")  # 30일, 24 일
# [왜] JSON 안에서 값 자리에 놓인 정수만 고른다(날짜 글 속 숫자는 빼고). 음수는 부호를 떼고 센다
_JSON_INT = re.compile(r":\s*-?(\d+)\s*[,}]")


def verify(
    draft: Draft,
    evidence: list[dict],
    calc: dict,
    cargos: list[dict],
    mask_map: dict[str, str],
    today: date,
) -> list[str]:
    """초안이 어긴 규칙을 한 문장씩 돌려준다. 빈 목록이면 통과.

    입력: draft=작성자 초안(가린 토큰 그대로), evidence=근거 묶음, calc=계산 결과,
          cargos=화물별 조회 결과, mask_map=토큰 → 실제 번호, today=오늘.
    출력: 위반 문장 목록. 작성자 프롬프트에 그대로 들어가므로 실제 번호를 넣지 않는다.
    """
    violations: list[str] = []
    by_id = {e["unit_id"]: e for e in evidence}
    cited = [by_id[c] for c in draft.citations if c in by_id]

    # 1. 인용: 근거 묶음의 unit_id만, 근거가 있으면 하나 이상, 답에 쓴 조문은 인용한 근거에 있어야 한다
    violations += [f"근거 묶음에 없는 인용: {c}" for c in draft.citations if c not in by_id]
    if evidence and not draft.citations:
        violations.append("근거가 있는데 인용이 없다")
    cited_names = " ".join(f"{e['unit_id']} {e['heading']}" for e in cited)
    for article in sorted(set(_ARTICLE.findall(draft.answer))):
        # [왜] (?!의): 인용이 제241조의2이면 답의 제241조는 그 앞부분일 뿐이라 통과시키지 않는다
        if not re.search(re.escape(article) + "(?!의)", cited_names):
            violations.append(f"인용한 근거에 없는 조문: {article}")

    # 2. 숫자: 날짜는 계산 결과·화물 단계 날짜·오늘에서만, 일수는 계산 결과·인용한 조문 글에서만
    calc_json = json.dumps(calc, ensure_ascii=False)
    stage_days = {
        c["facts"]["stage_at"][:10] for c in cargos if c.get("facts") and c["facts"].get("stage_at")
    }
    allowed_dates = set(_ISO_DATE.findall(calc_json)) | stage_days | {today.isoformat()}
    violations += [
        f"계산 결과에 없는 날짜: {d}" for d in sorted(set(_ISO_DATE.findall(draft.answer)) - allowed_dates)
    ]
    violations += [f"날짜는 YYYY-MM-DD로 쓴다: {d}" for d in _KOREAN_DATE.findall(draft.answer)]
    cited_text = " ".join(e["text"] for e in cited)
    allowed_counts = set(_JSON_INT.findall(calc_json)) | set(_DAY_COUNT.findall(cited_text))
    # [왜] "11월 26일"의 26일은 위에서 이미 걸렸다. 일수로 한 번 더 세지 않게 지우고 본다
    counts = set(_DAY_COUNT.findall(_KOREAN_DATE.sub("", draft.answer)))
    violations += [
        f"계산 결과·인용 근거에 없는 일수: {n}일" for n in sorted(counts - allowed_counts, key=int)
    ]

    # 3. 금지: 통관 가부, HS 코드 확정, 세액
    shown = "\n".join([draft.answer, *draft.next_options, draft.forwarder_message])
    for rule in load_rules("verify")["forbidden"]:
        if re.search(rule["pattern"], shown):
            violations.append(f"금지 표현: {rule['reason']}")

    # 4. 번호: 실제 번호 대신 토큰만. [주의] 위반 문장에도 실제 번호 대신 토큰을 쓴다
    violations += [
        f"실제 번호가 들어 있다 ({token} 자리)" for token, value in mask_map.items() if value in shown
    ]
    return violations
