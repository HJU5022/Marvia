"""프롬프트 파일(prompts/*.md)을 읽어 빈칸을 채운다 (설계 11절: 프롬프트는 레포 파일이 원본).

하지 않는 일: Langfuse 등록(계획 4).
"""

from __future__ import annotations

from pathlib import Path

PROMPTS = Path(__file__).resolve().parents[2] / "prompts"


def render(name: str, **values: str) -> str:
    """prompts/{name}.md의 {이름} 자리를 values로 채운다."""
    # [주의] str.format을 쓰므로 프롬프트 파일에는 빈칸 말고 중괄호를 쓰지 않는다
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8").format(**values)
