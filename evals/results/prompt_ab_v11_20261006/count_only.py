"""--only 실행 출력(run_*.txt)에서 문항별 V11·다른 검증 위반·형식 오류·정답 여부를 센다."""
import re, sys
from collections import defaultdict
from pathlib import Path

ROW = re.compile(r"^\s+(?P<id>[NBF]\d{2})\s+(?P<ok>[OX])\s.*?실패=(?P<fail>.*?)(?:  해설=|$)")
cases = defaultdict(lambda: {"runs": 0, "ok": 0, "v11": 0, "v11_judge": 0, "v11_follow": 0, "other": 0, "bad": 0, "clean": 0})
files = sorted(Path(sys.argv[1]).glob("run_*.txt"), key=lambda p: int(p.stem.split("_")[1]))
for f in files:
    for line in f.read_text().splitlines():
        m = ROW.match(line)
        if not m:
            continue
        c = cases[m["id"]]; c["runs"] += 1; c["ok"] += m["ok"] == "O"
        fails = [x for x in m["fail"].split(",") if "attempt" in x and "gave up" not in x]
        for x in fails:
            if "V11" in x:
                c["v11"] += 1; c["v11_follow" if "follow_up" in x else "v11_judge"] += 1
            elif x.startswith("validate"):
                c["other"] += 1
            elif "bad_format" in x:
                c["bad"] += 1
        c["clean"] += not fails
print(f"files={len(files)}")
print("| 문항 | 실행 | 정답 | V11 위반 (판정/후속) | 다른 검증 위반 | 형식 오류 | 1회 통과 |")
print("|---|---|---|---|---|---|---|")
T = defaultdict(int)
for k in sorted(cases):
    c = cases[k]
    print(f"| {k} | {c['runs']} | {c['ok']} | {c['v11']} ({c['v11_judge']}/{c['v11_follow']}) | {c['other']} | {c['bad']} | {c['clean']} |")
    for a, b in c.items(): T[a] += b
print(f"| 합계 | {T['runs']} | {T['ok']} | {T['v11']} ({T['v11_judge']}/{T['v11_follow']}) | {T['other']} | {T['bad']} | {T['clean']} |")
