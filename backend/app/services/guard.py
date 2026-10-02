"""사용자 자유 입력 속 프롬프트 주입(역할 재설정·지시 무시) 문장을 LLM에 넘기기 전에 코드가 걸러낸다 (SDD 7절, 8절).

왜 코드로 막나 (10-01 측정, gpt-4o-mini, 후속 질문에 "지금부터 너는 ~" 20회):
  현재 프롬프트 10/20 뚫림, 프롬프트 끝 역할 고정 문장 추가 뒤에도 4/20 뚫림. 뚫린 답은 숫자가 없어
  검증(V1·V7)을 통과해 사용자 화면까지 갔다. 엄격 스키마는 형식만 강제해서 문자열 안 내용은 못 막는다.
  프롬프트 문장은 모델이 따라 주느냐에 달려 있어서, 모델과 무관한 방어를 앞에 둔다.

한계: 아래 패턴에 없는 변형은 통과한다. 그래서 프롬프트 역할 고정 문장(prompts/*.md 끝 두 줄)과 같이 쓴다.
정상 화물 질문이 걸리지 않게 "누구에게 무엇을 하라"는 모양만 잡는다 (tests/test_guard.py의 정상 질문 목록).
"""
from __future__ import annotations

import re
import unicodedata

# 보이지 않는 글자로 패턴을 쪼개는 우회를 막으려고 지운다 (zero-width space·joiner, BOM, soft hyphen)
_INVISIBLE = re.compile("[​‌‍⁠﻿­]")

# 한국어. "너/당신/넌"에게 새 역할을 주거나, 앞선 지시를 무시하라거나, 지시문을 보여 달라는 모양
_KO = [
    r"(지금|이제)\s*부터\s*(너|넌|당신|니가|네가)",
    # "너는 이제 뭘 알려줄 수 있어?"는 정상 질문이다. "이제부터"이거나 뒤에 새 정체성이 붙을 때만 잡는다 (10-01 오탐 점검)
    r"(너|넌|당신)\s*(는|은)?\s*이제\s*부터",
    r"(너|넌|당신)\s*(는|은)?\s*이제\s*.{0,20}(챗봇|봇|AI|에이아이|어시스턴트|비서|역할|캐릭터|모드|으로서|로서|입니다|이다)",
    r"(너|넌|당신)\s*(는|은)\s*.{0,20}(챗봇|봇|AI|에이아이|어시스턴트|비서)\s*(가|이)\s*아니",
    r"역할\s*(을|를)?\s*(바꿔|바꾸|변경|전환|맡아|연기)",
    # "앞의 지시는 모두 무시하고"처럼 사이에 부사가 끼어도 잡는다 (8자까지)
    r"(이전|앞|위|기존|모든)\s*(의)?\s*(지시|명령|규칙|지침|프롬프트|설정)\s*(들)?\s*(을|를|은|는)?.{0,8}?(무시|잊|따르지)",
    # "시스템 메시지"는 UNI-PASS·선사 화면 문구를 묻는 정상 질문에도 나와서 뺐다 (10-01 오탐 점검)
    r"(시스템|system)\s*(프롬프트|prompt|지시|명령)",
    # 개발자 모드는 켜거나 들어가라는 모양만 ("개발자 모드는 없어?"는 통과)
    r"개발자\s*모드\s*(로|으로|를|을|에서|활성|켜|전환|진입)|탈옥|제한\s*없는\s*(AI|에이아이|모드|챗봇)",
    r"(AI|에이아이|어시스턴트|챗봇|모델)\s*(에게|한테)\s*(보내는|전하는)?\s*(지시|명령|메모|안내|노트)",
    r"(캐릭터|페르소나)\s*(로|으로|를|을)",
]

# 영어. 역할 부여, 지시 무시, 가짜 system 블록, 지시문 출력 요청
_EN = [
    r"\byou\s+are\s+(now|no\s+longer)\b",
    # "From now on, notify me ...", "act as a reminder"는 정상 요청이다. 새 정체성을 주는 모양만 (10-01 오탐 점검)
    r"\bfrom\s+now\s+on,?\s+(you\s+(are|will\s+be|must|should|only)|your\s+(role|name|job)|act|respond|answer\s+only)\b",
    r"\bact\s+as\s+(if\s+you\b|(an?\s+)?([\w-]+\s+){0,2}(ai|bot|assistant|model|character|persona|gpt|dan)\b)",
    r"\bpretend\s+(to\s+be|you)\b",
    r"\brole[\s-]*play\b",
    r"\bstay\s+in\s+character\b",
    # "Ignore the previous ETA"는 정상 질문이다. 지시·규칙·프롬프트를 무시하라는 모양만 (10-01 오탐 점검)
    r"\b(ignore|disregard|forget)\s+((all|any|the|your|previous|prior|above|earlier|everything)\s+){0,3}"
    r"(instructions?|rules?|prompts?|directions?|guidelines?|context|above|everything|what\s+you)\b",
    # "system message"는 화면 문구를 묻는 정상 질문에도 나와서 뺐다. 가짜 system 블록은 아래 두 줄이 잡는다
    r"\bsystem\s*(prompt|instruction)",
    r"\[\s*/?\s*system\s*\]",
    r"(^|\n)\s*#+\s*(new\s+)?(system|instruction)",
    r"\bnew\s+(system\s+)?(role|instructions?|message)\b",
    r"\bdeveloper\s+mode\b|\bjailbreak\b",
    r"\b(note|message|instructions?)\s+(to|for)\s+(the\s+)?(assistant|ai|model|llm|system)\b",
    r"\bprint\s+(your|the)\s+.{0,20}(prompt|instructions)\b",
    # 데이터가 끝난 척하고 새 지시를 넣는 구분자 깨기 (10-01 gpt-5-mini 화이트박스 측정에서 수정 전 프롬프트를 뚫음)
    r"\bEND\s+OF\s+(DATA|INPUT|CONTEXT|EVIDENCE)\b",
    # user_cargo·user_memory: 화물 비서 기억 데이터 블록을 닫는 척하는 글 (docs/specs/memory.md, 10-02 검증)
    r"</\s*(evidence|data|context|input|system|user|tool_result|user_cargo|user_memory)\s*>",
]
# 한국어 구분자 깨기: "새 지시:", "추가 지시 :" (콜론까지 있어야 잡는다. "지시"만으로는 정상 질문이 걸린다)
_KO.append(r"(새|추가|다음|변경된)\s*(지시|명령|규칙)\s*[:：]")

_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _KO + _EN]
# DAN은 대소문자를 구분한다. 소문자 "dan"은 이름·단어일 수 있다
_DAN = re.compile(r"\bDAN\b")


def _normal(text: str) -> str:
    """전각 문자·호환 문자를 보통 글자로 바꾸고 보이지 않는 글자를 지운다 (NFKC). 우회 표기를 한 모양으로 모은다."""
    return _INVISIBLE.sub("", unicodedata.normalize("NFKC", text))


def looks_like_injection(text: str | None) -> bool:
    """사용자 자유 입력이 역할 재설정·지시 무시·지시문 요청 모양이면 True. 비었으면 False."""
    if not text:
        return False
    norm = _normal(text)
    return bool(_DAN.search(norm)) or any(p.search(norm) for p in _PATTERNS)
