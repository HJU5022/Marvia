"""재생 모드 데모 파일 자동 갱신 (scripts/demo/make_demo.refresh, backend/app/main.py)."""
from datetime import datetime, timezone

from scripts.demo import make_demo


def test_refresh_swaps_in_new_files_and_keeps_other_folders(tmp_path):
    """임시 폴더에 다 만든 뒤 바꿔 끼운다. 녹화 LLM 답(llm/)처럼 이 스크립트가 만들지 않는 폴더는 그대로 둔다."""
    out = tmp_path / "replay"
    (out / "llm").mkdir(parents=True)
    (out / "llm" / "keep.json").write_text("[]", encoding="utf-8")
    make_demo.build_all(datetime(2026, 1, 1, tzinfo=timezone.utc), out)
    before = {p.relative_to(out) for p in out.rglob("*") if p.is_file()}
    until = make_demo.refresh(out)
    after = {p.relative_to(out) for p in out.rglob("*") if p.is_file()}
    assert (out / "llm" / "keep.json").exists()
    assert before == after  # 같은 파일 묶음이 새 시각으로 다시 만들어졌다
    assert not list(tmp_path.glob(".*staging")) and not list(out.glob(".*_old"))
    assert until > datetime.now(timezone.utc)
