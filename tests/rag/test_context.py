from marvia.rag.context import Context, make_contextualizer


def test_contextualizer_sends_heading_and_text(make_unit):
    prompts = []

    def ask(prompt: str) -> Context:
        prompts.append(prompt)
        return Context(sentence="수입신고 시기를 정한 조문이다.")

    unit = make_unit("제1조", "수입신고는 입항 후에 한다")
    assert make_contextualizer(ask)(unit) == "수입신고 시기를 정한 조문이다."
    assert "<heading>\n시험법 > 제1조\n</heading>" in prompts[0]
    assert "<provision>\n수입신고는 입항 후에 한다\n</provision>" in prompts[0]
