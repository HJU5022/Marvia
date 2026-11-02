from marvia.rag.index import embed_text, index_units


def test_embed_text_joins_heading_context_and_text(make_unit):
    unit = make_unit("제1조", "수입신고는 입항 후에 한다")
    assert embed_text(unit, "") == "시험법 > 제1조\n수입신고는 입항 후에 한다"
    assert embed_text(unit, "맥락") == "시험법 > 제1조\n맥락\n수입신고는 입항 후에 한다"


def test_index_twice_keeps_one_row_per_unit(db, make_unit, fake_embed):
    units = [make_unit("제1조", "수입신고는 입항 후에 한다"), make_unit("제2조", "정밀검사를 면제할 수 있다")]
    assert index_units(db, units, fake_embed) == 2
    index_units(db, units[:1], fake_embed)  # 같은 unit_id를 다시 넣는다
    assert db.execute("SELECT count(*) FROM corpus_units").fetchone()[0] == 2


def test_keywords_column_finds_article_number(db, make_unit, fake_embed):
    index_units(db, [make_unit("제1조", "제241조에 따른 수입신고")], fake_embed)
    sql = "SELECT count(*) FROM corpus_units WHERE keywords @@ websearch_to_tsquery('simple', '제241조')"
    assert db.execute(sql).fetchone()[0] == 1


def test_context_is_stored_and_searchable(db, make_unit, fake_embed):
    index_units(
        db, [make_unit("제1조", "수입신고는 입항 후에 한다")], fake_embed, lambda unit: "통관 첫 단계"
    )
    row = db.execute("SELECT context FROM corpus_units").fetchone()
    assert row[0] == "통관 첫 단계"
    sql = "SELECT count(*) FROM corpus_units WHERE keywords @@ websearch_to_tsquery('simple', '통관')"
    assert db.execute(sql).fetchone()[0] == 1
