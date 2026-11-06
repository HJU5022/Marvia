"""서류 사진(B/L·도착 통지서)의 글을 이 컴퓨터 안에서 읽는다 (설계 4.2, 계획 3d). 사진은 밖으로 보내지 않는다.

하지 않는 일: 번호 판단(identify.parse가 한다), 사진 저장. 엔진은 RapidOCR + onnxruntime이고,
모델은 패키지에 들어 있는 것을 쓴다(받는 일 없음, 11-06 Docker에서 확인).
[주의] 사진 글에는 상호·주소·전화 같은 다른 정보가 있다.
       LLM 쪽으로 넘길 글은 photo_clues로 번호 덩어리만 남긴다.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

from marvia.identify.parse import read_numbers


@cache
def _engine() -> Callable[[str], Any]:
    """RapidOCR 엔진을 한 번만 만든다. [왜] 모델 파일을 읽는 데 시간이 든다."""
    # [왜] 무거운 패키지(onnxruntime·OpenCV)라 사진을 읽을 때만 불러온다. 시험과 다른 길은 불러오지 않는다
    from rapidocr import RapidOCR

    return RapidOCR(params={"Global.log_level": "warning"})


def read_image(path: str | Path, engine: Callable[[str], Any] | None = None) -> str:
    """사진 한 장의 글을 줄마다 읽는다. engine을 주면 그것을 쓴다(시험의 가짜 엔진)."""
    out = (engine or _engine())(str(path))
    # [왜] RapidOCR은 읽은 줄을 txts(튜플)에 담고, 글을 못 찾으면 None을 둔다 (rapidocr/utils/output.py)
    return "\n".join(getattr(out, "txts", None) or ())


def photo_clues(text: str) -> str:
    """사진 글에서 화물 번호 덩어리만 남긴다. 나머지 글(상호·주소·전화번호)은 버린다."""
    # [왜] 번호 읽기와 같은 규칙(read_numbers)으로 덩어리를 찾는다. 날짜·전화번호는 거기서 이미 빠진다
    return " ".join(span.raw for span, _ in read_numbers(text))
