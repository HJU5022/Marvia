"""LLM 연결 확인 스크립트 (C-6 첫걸음, 모델 선정 스모크 테스트).

services/llm.py의 chat()을 불러서 모델이 붙는지, 구조화 출력(JSON 스키마)을 지키는지 본다.
사례는 가공값이다. 실제 B/L·고객 서류는 넣지 않는다 (무료 모델은 입력이 로깅될 수 있음).

    python -m scripts.eval.smoke_llm                 # .env의 LLM_MODEL
    python -m scripts.eval.smoke_llm --model qwen/qwen3.8-27b:free

무료 모델은 하루 50회 한도(한국 시각 오전 9시 초기화). 한 번 실행 = 1회.
"""
import argparse
import json
import os

from dotenv import load_dotenv

from backend.app.services.llm import chat

load_dotenv()  # OPENROUTER_API_KEY, LLM_MODEL을 .env에서 읽는다

# 가공 사례. 기대 답: 판매일까지 여유 3일이라 act는 아님 (fine/watch는 확인 대기)
CASE = (
    "화물의 통관 단계는 '입항적하목록 제출'. 선박 ETA는 2일 뒤, 판매 예정일은 5일 뒤. "
    "선박 위치 정보는 3시간 전 것. 신호 상충 없음."
)

# 역할 지시 + 판정 정의. 정의가 없으면 모델이 act를 "절차 계속 진행"으로 읽었다 (3회 실행, 3회차).
# 정의 문구는 사람이 확인한다. 서비스에서는 Skill·Langfuse Prompt가 이 자리를 맡는다 (SDD 5.6)
SYSTEM = (
    "너는 수입 화물 판정 도우미다. 주어진 근거만 쓴다.\n"
    "verdict 정의:\n"
    "- fine: 판매 예정일까지 조치할 필요 없음\n"
    "- watch: 여유는 있지만 확인이 필요함\n"
    "- act: 지금 조치하지 않으면 판매 예정일을 못 맞춤"
)

# PRD 12장 응답 스키마의 일부만. 전체 계약(C1)은 파이프라인이 붙은 뒤에 쓴다
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "reasons", "customs_explanation"],
    "properties": {
        "verdict": {"type": "string", "enum": ["fine", "watch", "act"]},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "customs_explanation": {"type": "string", "description": "화주가 이해할 수 있는 한국어 한두 문장"},
    },
}


def main(model: str) -> None:
    result = chat(
        [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": CASE},
        ],
        model=model,
        response_format={"type": "json_schema", "json_schema": {"name": "verdict", "strict": True, "schema": SCHEMA}},
        max_tokens=800,
    )
    print(f"model: {result.model} | provider: {result.provider} | {result.latency_ms} ms | 시도 {result.attempts}회")
    print(f"tokens: in {result.prompt_tokens} / out {result.completion_tokens}")

    # JSON으로 읽히는지 → 형식이 맞는지 순서로 본다
    try:
        data = json.loads(result.content or "")
    except json.JSONDecodeError:
        print("JSON: ❌ 읽을 수 없음")
        print(result.content)
        return
    missing = [k for k in SCHEMA["required"] if k not in data]
    print(f"JSON: ✅ | 필수 필드: {'✅' if not missing else '❌ 없음 ' + str(missing)}")
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM 연결·구조화 출력 확인")
    parser.add_argument("--model", default=os.environ.get("LLM_MODEL"))
    main(parser.parse_args().model)
