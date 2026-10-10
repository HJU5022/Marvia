"""Vision stage 2 on the fabricated Korean arrival notice: OCR text -> fields.

Responsibility: for each ko_notice image,
  1) RapidOCR (Korean mobile, ONNX) reads the lines,
  2) code takes the B/L number (value right after the "B/L NO." label, checked
     with the project's own _BL_PATTERN) and MASKS it before any LLM call,
  3) the small LLM (Gemini 2.5 Flash on Vertex, thinking off - same path as
     backend/app/services/llm.py) fills vessel / voyage / ETA / ports / item,
  4) code checks format + "the value really appears in the OCR text".
     A failed check means "send this image to the large vision model" (not run here).
Why: stage 1 only proved the characters are read. Stage 2 measures whether each
value is paired with the right label - the part OCR alone cannot do.
Reference: wiki 프로젝트/Marvia-모델-선정.md "비전" row; PRD rule "B/L is not passed to the LLM".
Only the FABRICATED notice is sent to Vertex (user decision 09-29). The real B/L is not used.

Usage: .venv/bin/python stage2.py [samples|layouts]
"""
import datetime
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

from compare_ocr import norm
from preprocess import read_lines

HERE = Path(__file__).parent
PROJECT = "marvia-510003"
URL = f"https://aiplatform.googleapis.com/v1/projects/{PROJECT}/locations/global/endpoints/openapi/chat/completions"
MODEL = "google/gemini-2.5-flash"

BL_PATTERN = re.compile(r"^[A-Z0-9]{8,20}$")  # copied from backend/app/schemas/agent.py:24
# Label variants: "B/L NO.", "B/L No", "B/L 번호", "Bill of Lading No" (sentence layout used "B/L 번호", 09-29).
BL_LABEL = re.compile(r"(B\s*/?\s*L|BILL\s+OF\s+LADING)\s*(NO|번호|#|NUMBER)", re.I)
MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                                      "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}

TRUTH = {"bl_no": "MRVA2026090001", "vessel": "SEA STAR", "voyage": "0925W", "eta": "2026-10-02",
         "pol": "QINGDAO, CHINA", "pod": "부산 신항", "item": "건고추"}

PROMPT = """You extract fields from OCR text of a Korean import arrival notice.
The OCR text lists table labels and values as separate lines, in reading order.
Return JSON only: {"vessel": str|null, "voyage": str|null, "eta": "YYYY-MM-DD"|null,
"pol": str|null, "pod": str|null, "item": str|null}
- vessel/voyage are often written together as "VESSEL / VOYAGE": split them.
- Copy values exactly as written. If a field is not in the text, use null. Never guess.

OCR text:
"""


def ocr_engine():
    return RapidOCR(params={
        "Global.use_cls": False, "Global.log_level": "warning",
        "Det.ocr_version": OCRVersion.PPOCRV5, "Det.model_type": ModelType.MOBILE,
        "Rec.lang_type": LangRec.KOREAN, "Rec.ocr_version": OCRVersion.PPOCRV5,
        "Rec.model_type": ModelType.MOBILE,
    })


def take_bl(lines):
    # The B/L value is a line next to the label that fits the project's pattern.
    # Look after the label first, then before it: on a tilted photo the value column
    # rises above its label, so OCR reads the value first (seen on ko_notice__tilt3, 09-29).
    for i, line in enumerate(lines):
        m = BL_LABEL.search(line)
        if m:
            # Same line first: a sentence like "B/L 번호 MRVA2026090001, ..." has the value inline.
            for tok in re.findall(r"[A-Za-z0-9]+", line[m.end():]):
                if BL_PATTERN.fullmatch(tok.upper()):
                    return tok.upper()
            for cand in lines[i + 1:i + 3] + lines[max(0, i - 2):i][::-1]:
                c = cand.replace(" ", "").upper()
                if BL_PATTERN.fullmatch(c):
                    return c
    return None


def ask_llm(text, token):
    body = {"model": MODEL, "messages": [{"role": "user", "content": PROMPT + text}],
            "response_format": {"type": "json_object"}, "temperature": 0,
            "extra_body": {"google": {"thinking_config": {"thinking_budget": 0}}}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    # Same retry rule as backend llm.py: 429/503 -> wait 2 s, at most 2 retries.
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.load(r)
            break
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or attempt == 2:
                raise
            time.sleep(2)
    return json.loads(data["choices"][0]["message"]["content"]), data.get("usage", {})


def dates_in(text):
    """Every date written in the OCR text, in the formats seen so far, as date objects.

    The LLM is asked for YYYY-MM-DD, so "02-OCT-2026" or "2026년 10월 2일" in the text
    must be compared as dates, not as strings (string check wrongly failed them, 09-29).
    """
    found = []
    for y, mo, d in re.findall(r"(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})", text):
        found.append((int(y), int(mo), int(d)))
    # Month names: OCR reads the letter O as zero ("02-0CT-2026", english_form 09-29), so fix 0->O there only.
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


def strip_ship_suffix(vessel):
    # Korean text writes "SEA STAR호" (호 = ship). Drop it only for Latin ship names (09-29).
    if vessel and vessel.endswith("호") and vessel[:-1].strip().isascii():
        return vessel[:-1].strip()
    return vessel


def check(fields, ocr_text):
    # Returns the list of failed checks. Any failure -> escalate to the large vision model.
    fails = []
    for k, v in fields.items():
        if v is None:
            fails.append(f"{k}:missing")
        elif k == "eta":
            continue  # dates are grounded below by value, not by spelling
        elif norm(v) not in norm(ocr_text):  # grounding: must be copied from the OCR text
            fails.append(f"{k}:not_in_text")
    if fields.get("voyage") and not re.fullmatch(r"[A-Z0-9]{3,8}", fields["voyage"]):
        fails.append("voyage:format")
    try:
        eta = datetime.date.fromisoformat(fields.get("eta") or "")
        if eta not in dates_in(ocr_text):
            fails.append("eta:not_in_text")
    except ValueError:
        if fields.get("eta") is not None:
            fails.append("eta:format")
    return fails


# Stage-2 layouts the prompt was NOT written for (make_messy.py). Each field lists accepted answers.
LAYOUT_TRUTH = {
    "two_col": {k: [v] for k, v in TRUTH.items()},
    "english_form": {"bl_no": ["MRVA2026090001"], "vessel": ["SEA STAR"], "voyage": ["0925W"],
                     "eta": ["2026-10-02"], "pol": ["QINGDAO, CHINA"], "pod": ["BUSAN NEW PORT, KOREA"],
                     "item": ["DRIED RED PEPPER", "120 BAGS OF DRIED RED PEPPER"]},
    "sentence": {"bl_no": ["MRVA2026090001"], "vessel": ["SEA STAR"], "voyage": ["0925W"], "eta": ["2026-10-02"],
                 "pol": ["QINGDAO", "중국 QINGDAO"], "pod": ["부산 신항"], "item": ["건고추", "건고추 120포"]},
}


def main(which="samples"):
    # which="samples": the 6 ko_notice images (first run). which="layouts": the 3 new layouts.
    token = subprocess.run(["gcloud", "auth", "application-default", "print-access-token"],
                           capture_output=True, text=True, check=True).stdout.strip()
    ocr = ocr_engine()
    rows = []
    if which == "layouts":
        cases = [(HERE / "layouts" / f"{n}.png", t) for n, t in LAYOUT_TRUTH.items()]
    else:
        cases = [(img, {k: [v] for k, v in TRUTH.items()}) for img in sorted((HERE / "samples").glob("ko_notice*"))]
    for img, truth in cases:
        t0 = time.perf_counter()
        lines, rot, runs = read_lines(ocr, img)  # red-stamp removal + rotation (preprocess.py)
        t_ocr = time.perf_counter() - t0

        bl = take_bl(lines)
        masked = "\n".join(("[BL]" if l.replace(" ", "").upper() == bl else l.replace(bl, "[BL]")) if bl else l
                           for l in lines)
        assert bl is None or bl not in masked.replace(" ", "").upper(), "B/L leaked into LLM input"

        t0 = time.perf_counter()
        fields, usage = ask_llm(masked, token)
        t_llm = time.perf_counter() - t0

        got = {"bl_no": bl, **{k: fields.get(k) for k in ("vessel", "voyage", "eta", "pol", "pod", "item")}}
        got["vessel"] = strip_ship_suffix(got["vessel"])
        correct = {k: (got[k] is not None and any(norm(got[k]) == norm(a) for a in alts)) for k, alts in truth.items()}
        fails = check(got, "\n".join(lines))
        rows.append({"image": img.name, "ocr_s": round(t_ocr, 2), "llm_s": round(t_llm, 2), "got": got,
                     "correct": correct, "check_fails": fails, "usage": usage})
        wrong = {k: got[k] for k, ok in correct.items() if not ok}
        print(f"{img.name:24s} {sum(correct.values())}/7  rot {rot} x{runs}  ocr {t_ocr:.2f}s  llm {t_llm:.2f}s  "
              f"check={'PASS' if not fails else fails}  wrong={wrong}")
    (HERE / "results" / f"report_stage2_{which}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else "samples")
