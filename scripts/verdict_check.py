"""판정 평가 문항(eval/verdict_set_v1.yaml)을 돌려 층마다 통과 수를 찍는다 (계획 8a). 키·DB·LLM 없이 돈다.

실행: uv run python scripts/verdict_check.py
틀린 문항이 있으면 그 칸을 찍고 1로 끝난다.
"""

from marvia.eval.dataset import file_sha256
from marvia.eval.verdict_set import SET_PATH, load_verdict_set, match_mismatches, mismatches, summarize

data = load_verdict_set()
done = summarize(data)
print(f"문항 파일: {SET_PATH.name} sha256 {file_sha256(SET_PATH)[:12]}")
for name, row in done["layers"].items():
    print(f"{name}: {row['passed']}/{row['n']}")
print(f"배 확정: {done['matches']['passed']}/{done['matches']['n']}")
wrong = [(item.id, found) for item in data.items if (found := mismatches(item))]
wrong += [(item.id, found) for item in data.matches if (found := match_mismatches(item))]
for item_id, found in wrong:
    print(f"틀림 {item_id}: {'; '.join(found)}")
raise SystemExit(1 if wrong else 0)
