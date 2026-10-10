"""Reading-only test by damage type and on real web documents (stage 1 only).

Responsibility: run RapidOCR (ONNX) on messy/ (10 damage types of the fabricated
notice) and web/ (4 real arrival notices from help.easyisf.com + an 1853
handwritten B/L from Wikimedia Commons), and report which ground-truth values
appear in the OCR text. Two recognizers: Korean (our pick) and the default
Chinese/English/Japanese one, to show what mixed Chinese text needs.
Why: the first test used one clean fabricated layout; this finds where reading
itself breaks, before any label-value pairing (stage 2).
Web documents stay local: no LLM call, no commit (user decision 09-29).
Ground truth for web/ was read by eye; B/L numbers there are redacted by the source.

Usage: .venv/bin/python read_test.py
"""
import json
import time
from pathlib import Path

from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

from compare_ocr import norm
from preprocess import read_lines

HERE = Path(__file__).parent

BASE = {"bl_no": "MRVA2026090001", "vessel": "SEA STAR", "voyage": "0925W", "pol": "QINGDAO, CHINA",
        "pod_ko": "부산 신항", "eta": "2026-10-02", "item_ko": "건고추", "consignee_ko": "가나다무역"}
TRUTH = {name: BASE for name in ("stamp", "shadow", "perspective", "crumple", "fax", "tiny", "rot90",
                                  "watermark", "handwriting")}
TRUTH["mixed_cjk"] = {**BASE, "shipper_zh": "青岛红辣椒贸易有限公司", "item_zh": "干辣椒"}
TRUTH.update({
    "an_easyisf_1": {"vessel": "SUNSHINE ACE", "voyage": "108A", "pol": "YOKOHAMA, JAPAN",
                     "pod": "Jacksonville, Florida", "eta": "05/25/24", "firms": "N278",
                     "weight": "810 kgs", "total": "$176.00"},
    "an_easyisf_2": {"vessel_voy": "EVER FUTURE 1110E", "pol": "QINGDAO", "pod": "LOS ANGELES,CA",
                     "eta": "APR/19", "hbl": "SHP0360", "invoice_date": "17-APR-2024", "weight": "800.000",
                     "under_watermark_1": "TOTAL ONE PACKAGE ONLY", "under_watermark_2": "FREEHAND SHIPMENT"},
    "an_easyisf_3": {"vessel": "MAERSK MONTE AZUL", "voyage": "417N", "pol": "Santos, SP, Brazil",
                     "pod": "Port Everglades, FL, USA", "firms": "N751", "weight": "26620.000 KGS",
                     "item": "GREEN COFFEE BEANS", "date": "2024-05-30"},
    "an_easyisf_4": {"flight": "CZ437", "arrival": "05/09/2024", "port": "ORD", "firms_I_not_1": "I225",
                     "pcs_weight": "60 / 416.00 KG", "airline": "China Southern Airlines"},
    "bl_1853_handwritten": {"print_port": "Port of Boston", "print_dest": "San Francisco",
                            "print_line": "LINE OF PACKETS", "hand_ship": "Carrier Pigeon",
                            "hand_name": "Pierce", "hand_date": "Jan 21", "hand_amount": "Ten"},
})


def engine(lang):
    return RapidOCR(params={
        "Global.use_cls": False, "Global.log_level": "warning",
        "Det.ocr_version": OCRVersion.PPOCRV5, "Det.model_type": ModelType.MOBILE,
        "Rec.lang_type": lang, "Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.model_type": ModelType.MOBILE,
    })


def main():
    images = sorted((HERE / "messy").iterdir()) + sorted((HERE / "web").iterdir())
    engines = {"korean": engine(LangRec.KOREAN), "default_ch": engine(LangRec.CH)}
    report = []
    for ename, ocr in engines.items():
        ocr(str(images[0]))  # warm-up
        got_all = tot_all = 0
        for img in images:
            truth = TRUTH[img.stem]
            t0 = time.perf_counter()
            texts, rot, runs = read_lines(ocr, img)  # red-stamp removal + rotation (preprocess.py)
            sec = time.perf_counter() - t0
            joined = norm(" ".join(texts))
            hits = {k: norm(v) in joined for k, v in truth.items()}
            got_all += sum(hits.values())
            tot_all += len(hits)
            report.append({"engine": ename, "image": img.name, "sec": round(sec, 2), "rot": rot, "runs": runs, "hits": hits})
            (HERE / "results" / f"read_pre_{ename}__{img.stem}.txt").write_text("\n".join(texts), encoding="utf-8")
            print(f"{ename:10s} {img.name:26s} {sum(hits.values())}/{len(hits)}  {sec:5.2f}s rot {rot} x{runs}  "
                  f"miss={[k for k, h in hits.items() if not h]}")
        print(f"{ename} TOTAL {got_all}/{tot_all}\n")
    (HERE / "results" / "report_read_pre.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
