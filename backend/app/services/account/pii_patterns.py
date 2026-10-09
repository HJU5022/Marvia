"""거래처 칸과 메모 글에 쓰는 개인정보·금액 모양 (docs/specs/memory.md "넣지 않는 것").

책임: 메모장 검사(services/account/memory.py)와 서류 칸 검사(services/chat/doc_ocr.py)가 같은 모양을 쓰게 한 곳에 둔다.
두 모듈이 서로를 불러오지 않게 작은 모듈로 뺐다 (doc_ocr가 메모장 전체를 불러오지 않는다).
개인 이름은 모양으로 가를 수 없어 여기서 막지 못한다. 프롬프트(marvia-memory-write, marvia-doc-extract)가 막는다.
"""
from __future__ import annotations

import re

# 거래처 역할 목록 (Spec "메모장 종류와 템플릿" 거래처, 마이그레이션 015와 schemas/memory.py Role과 같다)
ROLES = ("포워더", "관세사", "수출자", "판매처")
# 거래처 회사 이름 글자 수 상한 (Spec 거래처 "회사 (40자)")
COMPANY_MAX = 40

# 회사·부서 전화번호: 숫자와 하이픈, 하이픈 1개 이상 (예: 051-000-0000, 1588-0000)
PHONE = re.compile(r"^\+?[0-9]{2,4}(-[0-9]{2,4}){1,3}$")
# 개인 휴대폰 (010 등). 국가번호 82는 + 없이 와도 막는다 (검증 지적: "82-10-1234-5678")
MOBILE = re.compile(r"^(\+?82-?)?0?1[016789]-")
# 글 속 어디에 있든 휴대폰 번호 모양 (할 일·걱정·선호·담당 직무 칸에 섞여 들어오는 경우)
MOBILE_IN_TEXT = re.compile(r"(?<![0-9])(\+?82-?)?0?1[016789]-?[0-9]{3,4}-?[0-9]{4}(?![0-9])")
EMAIL = re.compile(r"\S+@\S+")
# 금액: "300만원", "3백만원", "$500", "USD 500". 계좌: 마지막 묶음이 6자리 이상인 숫자 묶음(전화번호는 4자리로 끝난다) 또는 "계좌"
MONEY = re.compile(
    r"[0-9][0-9,.]*\s*[십백천만억]*\s*(원|달러)|\$\s*[0-9]|\b(USD|KRW)\s*[0-9]|계좌|account\s*no|"
    r"(?<![0-9])[0-9]{2,6}-[0-9]{2,6}-[0-9]{6,8}(?![0-9])",
    re.I)


def has_personal_or_money(text: str) -> bool:
    """이메일, 개인 휴대폰, 금액, 계좌 모양이 들어 있나 (Spec "넣지 않는 것")."""
    return bool(EMAIL.search(text) or MOBILE_IN_TEXT.search(text) or MONEY.search(text))
