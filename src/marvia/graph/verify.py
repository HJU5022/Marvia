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
from marvia.tools.deadlines import kst_date
from marvia.tools.rules import load_rules

# 제241조, 241조, 제1조의4. [왜] "관세법 9조"처럼 "제"를 빼고 써도 같은 조문으로 본다
_ARTICLE = re.compile(r"(?<!\d)제?\s*(\d+)\s*조(?:\s*의\s*(\d+))?")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# YYYY-MM-DD가 아닌 날짜 꼴: 11월 26일, 2026.11.26, 11/26
_OTHER_DATE = re.compile(
    r"\d{1,2}월\s*\d{1,2}일|\d{4}\.\s*\d{1,2}\.\s*\d{1,2}|(?<![\d/])\d{1,2}/\d{1,2}(?![\d/])"
)
# 단위가 붙은 수: 30일, 2주, 6개월, 5년, 48시간, 1.5%
_COUNT = re.compile(r"(\d+(?:\.\d+)?)\s*(일|주|개월|년|시간|%)")
# 원 단위 금액: 120,000원, 50만원, 12만 5천원, 1억 2천만원, ₩120,000.
# [주의] 원산지·원료·원문·원칙·원하시면의 "원"은 빼고 본다
_WON_UNIT = {"억": 100_000_000, "천만": 10_000_000, "백만": 1_000_000, "만": 10_000, "천": 1_000, "백": 100}
_WON_PIECE = re.compile(r"(\d[\d,]*)\s*(억|천만|백만|만|천|백)?")
_WON = re.compile(
    r"((?:\d[\d,]*\s*(?:억|천만|백만|만|천|백)?\s*)+)원(?!산|료|문|칙|래|인|본|단|형|하)|₩\s*(\d[\d,]*)"
)
# [왜] JSON 안에서 값 자리에 놓인 수만 고른다(날짜 글 속 숫자는 빼고). 음수는 부호를 떼고 센다
_JSON_NUM = re.compile(r":\s*-?(\d+(?:\.\d+)?)\s*[,}]")


def _won(match: re.Match) -> int:
    """금액 글 하나를 원 단위 정수로 바꾼다. 12만 5천원 → 125000, 1억 2천만원 → 120000000."""
    words, symbol = match.groups()
    if symbol:  # ₩120,000
        return int(symbol.replace(",", ""))
    # [왜] "1억 2천만"은 조각(1억, 2천만)마다 수 × 단위를 더한다. 단위가 없으면 1
    return sum(int(n.replace(",", "")) * _WON_UNIT.get(unit, 1) for n, unit in _WON_PIECE.findall(words))


def _reimport_violations(shown: str, calc: dict) -> list[str]:
    """답이 말한 재수입 검사 결과가 코드 판정과 다르거나 코드 판정이 없으면 위반 문장을 돌려준다."""
    cfg = load_rules("verify")["reimport_verdicts"]
    code_verdict = (calc.get("reimport") or {}).get("verdict")
    out: list[str] = []
    # [왜] "단정할 수 없어요"처럼 결과 말 뒤에 부정이 오면 결과를 말한 것이 아니다 (문장 단위)
    #      [주의] 부정은 서술어 뒤에 온다. 결과 말 앞의 부정("지나지 않았으니 충족해요")은
    #      그 말을 지우지 못하므로 결과 말 뒤에서만 찾는다
    sentences = re.split(r"(?<=[.?!])\s+|\n", shown)
    for stated, patterns in cfg["phrases"].items():
        said = any(
            not re.search(cfg["negation"], re.split(cfg["clause_end"], s[m.end() :])[0])
            for s in sentences
            for p in patterns
            for m in re.finditer(p, s)
        )
        if stated != code_verdict and said:
            why = "코드 판정이 없다" if not code_verdict else f"코드 판정은 '{code_verdict}'이다"
            out.append(f"재수입 검사 결과를 코드 판정과 다르게 말했다 ('{stated}', {why})")
    return out


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
    주의: 정규식으로 보는 안전망이다. 법령 이름까지 맞는지(관세법 제9조와 시행령 제9조)는 보지 않는다.
    """
    violations: list[str] = []
    by_id = {e["unit_id"]: e for e in evidence}
    cited = [by_id[c] for c in draft.citations if c in by_id]

    # 1. 인용: 근거 묶음의 unit_id만, 근거가 있으면 하나 이상, 답에 쓴 조문은 인용한 근거에 있어야 한다
    violations += [f"근거 묶음에 없는 인용: {c}" for c in draft.citations if c not in by_id]
    # [왜] 근거에 물은 것이 없다고 밝힌 답에 인용을 강요하면 상관없는 근거를 끌어다 쓴다.
    #      인용이 있으면 위 줄에서 그대로 검사한다
    if evidence and not draft.citations and not draft.not_in_evidence:
        violations.append("근거가 있는데 인용이 없다")
    # [왜] 없다고 해 놓고 코드가 계산하거나 찾은 결과가 있으면 앞뒤가 안 맞는다. 기존 검증 실패 길로 간다
    if draft.not_in_evidence and (any(calc.values()) or any(c.get("facts") for c in cargos)):
        violations.append("근거에 없다고 했는데 코드가 계산하거나 찾은 결과가 있다")
    # [왜] 계산 결과 글은 코드와 rules/*.yaml이 만든 값이라, 그 안에 적힌 조문 이름은 답에 옮겨도 된다.
    #      인용(unit_id)은 여전히 근거 묶음에서만 온다
    calc_json = json.dumps(calc, ensure_ascii=False)
    cited_names = " ".join(f"{e['unit_id']} {e['heading']}" for e in cited) + " " + calc_json
    articles = {f"제{n}조" + (f"의{sub}" if sub else "") for n, sub in _ARTICLE.findall(draft.answer)}
    for article in sorted(articles):
        # [왜] (?!의): 인용이 제241조의2이면 답의 제241조는 그 앞부분일 뿐이라 통과시키지 않는다
        if not re.search(re.escape(article) + "(?!의)", cited_names):
            violations.append(f"인용한 근거에 없는 조문: {article}")

    # 2. 숫자: 날짜는 계산 결과·화물 단계 날짜·인용한 근거의 시행일·오늘에서만,
    #    단위가 붙은 수는 계산 결과·인용한 조문 글에서만, 금액은 계산 결과에서만
    stage_days = {
        kst_date(c["facts"]["stage_at"]).isoformat()
        for c in cargos
        if c.get("facts") and c["facts"].get("stage_at")
    }
    effective_days = {str(e["effective"]) for e in cited}
    allowed_dates = set(_ISO_DATE.findall(calc_json)) | stage_days | effective_days | {today.isoformat()}
    violations += [
        f"계산 결과에 없는 날짜: {d}" for d in sorted(set(_ISO_DATE.findall(draft.answer)) - allowed_dates)
    ]
    violations += [f"날짜는 YYYY-MM-DD로 쓴다: {d}" for d in _OTHER_DATE.findall(draft.answer)]
    calc_numbers = {float(n) for n in _JSON_NUM.findall(calc_json)}
    # [왜] 단위가 붙은 수는 인용한 조문 글과 계산 결과 글(코드가 쓴 "5년" 같은 단서)에서
    #      같은 단위로만 허용한다
    written = " ".join(e["text"] for e in cited) + " " + calc_json
    allowed_pairs = {(float(n), unit) for n, unit in _COUNT.findall(written)}
    # [왜] 날짜 꼴은 위에서 이미 걸렸다. "11월 26일"의 26일을 일수로 한 번 더 세지 않게 지우고 본다
    plain = _OTHER_DATE.sub("", draft.answer)
    seen: set[str] = set()
    for n, unit in _COUNT.findall(plain):
        value = float(n)
        if unit == "년" and value >= 1900:
            continue  # 2026년 같은 연도는 수가 아니다
        if unit == "%":
            # [왜] 계산 결과의 율은 0.015처럼 소수다. 답에는 1.5%로 쓴다
            ok = any(round(value, 6) == round(x * 100, 6) for x in calc_numbers)
        else:
            # [왜] 계산 결과의 숫자 값(남은 날·넘긴 날)은 날 수라 "일"에만 쓴다. 24개월로 옮기면 틀린 값이다
            ok = (unit == "일" and value in calc_numbers) or (value, unit) in allowed_pairs
        if not ok and n + unit not in seen:
            seen.add(n + unit)
            violations.append(f"계산 결과·인용 근거에 없는 수: {n}{unit}")

    # 3. 금지: 통관 가부, HS 코드 확정 (rules/verify.yaml), 세액 (계산 결과에 없는 금액)
    shown = "\n".join([draft.answer, *draft.next_options, draft.forwarder_message])
    for rule in load_rules("verify")["forbidden"]:
        if re.search(rule["pattern"], shown):
            violations.append(f"금지 표현: {rule['reason']}")
    # [왜] 가산세 상한처럼 계산 결과에 있는 금액은 옮겨 쓴 값이라 된다.
    #      그 밖의 금액은 세액을 계산해 말한 것이다
    if any(_won(m) not in calc_numbers for m in _WON.finditer(shown)):
        violations.append("금지 표현: 세액을 계산해 말했다")

    # 3-1. 재수입 검사 결과: 코드 판정(calc.reimport.verdict)과 같은 말만 한다 (설계 7.1)
    violations += _reimport_violations(shown, calc)

    # 4. 번호: 실제 번호 대신 토큰만. [주의] 위반 문장에도 실제 번호 대신 토큰을 쓴다
    violations += [
        f"실제 번호가 들어 있다 ({token} 자리)" for token, value in mask_map.items() if value in shown
    ]
    return violations
