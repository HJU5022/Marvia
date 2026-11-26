"""화면 입력창의 글자 수 상한이 서버 상한(rules/server.yaml)과 같은지 본다 (계획 9, R-247).

하지 않는 일: 화면 동작 시험(web/e2e가 한다).
"""

import re
from pathlib import Path

from marvia.tools.rules import load_rules

ROOT = Path(__file__).resolve().parents[1]


def test_the_composer_limit_is_the_server_limit():
    # [왜] 화면이 500자에서 막으면 서버가 받는 2000자까지 못 쓰고, 더 크면 서버가 422로 거절한다
    source = (ROOT / "web/components/Composer.tsx").read_text(encoding="utf-8")
    found = re.search(r"export const MAX_CHARS = (\d+);", source)
    assert found and int(found[1]) == load_rules("server")["request"]["max_text"]
