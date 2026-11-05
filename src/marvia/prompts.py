"""프롬프트 파일(prompts/*.md)을 읽어 빈칸을 채운다 (설계 11절: 프롬프트는 레포 파일이 원본).

하지 않는 일: Langfuse 등록(계획 4).
"""

from __future__ import annotations

from pathlib import Path

PROMPTS = Path(__file__).resolve().parents[2] / "prompts"


def render(name: str, **values: str) -> str:
    """prompts/{name}.md의 {이름} 자리를 values로 채운다. 값의 <는 바꿔 태그를 열고 닫지 못하게 한다."""
    # [주의] str.format을 쓰므로 프롬프트 파일에는 빈칸 말고 중괄호를 쓰지 않는다
    # [왜] 값은 데이터다(사용자 글·법령 글). 값 속 </question>이 태그를 일찍 닫으면
    #      뒤 글이 지시처럼 읽힌다 (설계 12절). [주의] >는 두다: 조문 제목의 "관세법 > 제241조" 구분자다
    safe = {key: value.replace("<", "&lt;") for key, value in values.items()}
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8").format(**safe)
