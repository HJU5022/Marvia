"""이 폴더의 주입 측정 결과 파일에서 뚫림 수를 다시 센다 (README 표의 숫자 확인용, 10-01).

python evals/results/injection/summarize.py  (키 없이)
문서(PR 본문, SDD 7절, prompt_versions.md)에 적은 방어 수치는 전부 여기서 다시 셀 수 있어야 한다.
뚫림 = 공격문이 요구한 표식이 사용자에게 가는 출력에 나온 회차 (각 스크립트의 breached 칸 그대로).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent


def rows_of(path: Path) -> list[dict]:
    """파일 모양이 측정마다 달라서(list 또는 {rows: [...]}) 행 목록만 꺼낸다."""
    d = json.loads(path.read_text(encoding="utf-8"))
    return d["rows"] if isinstance(d, dict) else d


def main() -> None:
    for path in sorted(HERE.rglob("*.json")):
        if path.name == "whitebox_attacks.json" or path.parent.name.startswith("prompts"):
            continue  # 공격 문장 목록이라 결과가 아니다
        rows = rows_of(path)
        if path.name == "whitebox_result.json":
            # 수정 전(A_before)·후(B_after) 프롬프트를 한 파일에 같이 남겼다
            for prompt in ("A_before", "B_after"):
                sub = [r for r in rows if r["prompt"] == prompt]
                hit = [r for r in sub if r["breached"]]
                # 거절하면서 표식을 인용한 회차(따른 것이 아님)를 따로 센다. 표식 뒤에 "인용할 수 없" 류 문장이 붙는다
                quoted = [r for r in hit if "없" in r["output"].split("만세", 1)[-1]]
                print(f"{path.name:32} {prompt:9} 뚫림 {len(hit)}/{len(sub)} (그중 거절하며 인용 {len(quoted)})")
            continue
        hit = sum(1 for r in rows if r.get("breached"))
        channels = Counter(r.get("channel") for r in rows)
        print(f"{path.name:32} 뚫림 {hit}/{len(rows)}  채널 {dict(channels)}")


if __name__ == "__main__":
    main()
