"""세관 정보와 선박 위치 서비스 값의 호출부호·국적 대조 (routers/agent.py에서 옮김, SDD 5.5). 국적 코드는 pycountry로 이름을 맞춘다."""

import pycountry

def _same_call_sign(a: str, b: str) -> bool:
    """호출부호 비교. 대소문자와 앞뒤 공백 차이는 같은 것으로 본다 (vessel_candidates 도구의 호출부호 필터와 같은 기준)."""
    return a.strip().upper() == b.strip().upper()

def _same_nationality(customs_nat: str, flag: str) -> bool:
    """세관 국적(두 글자 코드, 예: KR)과 ShipFinder 국적(코드 또는 영어 이름)이 같은 나라인가.

    세관 코드를 ISO 국가 이름으로 바꿔(pycountry) 정확히 같은지만 본다. 실제 응답의 ShipFinder 국적은
    ISO 이름("Korea, Republic of")과 같은 모양이었다. 글자 포함으로 비교하면 KR과 "Korea"가 안 맞고
    ("kr"이 붙어 있지 않다) NE(니제르)와 "Nigeria"는 맞아 버려서 쓰지 않는다.
    코드를 모르거나 이름이 다르게 오면 다르다고 보고, 부르는 쪽이 되묻는다 (진짜 배를 버리지 않는 쪽으로 실수).
    """
    a, b = customs_nat.strip(), flag.strip()
    if a.upper() == b.upper():
        return True  # 둘 다 코드로 온 경우 (평가셋 fixture 등)
    country = pycountry.countries.get(alpha_2=a.upper()) if len(a) == 2 else None
    if country is None:
        return False
    names = {getattr(country, attr, None) for attr in ("name", "official_name", "common_name")}
    return b.lower() in {n.lower() for n in names if n}

def _clearly_other_nationality(customs_nat: str, flag: str) -> bool:
    """세관 국적과 후보 국적이 확실히 다른 나라인가. 둘 다 나라를 알아볼 수 있을 때만 True.

    _same_nationality는 모르면 "다르다"로 답한다. 단일 후보에서는 그게 되묻기로 이어져 안전하지만, 여러 후보 중
    배를 빼는 데 쓰면 같은 실수가 진짜 배를 지운다. 그래서 빼는 쪽에는 이 함수를 쓴다: 모르면 빼지 않는다.
    """
    def country(value: str):
        v = value.strip()
        if len(v) == 2:
            return pycountry.countries.get(alpha_2=v.upper())
        for c in pycountry.countries:
            if v.lower() in {n.lower() for n in (c.name, getattr(c, "official_name", None), getattr(c, "common_name", None)) if n}:
                return c
        return None
    a, b = country(customs_nat), country(flag)
    return bool(a and b) and a.alpha_2 != b.alpha_2
