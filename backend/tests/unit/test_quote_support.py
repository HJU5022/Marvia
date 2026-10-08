"""V14 받침 검사(validate.quote_supports) 시험. 근거 조각이 원문에 있다는 것(quote_found)과 별개로,
그 조각이 답과 상관있는지를 본다. 앞의 두 사례는 실제 웹 검색 결과와 답이다."""
from backend.app.services.judge import validate

DO_SOURCE = ("D/O는 선사나 포워더가 발행한다. 실무적으로 이러한 비용을 선사나 포워더에 지불하면, 선사나 포워더는 화물인도지시서를 발행하여 "
             "수입물품을 찾아갈 수 있도록 합니다. 해상운임과 부대비용을 정산하고 원본 B/L 제출이나 서렌더 처리를 해야 합니다.")
DO_QUOTE = "실무적으로 이러한 비용을 선사나 포워더에 지불하면, 선사나 포워더는 화물인도지시서를 발행하여 수입물품을 찾아갈 수 있도록 합니다."
DO_REPLY = ("화물인도지시서를 받으려면 먼저 도착예정통지서를 확인하고 해상운임과 부대비용을 정산해야 합니다. "
            "또한 선하증권 원본 제출이나 서렌더 처리가 완료되어야 하며, 관세사를 통해 선사에 발급을 신청하게 됩니다.")

BL_SOURCE = "Master B/L은 선사가 주체가 되어 발행하는 B/L이고,House B/L은 포워더가 화주에게 발행하는 B/L입니다."
BL_REPLY = "마스터 B/L은 선사가 포워더에게 발행하는 선하증권이고, 하우스 B/L은 포워더가 실제 화주에게 발행하는 선하증권입니다."
FAR = "아무 관련 없는 문장이 길게 이어진다. " * 30


def test_real_replies_pass():
    assert validate.quote_supports(DO_REPLY, DO_QUOTE, DO_SOURCE, "D/O를 받기까지 절차가 어떻게 돼?")
    assert validate.quote_supports(BL_REPLY, BL_SOURCE, BL_SOURCE, "마스터 B/L이랑 하우스 B/L이 뭐야?")


def test_unrelated_quote_is_rejected():
    quote = "선박의 총톤수는 항만 사용료를 정하는 기준이다."
    assert not validate.quote_supports(DO_REPLY, quote, quote + FAR + DO_QUOTE, "D/O를 받기까지 절차가 어떻게 돼?")


def test_quote_sharing_only_the_question_words_is_rejected():
    quote = "화물인도지시서는 서류의 이름이다."
    assert not validate.quote_supports(DO_REPLY, quote, quote + FAR, "화물인도지시서 받기까지 절차가 어떻게 돼?")


def test_short_reply_is_not_judged():
    assert validate.quote_supports("네, 맞습니다.", "전혀 다른 글 전혀 다른 글", "전혀 다른 글 전혀 다른 글")


def test_check_chat_reply_flags_unsupported_quote():
    quote = "선박의 총톤수는 항만 사용료를 정하는 기준이다."
    found = validate.check_chat_reply(DO_REPLY, quote + FAR + DO_REPLY, "D/O 절차가 뭐야?", None, quote, quote + FAR)
    assert [v.rule for v in found if v.rule == "V14"]


def test_check_chat_reply_passes_supported_quote():
    found = validate.check_chat_reply(DO_REPLY, DO_SOURCE + DO_REPLY, "D/O를 받기까지 절차가 어떻게 돼?", None, DO_QUOTE, DO_SOURCE)
    assert not [v for v in found if v.rule == "V14"]
