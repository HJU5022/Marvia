from datetime import date
from pathlib import Path

from marvia.rag.lawpage import clean, split_units

PAGE = (Path(__file__).parent / "fixtures" / "law_sample.html").read_text(encoding="utf-8")


def _units():
    return split_units(
        PAGE,
        doc_id="L001556",
        law_name="관세법",
        kind="법률",
        effective=date(2026, 10, 2),
        source_url="https://www.law.go.kr/test",
    )


def _by_label():
    return {u.unit_id.split("#")[1]: u for u in _units()}


def test_one_unit_per_leaf_and_deleted_parts_skipped():
    # 제3조 ③항과 제4조는 "삭제"라 단위가 없다
    assert list(_by_label()) == [
        "제1조",
        "제2조.1호",
        "제2조.4호.가목",
        "제2조.4호.나목",
        "제3조.1항",
        "제3조.2항",
        "제19조의2.1항.3의2호",
    ]


def test_unit_id_has_doc_and_effective_date():
    assert _units()[0].unit_id == "L001556@20261002#제1조"


def test_leaf_text_keeps_parent_lines():
    text = _by_label()["제2조.4호.가목"].text
    assert text.startswith("제2조(정의) 이 법에서 사용하는 용어의 뜻은 다음과 같다. 4. “외국물품”이란")
    assert text.endswith("가. 외국으로부터 우리나라에 도착한 물품")


def test_heading_follows_chapter_and_section():
    assert (
        _by_label()["제3조.1항"].heading
        == "관세법 > 제1장 총칙 > 제2절 법 적용의 원칙 등 > 제3조(관세징수의 우선)"
    )


def test_sub_items_stay_inside_item():
    assert _by_label()["제19조의2.1항.3의2호"].text.endswith(
        "1) 화주의 위임에 따라 해외 판매자로부터 물품의 구매를 대행하는 것"
    )


def test_clean_removes_notes_and_joins_links():
    fragment = (
        '나. <a class="link sfon2">제241조</a><a class="link sfon3">제1항</a>에 따른 '
        '<span class="sfon">&lt;개정 2020. 12. 22.&gt;</span>'
    )
    assert clean(fragment) == "나. 제241조제1항에 따른"
