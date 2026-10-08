"""LLM 호출마다의 Langfuse 프롬프트 이름, JSON 출력 스키마, 출력 검증 모델 (services/llm.py에서 옮김, SDD 5.6). 프롬프트 글은 여기에 없다."""
from __future__ import annotations

from typing import get_args, Literal
from pydantic import BaseModel
from backend.app.schemas.agent import Evidence, Reason, Conflict, Verdict

JUDGE_PROMPT = "marvia-judge"  # Langfuse 프롬프트 이름 (SDD 5.6 표)

# 구조화 출력 스키마. Pydantic에서 자동으로 뽑지 않고 손으로 적은 이유: strict 모드는 minItems 같은
# 키워드를 받지 않는 제공사가 있어서, 스모크 테스트에서 통과한 모양(scripts/eval/smoke_llm.py)을 그대로 따른다.
# 모양은 아래 JudgeOutput과 같아야 한다. 받은 뒤 JudgeOutput으로 한 번 더 검사한다.
JUDGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "reasons", "conflicts", "actions", "answer", "customs", "table_disagree"],  # strict 모드는 모든 칸이 required
    "properties": {
        # null = 판정 보류. 위치가 아예 없을 때 등 (skills/cargo-verdict "코드가 낸 되묻기·보류·실패 결과")
        "verdict": {"type": ["string", "null"], "enum": ["fine", "watch", "act", None]},
        "reasons": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["rule", "value", "triggered"],
                "properties": {
                    "rule": {"type": "string", "description": "신호 id (rules.md)"},
                    "value": {"type": "string"},
                    "triggered": {"type": "boolean"},
                },
            },
        },
        "conflicts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["signals", "chosen", "why"],
                "properties": {
                    "signals": {"type": "array", "items": {"type": "string"}},
                    # 믿은 출처는 근거 카드의 출처 이름 중 하나여야 한다 (V6). 목록을 주지 않았더니 Gemini가
                    # "해수부 입항 예정" 같은 설명을 써서 act가 맞는데도 V6로 3번 탈락했다 (평가 B04·B09, Langfuse 확인).
                    # 목록은 계약 C1 Evidence.source에서 가져온다. 여기에 따로 적으면 둘이 어긋날 수 있다
                    "chosen": {"type": "string", "enum": list(get_args(Evidence.model_fields["source"].annotation)),
                               "description": "믿은 출처"},
                    "why": {"type": "string"},
                },
            },
        },
        "actions": {"type": "array", "items": {"type": "string"}},
        "answer": {"type": "string", "description": "사용자에게 보여 줄 한국어 두세 문장"},
        # 통관 단계 해설 (PRD 6.1 LLM 몫, skills/customs-stages). 통관 정보가 없으면 null
        "customs": {
            "anyOf": [
                {
                    "type": "object",
                    "additionalProperties": False,
                    # needs_broker는 코드가 정해 입력으로 준다 (signals.needs_broker). LLM은 쓰지 않는다
                    "required": ["plain_explanation", "next_stage"],
                    "properties": {
                        "plain_explanation": {"type": "string"},
                        "next_stage": {"type": ["string", "null"]},
                    },
                },
                {"type": "null"},
            ]
        },
        # 표 등급이 이 경우에 틀렸다고 볼 때 그 이유. 응답에 쓰지 않고 기록만 한다. 동의하면 null
        "table_disagree": {"type": ["string", "null"]},
    },
}

class CustomsExplanation(BaseModel):
    """LLM이 쓴 통관 해설. 단계 이름·코드·이력과 관세사 필요 여부는 코드 값을 쓰고, 여기서는 설명 둘만 받는다 (C1 CustomsInfo).
    예전 녹화 답(evals/fixtures/replay)에 needs_broker 칸이 남아 있어도 무시된다 (pydantic 기본값: 모르는 칸 무시)."""

    plain_explanation: str
    next_stage: str | None

class JudgeOutput(BaseModel):
    """LLM이 낸 판정. 필드 타입은 계약 C1(schemas/agent.py)의 것을 그대로 쓴다."""

    verdict: Verdict | None
    reasons: list[Reason]
    conflicts: list[Conflict]
    actions: list[str]
    answer: str
    customs: CustomsExplanation | None
    table_disagree: str | None = None  # 기록만 한다 (services/judge/verdict.py). 녹화 답·베이스라인은 없어도 된다

PICK_PROMPT = "marvia-pick-vessel"

PICK_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["choice", "confidence", "reasons_per_candidate"],
    "properties": {
        "choice": {"type": ["integer", "null"], "description": "고른 배의 MMSI. 애매하면 null"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "reasons_per_candidate": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["mmsi", "reason"],
                "properties": {"mmsi": {"type": "integer"}, "reason": {"type": "string"}},
            },
        },
    },
}

class CandidateReason(BaseModel):
    mmsi: int
    reason: str

class PickOutput(BaseModel):
    choice: int | None
    confidence: Literal["high", "medium", "low"]
    reasons_per_candidate: list[CandidateReason]

FOLLOW_UP_PROMPT = "marvia-follow-up"

FOLLOW_UP_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["in_scope", "answer"],
    "properties": {
        "in_scope": {"type": "boolean", "description": "판정 결과·근거 안에서 답할 수 있는 질문인가"},
        "answer": {"type": "string"},
    },
}

class FollowUpOutput(BaseModel):
    in_scope: bool
    answer: str

DOC_EXTRACT_PROMPT = "marvia-doc-extract"

DOC_EXTRACT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    # strict 모드는 모든 칸이 required
    "required": ["vessel", "voyage", "eta", "pol", "pod", "item", "etd", "doc_kind",
                 "original_bl", "original_bl_text", "to_order_bank", "to_order_bank_text",
                 "freight_term", "freight_term_text", "incoterm", "contact_company", "contact_role", "contact_phone"],
    "properties": {
        "vessel": {"type": ["string", "null"]},
        "voyage": {"type": ["string", "null"]},
        "eta": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
        "pol": {"type": ["string", "null"]},
        "pod": {"type": ["string", "null"]},
        "item": {"type": ["string", "null"]},
        "etd": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
        "doc_kind": {"type": ["string", "null"], "enum": ["bl", "arrival_notice", None]},
        "original_bl": {"type": ["string", "null"], "enum": ["required", "surrendered", None]},
        "original_bl_text": {"type": ["string", "null"]},
        "to_order_bank": {"type": ["boolean", "null"]},
        "to_order_bank_text": {"type": ["string", "null"]},
        "freight_term": {"type": ["string", "null"], "enum": ["prepaid", "collect", None]},
        "freight_term_text": {"type": ["string", "null"]},
        "incoterm": {"type": ["string", "null"], "enum": ["CIF", "FOB", "CFR", None]},
        "contact_company": {"type": ["string", "null"]},
        "contact_role": {"type": ["string", "null"], "enum": ["포워더", "관세사", "수출자", "판매처", None]},
        "contact_phone": {"type": ["string", "null"]},
    },
}

class DocFieldsOutput(BaseModel):
    vessel: str | None
    voyage: str | None
    eta: str | None  # 모양 검사는 doc_ocr.check_fields가 한다. 여기서 date로 바꾸면 틀린 모양이 형식 오류로 바뀌어 원인이 가려진다
    pol: str | None
    pod: str | None
    item: str | None
    # 기본값 None: 이 칸이 생기기 전 모양의 답(테스트·녹화)도 읽힌다. 값 검사는 doc_ocr.check_conditions
    doc_kind: str | None = None           # bl / arrival_notice. 거래처 출처(B/L·A/N)를 정하는 데만 쓴다
    original_bl: str | None = None        # required / surrendered
    original_bl_text: str | None = None   # 위 값의 근거로 서류에서 그대로 옮긴 글
    to_order_bank: bool | None = None     # 수하인이 "TO ORDER OF... BANK"인가
    to_order_bank_text: str | None = None
    freight_term: str | None = None       # prepaid / collect
    freight_term_text: str | None = None
    incoterm: str | None = None           # CIF / FOB / CFR
    contact_company: str | None = None    # 화물 인도 연락처 회사 (개인 이름 아님)
    contact_role: str | None = None       # 포워더 / 관세사 / 수출자 / 판매처
    contact_phone: str | None = None      # 회사·부서 전화 (개인 휴대폰 아님)
    # 출항일 YYYY-MM-DD (A/N의 ETD, B/L의 Shipped on board). 기본값 None: 프롬프트가 Langfuse에 등록되기 전이라
    # LLM이 이 칸을 모르거나 null로 두어도 읽힌다. 모양·서류 속 존재·eta와의 순서 검사는 doc_ocr.check_fields
    etd: str | None = None

MEMORY_PROMPT = "marvia-memory-write"

_NULLABLE_TEXT = {"type": ["string", "null"]}

MEMORY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ops"],
    "properties": {
        "ops": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                # strict 모드는 모든 칸이 required. 명령마다 안 쓰는 칸은 null (프롬프트에 적는다)
                "required": ["op", "id", "section", "kind", "fields", "field", "value"],
                "properties": {
                    "op": {"type": "string", "enum": ["add", "update", "delete", "set_cargo", "noop"]},
                    "id": _NULLABLE_TEXT,
                    "section": {"type": ["string", "null"], "enum": ["about", "cargo", None]},
                    "kind": {"type": ["string", "null"],
                             "enum": ["preference", "schedule", "contact", "worry", "todo", None]},
                    "fields": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["text", "done", "cycle", "task", "company", "role", "duty", "phone", "source"],
                        "properties": {
                            "text": _NULLABLE_TEXT, "done": {"type": ["boolean", "null"]},
                            "cycle": _NULLABLE_TEXT, "task": _NULLABLE_TEXT, "company": _NULLABLE_TEXT,
                            "role": _NULLABLE_TEXT, "duty": _NULLABLE_TEXT, "phone": _NULLABLE_TEXT,
                            "source": _NULLABLE_TEXT,
                        },
                    },
                    "field": {"type": ["string", "null"], "enum": ["sale_due_date", "forwarder_eta", "label", None]},
                    "value": _NULLABLE_TEXT,
                },
            },
        },
    },
}

class MemoryFields(BaseModel):
    """명령의 칸 값. 종류마다 쓰는 칸이 다르고 나머지는 null. 어느 칸이 허용되는지는 services/account/memory.py가 본다."""

    text: str | None = None
    done: bool | None = None
    cycle: str | None = None
    task: str | None = None
    company: str | None = None
    role: str | None = None
    duty: str | None = None
    phone: str | None = None
    source: str | None = None

class MemoryOp(BaseModel):
    op: Literal["add", "update", "delete", "set_cargo", "noop"]
    id: str | None = None
    section: str | None = None
    kind: str | None = None
    fields: MemoryFields | None = None
    field: str | None = None
    value: str | None = None

class MemoryOpsOutput(BaseModel):
    ops: list[MemoryOp]

TITLE_PROMPT = "marvia-chat-title"

TITLE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title"],
    "properties": {"title": {"type": "string"}},
}

class TitleOutput(BaseModel):
    title: str

JUDGE_EVAL_PROMPT = "marvia-judge-eval"  # Langfuse 프롬프트 이름 (SDD 5.6 표)

GRADE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["score", "reason"],
    "properties": {
        # 정수 enum은 Gemini 구조화 출력이 지원하지 않아 빈 {}가 온다 (채점 모델을 gemini-2.5-flash로 바꿀 때 확인).
        # 0/1 범위는 GradeOutput(Literal[0, 1])이 검사한다
        "score": {"type": "integer", "description": "지시문의 다섯 조건을 모두 지키면 1, 하나라도 어기면 0"},
        "reason": {"type": "string", "description": "어긴 조건 번호와 이유 한 줄. 다 지키면 pass"},
    },
}

class GradeOutput(BaseModel):
    score: Literal[0, 1]
    reason: str

CHAT_ROUTE_PROMPT = "marvia-chat-route"

CHAT_ROUTE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["intent", "bl_ref", "bl_type", "sale_due_date", "question", "place", "place_label", "days", "reply"],
    "properties": {
        "intent": {"type": "string", "enum": ["cargo", "follow_up", "vessel_search", "other"]},
        "bl_ref": {"type": ["string", "null"]},
        "bl_type": {"type": ["string", "null"], "enum": ["MASTER", "HOUSE", None]},
        "sale_due_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
        "question": {"type": ["string", "null"]},
        "place": {"type": ["string", "null"]},
        "place_label": {"type": ["string", "null"]},
        "days": {"type": ["integer", "null"]},
        "reply": {"type": "string"},
    },
}

class ChatRouteOutput(BaseModel):
    intent: Literal["cargo", "follow_up", "vessel_search", "other"]
    bl_ref: str | None
    bl_type: Literal["MASTER", "HOUSE"] | None
    sale_due_date: str | None  # 모양 검사는 services/chat/chat.py가 한다
    question: str | None
    place: str | None
    place_label: str | None = None  # 답에 쓸 이름. 사용자가 쓴 말 그대로 (예: 중국)
    days: int | None
    reply: str

CHAT_AGENT_PROMPT = "marvia-chat-agent"

# 도구 없이 답할 때의 근거 칸: 실무 질문 답에 Skill 문서에 없는 조언("판매처에 문의", "A/N에 B/L 번호가 보통 적혀 있다")이
# 섞여 나왔는데, 숫자·영문·옮긴 낱말만 보는 V7·V9·V10으로는 못 잡았다. 그래서 답의 종류(answer_kind)와 근거 문장(skill_quote)을 받는다.
#   skill: Skill 문서로 답했다. skill_quote는 그 답을 받치는 Skill 문서 원문 한 조각이고, 코드가 원문에 그대로 있는지 본다 (validate V14)
#   not_in_skills: 수입 화물 질문이지만 Skill 문서에 없다. 코드가 고정 문구를 쓴다 (chat.NOT_IN_SKILLS)
#   unrelated: 수입 화물과 상관없는 말. 코드가 고정 안내를 쓴다 (chat.OTHER_REPLY)
#   tool: 도구를 불렀고 그 결과를 받은 뒤의 답. 도구 없이 tool을 내면 코드가 도구를 부르라고 다시 묻는다 (chat._agent).
#     따로 둔 이유: 도구를 쓴 답을 unrelated + 빈 reply로 내게 했을 때 도구를 안 부른 답과 코드가 구별하지 못했다.
#     같은 날 진단에서 deepseek-v4-flash(OpenRouter)는 strict response_format을 붙이면 도구를 전혀 부르지 않고 이 모양만 냈다
#     (붙이지 않으면 search_arrivals·ask_cargo를 바로 불렀다). 그 문제는 _ask_json 쪽이고, 여기서는 tool을 낸 답을 코드가 알아보게만 한다
# 도구를 쓴 답이면 근거 칸은 보지 않는다. 종류를 잘못 골라도 결과는 고정 문구 중 하나라 지어낸 조언이 화면에 가지 않는다
#   general: 2층. 교과서 수준의 일반 해운 설명(용어 뜻, 일반 절차)을 모델 지식으로 답했다. 근거 조각 없이 내보내되
#     숫자·세액·특정 화물·배 이야기는 안 되고 꼬리표는 없다: 고지는 이용약관으로 옮겼다 (chat._agent). 검사는 V7·V9(허용 용어 확장)·V10·V13
#   unrelated: 이제 한 문장짜리 직접 답을 낼 수 있다 (날짜·"마르비아가 뭐야?" 같은 잡담). 검사에 걸리면 고정 안내로 바뀐다
#   clarify: 사용자가 쓴 식별자(예: TEST41)가 B/L 번호인지 배 이름인지 모르겠다. 코드가 고정 문장으로 되묻는다
#     (chat.clarify_reply). reply는 비운다: LLM 글은 화면에 가지 않고 식별자도 코드가 문장에서 직접 뽑는다
# help·greeting: 사용법 질문과 인사. 문장은 services/chat/chat.py가 고정 문구로 낸다
CHAT_AGENT_KINDS = ("tool", "skill", "general", "not_in_skills", "unrelated", "clarify", "help", "greeting")

CHAT_AGENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reply", "answer_kind", "skill_quote", "watch_cue"],
    "properties": {
        "reply": {"type": "string"},
        "answer_kind": {"type": "string", "enum": list(CHAT_AGENT_KINDS)},
        "skill_quote": {"type": "string"},
        "watch_cue": {"type": "boolean"},
    },
}

class ChatAgentOutput(BaseModel):
    reply: str  # 화면에 내보내기 전에 services/chat/chat.py가 검사한다
    # 기본값은 도구를 쓴 답(두 칸을 보지 않음)과 예전 녹화 답이 그대로 읽히게 둔 것이다. 실제 호출은 strict 스키마라 늘 채워 온다
    answer_kind: Literal["tool", "skill", "general", "not_in_skills", "unrelated", "clarify", "help", "greeting"] = "unrelated"
    skill_quote: str = ""  # answer_kind가 skill이면 Skill 문서 원문 그대로의 한 조각
    # 사용자 말에 걱정·기한 압박이 묻어 있나 (결정 "먼저 제안"). 신호일 뿐이다: 제안할지는 services/chat/chat.py가 정한다.
    # 기본값 False는 예전 녹화 답이 그대로 읽히게 둔 것이다 (실제 호출은 strict 스키마라 늘 채워 온다)
    watch_cue: bool = False

PORT_MATCH_PROMPT = "marvia-port-match"

PORT_MATCH_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ports"],
    "properties": {"ports": {"type": "array", "items": {"type": "string"}}},
}

class PortMatchOutput(BaseModel):
    ports: list[str]
