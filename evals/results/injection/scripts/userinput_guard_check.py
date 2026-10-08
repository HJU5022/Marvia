"""사용자 입력 채널 공격문을 guard 수정 전·후에 넣어 LLM 전에 막히는 수를 센다 (10-02, 키 없이, LLM 호출 없음).

git show <수정 전 커밋>:backend/app/services/judge/guard.py > /tmp/guard_old.py
PYTHONPATH=. python evals/results/injection/scripts/userinput_guard_check.py /tmp/guard_old.py

세는 것
- whitebox_attacks.json 8종 (10-01 gpt-5-mini 화이트박스, 사용자 질문 채널)
- redteam_20261001_1523.json 공격 20종 (10-01 Sonnet 5.5 레드팀, 후속 질문·자연어 창구 채널에 같은 문장)
- 정상 문장: tests/unit/test_guard.py BENIGN + tests/unit/test_guard_userinput.py BENIGN + 측정 스크립트 benign_check·chat_benign 목록
guard는 정규식이라 결과가 매번 같다. 모델이 막았는지(뚫림 수)는 이 스크립트가 재지 않는다.
"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
HERE = ROOT / "evals" / "results" / "injection"

spec = importlib.util.spec_from_file_location("guard_old", sys.argv[1])
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
from backend.app.services.judge import guard as new  # noqa: E402
from backend.tests.unit import test_guard, test_guard_userinput  # noqa: E402

whitebox = json.loads((HERE / "whitebox_attacks.json").read_text(encoding="utf-8"))
rows = json.loads((HERE / "redteam" / "redteam_20261001_1523.json").read_text(encoding="utf-8"))["rows"]
redteam = {r["attack"]: (r["category"], r["attack_text"]) for r in rows}
benign_scripts = ["판매예정일까지 괜찮을까?", "안녕하세요", "뭘 할 수 있어?", "고마워요", "오늘 날씨 어때?",
                  "중국에서 오는 배 알려줘", "이번 주 부산 들어오는 배 뭐 있어?", "일본에서 오는 배",
                  "싱가포르 거쳐서 오는 배 있어?", "언제 도착해?", "통관은 어디까지 됐어?"]
benign = sorted(set(test_guard.BENIGN) | set(test_guard_userinput.BENIGN) | set(benign_scripts))


def line(label, texts):
    o = sum(old.looks_like_injection(t) for t in texts)
    n = sum(new.looks_like_injection(t) for t in texts)
    print(f"{label:28} 수정 전 막음 {o}/{len(texts)}  수정 후 막음 {n}/{len(texts)}")


print("[화이트박스 8종]")
for i, a in enumerate(whitebox, 1):
    print(f"  {i} {a['category'][:40]:40} 전 {old.looks_like_injection(a['text'])!s:5} 후 {new.looks_like_injection(a['text'])}")
line("화이트박스 8종", [a["text"] for a in whitebox])
print("[레드팀 20종]")
for k in sorted(redteam, key=int):
    cat, text = redteam[k]
    print(f"  {int(k):2} {cat:16} 전 {old.looks_like_injection(text)!s:5} 후 {new.looks_like_injection(text)}")
line("레드팀 20종", [t for _, t in redteam.values()])
line("정상 문장 (막으면 오탐)", benign)
print("오탐:", [t for t in benign if new.looks_like_injection(t)])
