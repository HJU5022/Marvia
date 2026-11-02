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
