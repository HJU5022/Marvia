"""별표 단위 파일의 정답 열쇠 시험 (계획 3b Task 1, 사전 부검 F2·F3). 키·DB 없이 돈다."""

from marvia.eval.dataset import CORPUS_UNITS
from marvia.eval.metrics import matches
from marvia.eval.run import UNIT_ID
from marvia.rag.index import read_units
from marvia.rag.provision import parse_label

# rules/reimport.yaml·deadlines.yaml이 쓰는 이름표 → 그 단위 글에 있어야 할 구절 (11-06 원문과 대조해 손으로
# 적음)
LABELS = {
    "시행규칙 별표 9 제2호가목7)": "동일사 동일수입식품등의 조건을 충족하는 것으로서 다시 수입하는",
    "시행규칙 별표 9 제2호가목12)": "외국으로부터 반송된 수입식품등",
    "시행규칙 별표 9 제2호다목2)나)": "합산하여 5회까지",
    "시행규칙 별표 9 제2호다목5)": "반려된 횟수를 합산하여 3회 이상",
    "시행규칙 별표 9 제2호라목": "무작위표본검사란",
    "시행규칙 별표 9 제3호가목5)": "미만으로 수입되어 정밀검사한 동일사",
    "시행규칙 별표 10 제1호가목1)": "최초로 수입된 수입식품등",
    "시행규칙 별표 10 제1호가목3)": "기간이 경과하였거나",
    "시행규칙 별표 10 제1호나목": "외국으로부터 반송된 수입식품등",
    "시행규칙 별표 10 제2호나목": "부적합 처분을 받은 후 5년 이내",
    "시행규칙 별표 10 제3호가목": "제26조제1항제3호에 해당하는 자",
    "시행규칙 별표 10 제3호나목": "유해물질이 검출된",
    "시행규칙 별표 10 제4호다목": "생산국ㆍ품명ㆍ수출업소 및 포장장소가 같은 것",
    "시행규칙 별표 10 제4호마목": "제조국ㆍ해외제조업소ㆍ재질 및 바탕색상이 같은 것",
    "보세화물관리에 관한 고시 별표 1": "지정장치장",
}


def _annex_units():
    return [u for u in read_units(CORPUS_UNITS) if u.kind == "별표"]


def test_every_label_the_rules_use_has_annex_units_with_its_text():
    units = _annex_units()
    for label, phrase in LABELS.items():
        parsed = parse_label(label)
        assert parsed is not None, label
        law, key = parsed
        hits = [u for u in units if u.law_name == law and matches(u.unit_id.split("#")[1], [key])]
        assert hits and any(phrase in u.text for u in hits), label


def test_annex_unit_ids_survive_the_eval_regex_and_prefix_rule():
    units = _annex_units()
    assert units
    for u in units:
        assert UNIT_ID.findall(f"[{u.unit_id}] {u.heading}") == [u.unit_id]
    assert matches("L012500@20260930#별표9.2호.가목.7)", ["L012500@20260930#별표9.2호.가목"])
    assert not matches("L012500@20260930#별표10.1호.가목.1)", ["L012500@20260930#별표1"])
