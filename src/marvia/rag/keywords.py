"""한국어 글을 키워드 검색용 낱말로 나눈다 (설계 5.3: kiwipiepy로 나눠 tsvector('simple')에 넣는다).

하지 않는 일: 검색. 색인할 때와 질문할 때 같은 함수로 낱말을 만들어야 서로 맞는다.
"""

from __future__ import annotations

import re
from functools import cache
from typing import cast

from kiwipiepy import Kiwi, Token

from marvia.tools.rules import load_rules

# [왜] Kiwi는 "제241조"를 제/241/조로 쪼갠다. 조문 번호는 통째로 따로 남긴다
ARTICLE_REF = re.compile(r"제\d+조(?:의\d+)?")


@cache
def _kiwi() -> Kiwi:
    """[왜] Kiwi는 처음 만들 때 사전을 읽느라 1~2초 걸린다. 한 번만 만든다."""
    return Kiwi()


def keywords(text: str) -> list[str]:
    """글에서 조문 번호와 명사·동사 어간 같은 내용어를 뽑는다. 중복은 남긴다(많이 나온 낱말이 점수가 높다)."""
    tags = set(load_rules("rag")["keyword_tags"])
    # [왜] 불규칙 활용은 "VV-I"처럼 붙임표 뒤에 표시가 붙는다. 앞부분만 본다
    # [왜] 글 하나를 넣으면 Token 목록이 온다. 여러 글을 넣는 경우와 타입 표시가 섞여 있어 pyright에 알려 준다
    tokens = cast(list[Token], _kiwi().tokenize(text))
    words = [t.form for t in tokens if t.tag.split("-")[0] in tags]
    return ARTICLE_REF.findall(text) + words
