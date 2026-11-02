"""국가법령정보센터 페이지 주소를 만들고, 받은 페이지에서 번호·시행일을 읽는다 (설계 5.1, 2절 결정 15).

하지 않는 일: 인터넷 호출(scripts/fetch_corpus.py가 한다), 조문 자르기(lawpage.py).
[주의] 웹 페이지 구조에 기댄다(10-30 확인). 구조가 바뀌면 여기 함수가 None을 돌려주고
스크립트가 MISS로 알린다.
"""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import quote

from marvia.rag.lawpage import clean

SITE = "https://www.law.go.kr"


def law_search_url(name: str) -> str:
    """법령 이름으로 그 법령의 정보 페이지(최신 공포본) 주소를 만든다."""
    return f"{SITE}/LSW/lsInfoP.do?lsNm={quote(name)}"


def law_body_url(seq: str, effective: date) -> str:
    """판 번호(lsiSeq)와 시행일로 조문 본문 페이지 주소를 만든다. ancYnChk=0은 시행일 기준."""
    return (
        f"{SITE}/LSW/lsInfoR.do?lsiSeq={seq}&chrClsCd=010202&urlMode=lsInfoP"
        f"&efYd={effective:%Y%m%d}&ancYnChk=0"
    )


def rule_search_url(name: str) -> str:
    """고시·규정 이름으로 행정규칙 페이지 주소를 만든다. [왜] 이 주소는 이름에서 띄어쓰기를 빼야 찾는다"""
    return f"{SITE}/{quote('행정규칙')}/{quote(name.replace(' ', ''))}"


def rule_body_url(seq: str) -> str:
    """행정규칙 판 번호(admRulSeq)로 본문 페이지 주소를 만든다."""
    return f"{SITE}/LSW/admRulInfoR.do?admRulSeq={seq}"


def law_info(page: str) -> tuple[str, str, date] | None:
    """법령 정보 페이지에서 (법령ID, 판 번호, 시행일)을 읽는다. 못 읽으면 None."""
    law_id = re.search(r'id="lsId" name="lsId" value="(\d+)"', page)
    seq = re.search(r'id="lsiSeq" value="(\d+)"', page)
    effective = re.search(r"efYd = '(\d{4})(\d{2})(\d{2})'", page)
    if not (law_id and seq and effective):
        return None
    return law_id[1], seq[1], date(int(effective[1]), int(effective[2]), int(effective[3]))


def rule_seq(page: str) -> str | None:
    """행정규칙 페이지에서 판 번호(admRulSeq)를 읽는다. 못 읽으면 None."""
    m = re.search(r"admRulSeq[\"']?\s*[=:,]\s*[\"']?(\d{10,})", page)
    return m[1] if m else None


def rule_info(body: str) -> tuple[str, date] | None:
    """행정규칙 본문 페이지에서 (행정규칙ID, 시행일)을 읽는다. 못 읽으면 None."""
    rule_id = re.search(r'id="admRulId" name="admRulId" value="(\d+)"', body)
    # [왜] 시행일은 숨은 칸이 없고 제목 아래 "[시행 2025. 12. 17.]" 글로만 있다. 앞부분만 보면 된다
    effective = re.search(r"시행\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.", clean(body[:30000]))
    if not (rule_id and effective):
        return None
    return rule_id[1], date(int(effective[1]), int(effective[2]), int(effective[3]))


def title(page: str) -> str:
    """페이지의 첫 h2 제목. 받은 문서가 맞는지 사람이 볼 때 쓴다."""
    m = re.search(r"<h2[^>]*>(.*?)</h2>", page, re.S)
    return clean(m[1]) if m else ""
