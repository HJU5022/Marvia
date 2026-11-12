"""검색 전용 측정의 계산 규칙 시험 (scripts/retrieval_check.py가 쓰는 marvia.eval.retrieval). 키 없이 돈다."""

import json
import subprocess
import sys
from datetime import date
from types import SimpleNamespace

import pytest

from marvia.eval.dataset import ROOT, SET_PATH, SET_V2_PATH, file_sha256
from marvia.eval.metrics import matches, mrr, recall_at_k
from marvia.eval.retrieval import (
    article_group,
    capped,
    load_items,
    measure,
    rank_item,
    summarize_layers,
    targets,
)
from marvia.rag.models import Evidence

D = "L1@20260101#"


@pytest.mark.parametrize(
    ("unit_id", "group"),
    [
        ("A36893@20251217#제26조.1항.8호", "A36893@20251217#제26조.1항"),
        ("L001556@20261002#제237조.1항.4의2호", "L001556@20261002#제237조.1항"),
        ("L012500@20260930#제32조", "L012500@20260930#제32조"),
        ("X@1#제2조.1호.라목", "X@1#제2조"),  # 항 없이 호가 바로 오면 조까지만
        ("X@1#제5조의2.3항.1호.가목", "X@1#제5조의2.3항"),
        ("L012500@20260930#별표9.2호.가목.7)", "L012500@20260930#별표9.2호.가목"),  # 별표는 세 마디까지
        ("A36852@20260224#별표1.4호", "A36852@20260224#별표1.4호"),
    ],
)
def test_units_are_grouped_by_article_and_paragraph(unit_id, group):
    assert article_group(unit_id) == group


def test_capped_moves_the_extra_units_of_one_article_to_the_back():
    ranked = ["X@1#제1조.1항.1호", "X@1#제1조.1항.2호", "X@1#제1조.1항.3호", "X@1#제2조"]
    assert capped(ranked, 2) == ["X@1#제1조.1항.1호", "X@1#제1조.1항.2호", "X@1#제2조", "X@1#제1조.1항.3호"]
    assert capped(ranked, 0) == ranked  # 0이면 묶지 않는다


def test_targets_count_also_ok_as_another_answer_and_strict_keeps_only_the_source_unit():
    plain = {"gold": [D + "제1조", D + "제2조"]}
    assert targets(plain, strict=False) == [[D + "제1조"], [D + "제2조"]]  # 정답마다 따로 찾아야 한다
    wide = {"gold": [D + "제1조"], "also_ok": [D + "제9조"], "source_unit": D + "제1조.1항"}
    assert targets(wide, strict=False) == [[D + "제1조", D + "제9조"]]  # 둘 가운데 하나만 찾아도 맞다
    assert targets(wide, strict=True) == [[D + "제1조.1항"]]
    assert targets(plain, strict=True) == targets(plain, strict=False)  # 질문을 쓴 단위가 없으면 같다


def row(id: str, layer: str, ranked: list[str], cand: list[str] | None = None, **item) -> dict:
    return {"id": id, "layer": layer, "retrieved": ranked, "cand": cand or ranked, **item}


def test_summary_gives_unit_article_and_strict_values_per_layer_and_overall():
    rows = [
        # 정답 조문의 다른 호를 2위로 찾았다: 단위 기준으로 맞고, 질문을 쓴 단위(엄격)로는 틀리다
        row(
            "A1", "a", [D + "제9조", D + "제1조.1항.2호"], gold=[D + "제1조"], source_unit=D + "제1조.1항.1호"
        ),
        # 후보에는 있었지만 상위 k 밖이다. 같은 조·항의 호들이 앞을 차지했다
        row(
            "B1",
            "b",
            [D + "제3조.1항.1호", D + "제3조.1항.2호", D + "제2조"],
            cand=[D + "제3조.1항.1호", D + "제3조.1항.2호", D + "제2조"],
            gold=[D + "제2조"],
        ),
    ]
    out = summarize_layers(rows, k=2)
    assert out["a"] == {
        "n": 1,
        "cand_recall": 1.0,
        "cand_mean": 2.0,
        "unit_r_at_k": 1.0,
        "unit_mrr": 0.5,
        "article_r_at_k": 1.0,
        "article_mrr": 0.5,
        "strict_r_at_k": 0.0,
        "strict_mrr": 0.0,
    }
    # 조문 기준: 제3조.1항의 두 호가 한 묶음이 되어 제2조가 2위로 올라온다
    assert (out["b"]["unit_r_at_k"], out["b"]["article_r_at_k"], out["b"]["article_mrr"]) == (0.0, 1.0, 0.5)
    assert out["b"]["cand_recall"] == 1.0
    assert out["all"]["n"] == 2 and out["all"]["unit_r_at_k"] == 0.5


def test_unit_values_equal_the_eval_metrics_when_no_item_has_another_answer():
    rows = [
        row("R1", "set", [D + "제1조.1항", D + "제5조"], gold=[D + "제1조", D + "제7조"]),
        row("R2", "set", [D + "제8조", D + "제2조"], gold=[D + "제2조"]),
    ]
    items = {r["id"]: SimpleNamespace(gold=r["gold"]) for r in rows}
    out = summarize_layers(rows, k=8)["all"]
    assert out["unit_r_at_k"] == recall_at_k(rows, items, 8)["value"]
    assert out["unit_mrr"] == mrr(rows, items)["value"]


def test_importer_layer_is_added_when_some_questions_are_not_an_importers():
    rows = [
        row("B1", "b", [D + "제1조"], gold=[D + "제1조"]),
        row("B2", "b", [D + "제9조"], gold=[D + "제2조"], importer_question=False),
    ]
    out = summarize_layers(rows, k=8)
    assert out["b"]["n"] == 2 and out["b_importer"]["n"] == 1 and out["b_importer"]["unit_r_at_k"] == 1.0


def test_load_items_reads_the_retrieval_sets_and_the_gold_items_of_the_eval_set():
    items, as_of, name = load_items(SET_PATH.parent / "rset_v1.yaml")
    assert (len(items), as_of, name) == (60, date(2026, 11, 6), "rset_v1")
    assert {i["layer"] for i in items} == {"a", "b", "c"} and all(i["query"] and i["gold"] for i in items)
    v2, v2_as_of, v2_name = load_items(SET_V2_PATH)
    assert len(v2) == 12 and v2_name == "v2" and {i["layer"] for i in v2} == {"set"}
    # [왜] 평가셋의 also_ok는 "인용해도 틀리지 않은 단위"일 뿐 검색 정답이 아니다.
    #      검색 전용셋의 also_ok와 뜻이 다르다
    assert all("also_ok" not in i for i in v2)


def unit(n: int, origin: str = "hybrid") -> Evidence:
    return Evidence(
        unit_id=f"{D}제{n}조",
        law_name="시험법",
        heading=f"시험법 > 제{n}조",
        effective=date(2026, 1, 1),
        source_url="https://example.test",
        text=f"제{n}조 본문",
        score=0.0,
        origin=origin,
    )


def test_rank_item_reranks_all_candidates_or_keeps_their_order_and_applies_the_cap():
    cands = [unit(1), unit(2, "graph"), unit(3, "provision")]
    scores = lambda query, texts: [0.2, 0.9, 0.5]  # noqa: E731
    on = rank_item("질의", cands, scores, rerank=True, cap=0)
    assert on == {
        "cand": [D + "제1조", D + "제2조", D + "제3조"],
        "ranked": [D + "제2조", D + "제3조", D + "제1조"],  # 점수 내림차순 (graph/rag.py top_ranked와 같다)
        "graph": 1,
        "provision": 1,
    }
    # 측정 길의 리랭커도 제품 길(top_ranked)과 같은 글을 읽는다: 법령 이름 + 본문
    read = []
    rank_item("질의", cands, lambda query, texts: read.extend(texts) or [0.1, 0.2, 0.3], rerank=True, cap=0)
    assert read[0] == "시험법\n제1조 본문"
    off = rank_item("질의", cands, scores, rerank=False, cap=0)
    assert off["ranked"] == off["cand"]
    assert rank_item("질의", [], scores, rerank=True, cap=0)["ranked"] == []


def test_measure_runs_every_item_and_keeps_only_ids_in_the_rows():
    items = [
        {"id": "A1", "layer": "a", "query": "시험법 제3조 내용", "gold": [D + "제3조"]},
        {
            "id": "B1",
            "layer": "b",
            "query": "반입은 언제",
            "gold": [D + "제9조"],
            "source_unit": D + "제9조.1항",
        },
    ]
    asked = []

    def search(query: str, as_of: date) -> list[Evidence]:
        asked.append((query, as_of))
        return [unit(1), unit(2), unit(3, "provision")]

    rows = measure(items, date(2026, 11, 6), search, lambda q, texts: [0.1, 0.2, 0.9], rerank=True, cap=0)
    assert asked == [("시험법 제3조 내용", date(2026, 11, 6)), ("반입은 언제", date(2026, 11, 6))]
    assert rows[0] == {
        "id": "A1",
        "layer": "a",
        "gold": [D + "제3조"],
        "cand": [D + "제1조", D + "제2조", D + "제3조"],
        "retrieved": [D + "제3조", D + "제2조", D + "제1조"],
        "graph": 0,
        "provision": 1,
    }
    assert rows[1]["source_unit"] == D + "제9조.1항" and "query" not in rows[1]  # 줄에는 글을 두지 않는다
    assert "본문" not in str(rows)
    out = summarize_layers(rows, k=8)
    assert (out["a"]["unit_r_at_k"], out["b"]["unit_r_at_k"], out["all"]["unit_mrr"]) == (1.0, 0.0, 0.5)


def check(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/retrieval_check.py", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_script_stops_before_any_key_is_needed_when_arguments_are_wrong(tmp_path):
    assert "--out과 --tag" in check("--set", "rset_v1").stderr
    assert "문항 파일이 없다" in check("--set", "nope", "--tag", "t", "--out", str(tmp_path)).stderr
    (tmp_path / "retrieval-t.json").write_text("{}", encoding="utf-8")
    kept = check("--set", "rset_v1", "--tag", "t", "--out", str(tmp_path))
    assert kept.returncode != 0 and "이미 있다" in kept.stderr  # 앞서 잰 결과를 덮어쓰지 않는다
    assert check("--leg", "graph").returncode != 0  # 다리는 rrf, vector, keyword뿐이다


def test_same_compares_the_rankings_of_two_result_files(tmp_path):
    tail = [f"t{n}" for n in range(8)]
    # b는 상위 8개 뒤(직접 길의 줄에만 있는 꼬리)가 달라도 같다고 본다
    for name, top in (("a", ["u1", *tail]), ("b", ["u1", *tail, "꼬리"]), ("c", ["u2", *tail])):
        rows = [{"id": "R1", "retrieved": top}]
        (tmp_path / f"{name}.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
    same = check("--same", str(tmp_path / "a.json"), str(tmp_path / "b.json"))
    assert same.returncode == 0 and "같음" in same.stdout
    differs = check("--same", str(tmp_path / "a.json"), str(tmp_path / "c.json"))
    assert differs.returncode == 1 and "다름: R1" in differs.stdout


def test_same_says_when_article_values_were_computed_over_different_ranges(tmp_path):
    # [왜] 직접 길은 리랭커가 줄 세운 후보 전체를 조·항으로 묶고, MCP 길은 돌려받은 상위 n개만 묶는다.
    #      단위 기준 순위가 같아도 조문 기준 값은 다를 수 있어 나란히 견주면 안 된다
    rows = [{"id": "R1", "retrieved": ["u1"]}]
    for name, scope in (("direct", "candidates"), ("mcp", "top_n"), ("old", None)):
        meta = {"article_scope": scope} if scope else {}
        (tmp_path / f"{name}.json").write_text(json.dumps({"meta": meta, "rows": rows}), encoding="utf-8")
    mixed = check("--same", str(tmp_path / "direct.json"), str(tmp_path / "mcp.json"))
    assert mixed.returncode == 0 and "같음" in mixed.stdout
    assert "조문 기준 값은 견주지 않는다" in mixed.stdout and "candidates" in mixed.stdout
    alike = check("--same", str(tmp_path / "direct.json"), str(tmp_path / "direct.json"))
    assert "조문 기준" not in alike.stdout
    # 옛 결과 파일(칸 없음)은 직접 길에서 후보 전체로 잰 것이다
    assert (
        "조문 기준" not in check("--same", str(tmp_path / "old.json"), str(tmp_path / "direct.json")).stdout
    )


def test_the_article_scope_names_follow_the_search_path():
    from marvia.eval.retrieval import article_scope

    assert article_scope(via_mcp=False) == "candidates" and article_scope(via_mcp=True) == "top_n"


STORED = sorted((ROOT / "eval" / "results").glob("retrieval-*.json"))
SET_FILES = {"v2": "set_v2.yaml"} | {
    name: f"{name}.yaml" for name in ("rset_v1", "rset_a2", "rset_a3", "rset_b2", "rset_a4")
}


PATH_SETS = ("v2", "rset_v1")  # 직접 길과 MCP 길을 한 번씩 더 잰 묶음 (기본 설정)


def stored(name: str) -> dict:
    return json.loads((ROOT / "eval" / "results" / f"retrieval-{name}.json").read_text(encoding="utf-8"))


def test_the_stored_retrieval_results_cover_every_set_and_setting_at_one_commit():
    metas = [json.loads(path.read_text(encoding="utf-8"))["meta"] for path in STORED]
    # 공식 묶음: 묶음 여섯 × 설정 넷(기본, 벡터만, 키워드만, 리랭커 끔). 길 대조: 묶음 둘 × 길 둘
    official = [m for m in metas if not m["tag"].endswith(("-direct", "-mcp"))]
    paths = [m for m in metas if m["tag"].endswith(("-direct", "-mcp"))]
    legs = (("rrf", "on"), ("vector", "on"), ("keyword", "on"), ("rrf", "off"))
    wanted = {(s, leg, rr) for s in SET_FILES for leg, rr in legs}
    assert {(m["set"], m["leg"], m["rerank"]) for m in official} == wanted and len(official) == 24
    assert sorted(m["tag"] for m in paths) == sorted(
        f"{s}-{via}" for s in PATH_SETS for via in ("direct", "mcp")
    )
    assert all(m["rag_via"] == "direct" for m in official)  # 공식 값은 직접 길로 잰다 (평가 실행과 같다)
    assert len({m["commit"] for m in metas}) == 1  # 한 커밋에서 잰 값끼리만 견준다
    for meta in metas:
        # [왜] 색인이 단위 파일과 다르거나 문제가 적힌 측정은 공식 값으로 두지 않는다
        assert meta["problems"] == [] and meta["index_units"] == meta["file_units"]
        # 잰 문항 파일이 지금 저장소의 파일과 같다(문항이나 정답이 바뀌면 다시 잰다)
        assert meta["set_sha256"] == file_sha256(ROOT / "eval" / SET_FILES[meta["set"]])


def gold_ranks(row: dict, k: int) -> list[int | None]:
    """정답마다 상위 k 안의 순위(없으면 None). also_ok가 있으면 그 가운데 하나를 찾아도 정답이다."""
    return [
        next((n for n, u in enumerate(row["retrieved"][:k], 1) if matches(u, alt)), None)
        for alt in targets(row, strict=False)
    ]


@pytest.mark.parametrize("name", PATH_SETS)
def test_the_default_mcp_path_finds_the_gold_units_at_the_same_ranks_as_the_direct_path(name):
    # [왜] 평가는 직접 길로 돈다(그래프 후보를 리랭커 앞에서 세려고). 제품의 기본 길은 MCP다.
    #      두 길이 같은 검색 함수를 타는지를 같은 커밋·같은 색인에서 한 번씩 재어 둔 결과로 확인한다
    direct, mcp = stored(f"{name}-direct"), stored(f"{name}-mcp")
    assert (direct["meta"]["rag_via"], mcp["meta"]["rag_via"]) == ("direct", "mcp")
    k = direct["meta"]["k"]
    assert [r["id"] for r in direct["rows"]] == [r["id"] for r in mcp["rows"]]
    for one, other in zip(direct["rows"], mcp["rows"], strict=True):
        assert gold_ranks(one, k) == gold_ranks(other, k), one["id"]
    for layer, summary in direct["summary"].items():
        for key in ("unit_r_at_k", "unit_mrr", "strict_r_at_k", "strict_mrr"):
            assert summary[key] == mcp["summary"][layer][key], (layer, key)
    # [주의] 상위 k의 순서까지 같다고 보지 않는다. 리랭커 점수와 질의 임베딩이 호출마다 조금 흔들려
    #        정답이 아닌 이웃 단위의 자리가 바뀐다


@pytest.mark.parametrize("name", PATH_SETS)
def test_article_values_of_the_two_paths_are_marked_as_not_comparable(name):
    direct, mcp = stored(f"{name}-direct"), stored(f"{name}-mcp")
    # [왜] 조문 기준 값은 직접 길에서는 리랭커가 줄 세운 후보 전체를, MCP 길에서는 돌려받은 상위 n개만 묶는다
    assert direct["meta"]["article_scope"] == "candidates" and mcp["meta"]["article_scope"] == "top_n"
    assert max(len(r["retrieved"]) for r in mcp["rows"]) <= mcp["meta"]["k"]
    assert min(len(r["retrieved"]) for r in direct["rows"]) > direct["meta"]["k"]
    folder = ROOT / "eval" / "results"
    said = check(
        "--same", str(folder / f"retrieval-{name}-direct.json"), str(folder / f"retrieval-{name}-mcp.json")
    )
    assert "조문 기준 값은 견주지 않는다" in said.stdout


@pytest.mark.parametrize("path", STORED, ids=lambda path: path.stem)
def test_a_stored_retrieval_summary_equals_the_summary_recomputed_from_its_rows(path):
    # [왜] 저장한 요약을 믿지 않고 저장한 줄에서 지금 코드로 다시 센다. 계산 규칙이 바뀌면 여기서 드러난다
    result = json.loads(path.read_text(encoding="utf-8"))
    assert summarize_layers(result["rows"], result["meta"]["k"]) == result["summary"]
    assert "본문" not in result["rows"][0] and set(result["rows"][0]) >= {
        "id",
        "layer",
        "gold",
        "cand",
        "retrieved",
    }
