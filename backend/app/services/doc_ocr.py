"""서류 사진을 글자로 읽고, B/L 번호를 코드로 뽑고, LLM이 뽑은 칸을 검사한다 (docs/specs/document-extract.md 1~3, 5단계).

책임: LLM 앞뒤의 코드 몫을 맡는다. LLM 호출은 여기서 하지 않는다 (CLAUDE.md, llm.extract_doc_fields가 4단계).
  read_lines()   전처리(빨간 도장 지우기 + 방향 맞추기) 후 OCR
  take_bl()      "B/L NO." 이름표 근처에서 B/L 번호를 찾는다. LLM에 넘기지 않기 위해 코드가 먼저 뽑는다
  mask_bl()      OCR 글자에서 B/L 번호를 [BL]로 가린다
  check_fields() 뽑은 칸이 비었는지, OCR 글자에 실제로 있는지, 형식이 맞는지

모든 규칙은 2026-09-29 실험(레포 밖 ocr_bench/, 팀 위키 근거 원장)에서 실패를 보고 넣은 것이다. 주석의 "(09-29 …)"가 그 사례다.
"""
from __future__ import annotations

import datetime
import logging
import re
import threading
import time
from dataclasses import dataclass
from io import BytesIO

import numpy as np
from PIL import Image

from backend.app.schemas.agent import _BL_PATTERN  # B/L 형식은 계약 C2 한 곳에만 둔다 (SDD 3.1)

logger = logging.getLogger(__name__)

# 확신도가 이 정도면 0° 한 번 읽고 멈춘다. 똑바른 가공 통지서의 줄 평균 확신도가 약 0.98이었고,
# 옆으로 누운 사진을 0°로 읽으면 약 0.68이었다 (09-29 실험). 둘 사이를 가른다
CONFIDENT_MEAN = 0.9
CONFIDENT_LINES = 5
# 다른 방향이 이만큼 낫지 않으면 0°를 지킨다. 똑바른 사진을 270°로 돌려도 OCR이 스스로 읽어 점수가 같게 나오는데,
# 그 경우 줄 순서가 거꾸로 나온다 (09-29 실험, 이름표와 값 순서가 뒤집혀 B/L 찾기가 흔들린다)
ROTATION_MARGIN = 1.05

# 이름표 변형: "B/L NO.", "B/L No", "B/L 번호", "Bill of Lading No" (09-29 문장형 서식에서 "B/L 번호"를 못 찾았다)
BL_LABEL = re.compile(r"(B\s*/?\s*L|BILL\s+OF\s+LADING)\s*(NO|번호|#|NUMBER)", re.I)
MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                                      "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}
VOYAGE_PATTERN = re.compile(r"[A-Z0-9]{3,8}")  # 항차: 0925W, 2634E, 108A (09-29 가공·웹 서류에서 본 모양)
FIELDS = ("bl_no", "vessel", "voyage", "eta", "pol", "pod", "item")
# 칸 이름표. 이름표처럼 짧은 줄에 같은 칸 이름이 두 번 이상 나오면(예: "선명 / 항차"와 "선명 / 항차 (정정)")
# 어느 값이 맞는지 서류만으로 알 수 없다. 09-30 주입 확인 D8: LLM이 3번 모두 "(정정)" 쪽 위조 값을 골랐고,
# 그 값도 서류 글자라 not_in_text로 못 잡았다. 이럴 때는 사용자 확인으로 넘긴다 (ambiguous)
FIELD_LABELS = {
    "vessel": re.compile(r"선명|\bVESSEL\b", re.I),
    "voyage": re.compile(r"항차|\bVOY(AGE)?\b", re.I),
    "eta": re.compile(r"입항\s*예정일|도착\s*예정일|\bETA\b", re.I),
}
# 이름표 줄로 보는 최대 길이(공백 · 문장부호 뺀 글자 수). 긴 문장 속 단어("입항 예정일은 바뀔 수 있습니다")는 세지 않는다.
# 안내문에 흔한 문장까지 세면 정상 서류도 매번 확인 필요가 된다. 가공 서식의 이름표는 6~14자다 (09-30)
LABEL_MAX_CHARS = 20

_engine = None
_engine_lock = threading.Lock()


@dataclass
class OcrResult:
    lines: list[str]   # 읽은 순서대로의 글자 줄
    rotation: int      # 고른 방향 (0, 180, 270)
    runs: int          # OCR을 몇 번 돌렸나. 보통 1, 누운·뒤집힌 사진은 3
    ocr_ms: int


def _get_engine():
    """RapidOCR 엔진을 한 번만 만든다. 모델 로드가 요청마다 반복되지 않게 한다.

    모델: PaddleOCR PP-OCRv5 mobile을 ONNX로 바꾼 것 (글자 위치 ch_det_mobile, 읽기 korean_rec_mobile).
    한국어 모델이 영어도 읽는다. Paddle 엔진 그대로는 B/L 한 장에 약 20초, ONNX Runtime은 약 2초였다 (09-29 Mac M2).
    import를 여기서 하는 이유: rapidocr는 무겁고, 이 기능을 안 쓰는 테스트·워커가 불러올 필요가 없다.
    """
    global _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

            _engine = RapidOCR(params={
                "Global.use_cls": False,  # 줄 단위 180° 판별은 끈다. 방향은 read_lines()가 페이지 단위로 맞춘다
                "Global.log_level": "warning",
                "Det.ocr_version": OCRVersion.PPOCRV5, "Det.model_type": ModelType.MOBILE,
                "Rec.lang_type": LangRec.KOREAN, "Rec.ocr_version": OCRVersion.PPOCRV5,
                "Rec.model_type": ModelType.MOBILE,
            })
        return _engine


def remove_red(img: Image.Image) -> Image.Image:
    """진한 빨간 픽셀을 흰색으로 칠한다. 빨간 도장이 값 위에 찍히면 `MRVA2026090001`이 `MRV60001`로 잘렸다.
    지우고 나니 3/8 → 8/8 (09-29). 빨간 도장·워터마크에만 듣는다. 파란·검은 도장은 그대로다."""
    a = np.asarray(img.convert("RGB")).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    a[(r > 150) & (r - g > 60) & (r - b > 60)] = 255
    return Image.fromarray(a.astype(np.uint8))


def read_lines(image_bytes: bytes, engine=None) -> OcrResult:
    """사진 바이트를 OCR 글자 줄로 바꾼다. 0°를 먼저 읽고, 확신이 낮으면 180°·270°도 읽어 가장 나은 방향을 쓴다.

    90°를 안 읽는 이유: OCR이 세로로 긴 글자 상자를 스스로 돌려 읽어서, 한쪽으로 누운 사진은 0°에서 이미 읽힌다.
    반대쪽으로 누운 사진은 270°, 뒤집힌 사진은 180°가 맡는다 (09-29 실험, 90° 회전 사진 0/8 → 8/8).
    Raises:
        PIL.UnidentifiedImageError: 이미지가 아닐 때. 라우터가 400으로 바꾼다
    """
    engine = engine or _get_engine()
    img = remove_red(Image.open(BytesIO(image_bytes)))
    start = time.monotonic()
    best: tuple[float, int, list[str]] | None = None
    runs = 0
    for deg in (0, 180, 270):
        out = engine(np.asarray(img.rotate(deg, expand=True)))
        runs += 1
        scores = list(out.scores or [])
        total = sum(scores)  # 많이, 확실하게 읽을수록 크다
        if best is None or total > best[0] * ROTATION_MARGIN:
            best = (total, deg, list(out.txts or []))
        if deg == 0 and len(scores) >= CONFIDENT_LINES and total / len(scores) >= CONFIDENT_MEAN:
            break  # 보통 서류: 한 번이면 된다
    return OcrResult(lines=best[2], rotation=best[1], runs=runs, ocr_ms=int((time.monotonic() - start) * 1000))


def take_bl(lines: list[str]) -> str | None:
    """B/L 이름표를 찾고, 같은 줄 → 뒤 두 줄 → 앞 두 줄 순서로 B/L 형식에 맞는 값을 찾는다.

    형식만으로 고르지 않는 이유: 컨테이너 번호(TEMU1235474)도 같은 형식이라 이름표 없이는 구분이 안 된다.
    앞줄도 보는 이유: 기울어진 사진에서는 오른쪽 값 칸이 이름표보다 위로 올라가 OCR이 값을 먼저 읽었다 (09-29).
    같은 줄을 먼저 보는 이유: 문장형 안내문은 "B/L 번호 MRVA2026090001, 품명 …"처럼 한 줄에 있다 (09-29).
    """
    for i, line in enumerate(lines):
        m = BL_LABEL.search(line)
        if not m:
            continue
        for tok in re.findall(r"[A-Za-z0-9]+", line[m.end():]):
            if _BL_PATTERN.fullmatch(tok.upper()):
                return tok.upper()
        for cand in lines[i + 1:i + 3] + lines[max(0, i - 2):i][::-1]:
            c = cand.replace(" ", "").upper()
            if _BL_PATTERN.fullmatch(c):
                return c
    return None


def mask_bl(lines: list[str], bl: str | None) -> str:
    """LLM에 넘길 글자. B/L 번호를 [BL]로 가린다 (CLAUDE.md "B/L 번호를 LLM에 넘기지 않는다").

    Raises:
        ValueError: 가린 뒤에도 B/L이 남아 있을 때. 이 경우 LLM을 부르지 않는다
    """
    if not bl:
        return "\n".join(lines)
    masked = [("[BL]" if l.replace(" ", "").upper() == bl else l.replace(bl, "[BL]")) for l in lines]
    text = "\n".join(masked)
    if bl in text.replace(" ", "").upper():
        raise ValueError("B/L 번호가 가려지지 않았습니다")
    return text


def norm(s: str) -> str:
    """비교용: 대문자로 바꾸고 공백·문장부호를 뺀다. "HEUNG-A  JANICE" == "HEUNGAJANICE".
    O/0, I/1은 합치지 않는다. B/L 번호가 한 글자 틀리면 틀린 것이다."""
    return re.sub(r"[\s\-./,:()]", "", s.upper())


def dates_in(text: str) -> set[datetime.date]:
    """OCR 글자에 적힌 날짜 전부. LLM은 YYYY-MM-DD로 답하므로 "02-OCT-2026"이나 "2026년 10월 2일"과
    글자로 비교하면 맞는 답도 틀렸다고 나온다 (09-29 영어 서식). 날짜끼리 비교한다."""
    found = []
    for y, mo, d in re.findall(r"(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})", text):
        found.append((int(y), int(mo), int(d)))
    # 달 이름 자리에서만 숫자 0을 알파벳 O로 본다. OCR이 OCT를 "0CT"로 읽었다 (09-29)
    for d, mon, y in re.findall(r"(\d{1,2})[- ]?([A-Z0]{3})[- ]?(\d{4})", text.upper()):
        mon = mon.replace("0", "O")
        if mon in MONTHS:
            found.append((int(y), MONTHS[mon], int(d)))
    out = set()
    for y, mo, d in found:
        try:
            out.add(datetime.date(y, mo, d))
        except ValueError:
            pass
    return out


def strip_ship_suffix(vessel: str | None) -> str | None:
    """한국어 안내문은 "SEA STAR호"처럼 배 이름 뒤에 '호'를 붙인다. LLM이 그대로 옮겨 틀렸다 (09-29).
    영문 선명일 때만 뗀다. 한글 선명은 '호'까지가 이름일 수 있다."""
    if vessel and vessel.endswith("호") and vessel[:-1].strip().isascii():
        return vessel[:-1].strip()
    return vessel


def label_lines(lines: list[str], key: str) -> int:
    """그 칸의 이름표로 보이는 줄 수. 이름표 줄 = 칸 이름이 들어 있고 짧은 줄 (LABEL_MAX_CHARS)."""
    pattern = FIELD_LABELS[key]
    return sum(1 for line in lines if pattern.search(line) and len(norm(line)) <= LABEL_MAX_CHARS)


def check_fields(fields: dict[str, str | None], lines: list[str]) -> dict[str, list[str]]:
    """칸마다 걸린 검사 이름 목록. 빈 목록이면 통과. 하나라도 걸리면 사용자 확인이 필요하다.

    missing      값이 없다
    not_in_text  OCR 글자에 그 값이 없다. LLM이 지어냈거나 고쳐 쓴 경우 (날짜는 날짜끼리 비교)
    format       항차·날짜 모양이 아니다
    ambiguous    그 칸의 이름표가 서류에 두 번 이상 있다 (가짜 정정 행 등). 값이 맞아도 사용자 확인으로 넘긴다
    칸끼리 뒤바뀐 경우(선명 자리에 선적항)는 여기서 못 잡는다. 사용자 확인 화면이 막는다 (Spec EC-07).
    """
    text = "\n".join(lines)
    ocr_dates = dates_in(text)
    result: dict[str, list[str]] = {}
    for key in FIELDS:
        value = fields.get(key)
        fails: list[str] = []
        if value is None or value == "":
            fails.append("missing")
        elif key == "eta":
            try:
                if datetime.date.fromisoformat(value) not in ocr_dates:
                    fails.append("not_in_text")
            except ValueError:
                fails.append("format")
        else:
            if norm(value) not in norm(text):
                fails.append("not_in_text")
            if key == "voyage" and not VOYAGE_PATTERN.fullmatch(value):
                fails.append("format")
        if key in FIELD_LABELS and label_lines(lines, key) > 1:
            fails.append("ambiguous")
        result[key] = fails
    return result
