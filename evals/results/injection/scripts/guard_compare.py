"""측정에 쓴 공격 문장 전부를 수정 전후 guard에 넣어 비교한다 (10-01 오탐 수정 확인용, 키 없이).

git show <수정 전 커밋>:backend/app/services/judge/guard.py > /tmp/guard_old.py
PYTHONPATH=. python evals/results/injection/scripts/guard_compare.py /tmp/guard_old.py
"""
import glob
import importlib.util
import json
import re
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("guard_old", sys.argv[1])
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
from backend.app.services.judge import guard as new  # noqa: E402

texts = set()
for f in glob.glob("evals/results/injection/**/*.json", recursive=True):
    if "prompts" in Path(f).parts:
        continue
    d = json.load(open(f, encoding="utf-8"))
    rows = d.get("rows", d.get("attacks", [])) if isinstance(d, dict) else d
    for r in rows:
        if isinstance(r, dict):
            for k in ("attack_text", "text"):
                if isinstance(r.get(k), str) and len(r[k]) > 15:
                    texts.add(r[k])
for f in (".local/redteam/role_variants.json",):
    try:
        for a in json.load(open(f, encoding="utf-8"))["attacks"]:
            texts.add(a["text"])
    except OSError:
        pass
# 측정 스크립트 안의 공격 문장: role_reset_check2.py의 "text"/문자열 상수 중 긴 것
src = open("evals/results/injection/scripts/role_reset_check2.py", encoding="utf-8").read()
for m in re.finditer(r'"((?:[^"\\]|\\.){25,})"', src):
    texts.add(m.group(1).encode().decode("unicode_escape", errors="ignore") if "\\u" in m.group(1) else m.group(1))

print("attack texts", len(texts))
print("old blocks", sum(old.looks_like_injection(t) for t in texts), "new blocks", sum(new.looks_like_injection(t) for t in texts))
lost = [t for t in texts if old.looks_like_injection(t) and not new.looks_like_injection(t)]
print("newly passing:", len(lost))
for t in lost:
    print("  -", t[:170].replace("\n", " "))
