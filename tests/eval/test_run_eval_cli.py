"""scripts/run_eval.py 명령의 경계 시험. 키·DB 없이 돈다."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_sheet_refuses_to_write_answer_text_inside_the_repo():
    out = ROOT / "tests" / "sheet-should-not-exist.md"
    done = subprocess.run(
        [sys.executable, "scripts/run_eval.py", "sheet", "a.json", "a.raw.json", "--out", str(out)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert done.returncode != 0 and "저장소 안" in done.stderr
    assert not out.exists()
