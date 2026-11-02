from marvia.rag.keywords import keywords


def test_keeps_nouns_and_drops_particles():
    words = keywords("재수입 정밀검사 면제 조건은?")
    assert {"수입", "정밀", "검사", "면제", "조건"} <= set(words)
    assert "은" not in words


def test_keeps_article_number_whole():
    assert "제241조" in keywords("제241조에 따른 수입신고")
