from datetime import date
from urllib.parse import quote

from marvia.rag import fetch


def test_law_info_reads_ids_and_effective_date():
    page = (
        '<input type="hidden" id="lsiSeq" value="290673" />'
        '<input type="hidden" id="lsId" name="lsId" value="001556" />'
        "<script>var efYd = '20261002';</script>"
    )
    assert fetch.law_info(page) == ("001556", "290673", date(2026, 10, 2))


def test_law_info_returns_none_when_page_changed():
    assert fetch.law_info("<html></html>") is None


def test_rule_info_reads_id_and_effective_date():
    body = (
        '<input type="hidden" id="admRulId" name="admRulId" value="36893" /><div>[시행 2025. 12. 17.]</div>'
    )
    assert fetch.rule_info(body) == ("36893", date(2025, 12, 17))


def test_rule_search_url_drops_spaces():
    assert fetch.rule_search_url("보세화물관리에 관한 고시").endswith(quote("보세화물관리에관한고시"))


def test_view_urls_open_the_framed_viewer_of_the_same_version():
    # [왜] lsInfoR·admRulInfoR는 사이트 틀 없이 본문 조각만 준다(11-26 실측). 사람이 여는 주소는 P 쪽이다.
    #      같은 판(lsiSeq·efYd, admRulSeq)을 가리켜야 근거 글과 화면이 어긋나지 않는다
    assert fetch.law_view_url("290673", date(2026, 10, 2)) == (
        "https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=290673&efYd=20261002&ancYnChk=0"
    )
    assert (
        fetch.rule_view_url("2100000275032")
        == "https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq=2100000275032"
    )
    # 내려받는 주소(본문 조각)는 그대로다. 조문 자르기가 이 조각을 읽는다
    assert "/LSW/lsInfoR.do?" in fetch.law_body_url("290673", date(2026, 10, 2))
    assert "/LSW/admRulInfoR.do?" in fetch.rule_body_url("2100000275032")


def test_stored_corpus_links_are_viewer_pages_not_body_fragments():
    import json
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "corpus"
    urls = {
        json.loads(line)["source_url"]
        for path in (root / "units").glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    }
    urls |= {m["url"] for m in json.loads((root / "manifest.json").read_text(encoding="utf-8")) if "url" in m}
    assert urls
    bare = sorted(u for u in urls if re.search(r"/LSW/(lsInfoR|admRulInfoR)\.do", u))
    assert bare == []
    assert all(re.search(r"/LSW/(lsInfoP|admRulInfoP|lsBylInfoPLinkR)\.do\?", u) for u in urls)
