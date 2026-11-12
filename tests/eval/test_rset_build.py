"""검색 전용 평가셋을 만든 스크립트(scripts/rset) 시험: 다시 돌리면 eval/에 둔 파일과 글자까지 같다.

키와 DB 없이 돈다. rset_a4는 로컬 DB에서 단위 순서를 읽어 여기서 다시 만들지 않는다(동결 시험만 있다).
모델이 쓴 질문은 eval/rset_build/의 파일을 그대로 넣는다.
"""

import shutil
import subprocess
import sys

from marvia.eval.dataset import ROOT

BUILD = ROOT / "eval" / "rset_build"


def script(name: str, *args) -> None:
    done = subprocess.run(
        [sys.executable, f"scripts/rset/{name}", *map(str, args)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-600:]


def same(made, name: str) -> bool:
    return made.read_bytes() == (ROOT / "eval" / name).read_bytes()


def test_the_scripts_rebuild_every_frozen_retrieval_set_byte_for_byte(tmp_path):
    work, out, second = tmp_path / "v1", tmp_path / "set", tmp_path / "b2"
    for folder in (work, out, second):
        folder.mkdir()
    # rset_v1: 표본 → (질문) → 초안 → 정답 독립 확인의 고침
    script("build_rset.py", "sample", work)
    # [왜] 질문을 쓰는 쪽에 준 글과 표본이 저장해 둔 것과 같아야 저장된 질문이 이 표본의 질문이다
    assert (work / "sample.json").read_bytes() == (BUILD / "sample.json").read_bytes()
    assert (work / "for_writer.json").read_bytes() == (BUILD / "for_writer.json").read_bytes()
    shutil.copy(BUILD / "questions.json", work)
    script("build_rset.py", "write", work, work / "draft.yaml")
    script("apply_fixes.py", work / "draft.yaml", out / "rset_v1.yaml")
    assert same(out / "rset_v1.yaml", "rset_v1.yaml")
    script("build_rset_a2.py", out / "rset_v1.yaml", out / "rset_a2.yaml")
    assert same(out / "rset_a2.yaml", "rset_a2.yaml")
    # rset_a3과 rset_b2: 같은 난수기를 이어 쓴다
    script("build_round2.py", "sample", out, second)
    assert same(out / "rset_a3.yaml", "rset_a3.yaml")
    assert (second / "b2_sample.json").read_bytes() == (BUILD / "b2_sample.json").read_bytes()
    assert (second / "b2_for_writer.json").read_bytes() == (BUILD / "b2_for_writer.json").read_bytes()
    shutil.copy(BUILD / "b2_questions.json", second)
    script("build_round2.py", "write", out, second)
    shutil.move(out / "rset_b2.yaml", second / "draft.yaml")
    script("apply_fixes_b2.py", second / "draft.yaml", out / "rset_b2.yaml")
    assert same(out / "rset_b2.yaml", "rset_b2.yaml")


def test_the_writer_was_given_no_gold_unit_names():
    # [왜] 질문을 쓰는 쪽이 정답 단위 이름이나 조문 번호를 보면 질문이 검색에 유리하게 치우친다
    for name in ("for_writer.json", "b2_for_writer.json"):
        assert "@20" not in (BUILD / name).read_text(encoding="utf-8")
