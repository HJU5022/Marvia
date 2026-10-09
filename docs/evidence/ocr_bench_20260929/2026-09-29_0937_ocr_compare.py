"""Compare local OCR candidates for vision stage 1 (OCR -> regex/small LLM).

Responsibility: run each OCR engine on every image in samples/, check whether
each ground-truth field value appears in the OCR text, and time it.
Why this metric: stage 2 (regex for B/L, small LLM for vessel/ETA) can only
extract what OCR actually read. So "is the exact value present in the text"
is the ceiling for the whole pipeline. It does not measure layout (which
value belongs to which label) - that is checked later with the small LLM.
Reference: wiki 프로젝트/Marvia-모델-선정.md "비전" row (2-stage, 09-29).

Usage: .venv/bin/python compare_ocr.py   (writes results/)
"""
import json
import re
import time
from pathlib import Path

HERE = Path(__file__).parent
SAMPLES = HERE / "samples"
RESULTS = HERE / "results"

# Ground truth read by eye from the source documents.
# bl = real B/L scan (English only), ko_notice = fabricated Korean notice.
TRUTH = {
    "bl": {
        "bl_no": "HASLC03260802028",
        "vessel": "HEUNG-A JANICE",
        "voyage": "2634E",
        "container": "TEMU1235474",
        "pol": "QINGDAO",
        "pod": "BUSAN",
        "onboard_date": "2026.9.12",
    },
    "ko_notice": {
        "bl_no": "MRVA2026090001",
        "vessel": "SEA STAR",
        "voyage": "0925W",
        "pol": "QINGDAO",
        "pod_ko": "부산 신항",
        "eta": "2026-10-02",
        "item_ko": "건고추",
        "consignee_ko": "가나다무역",
    },
}


def norm(s: str) -> str:
    # Uppercase and drop spaces/punctuation so "HEUNG-A  JANICE" == "HEUNGAJANICE".
    # O/0 and I/1 are NOT merged on purpose: a B/L number with a wrong digit is a miss.
    return re.sub(r"[\s\-./,:()]", "", s.upper())


def make_engines():
    # Each engine: (name, loader). Loading is timed separately from reading.
    def paddle(rec_model):
        from paddleocr import PaddleOCR
        ocr = PaddleOCR(
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_recognition_model_name=rec_model,
            # Extra pre-processing models are off to keep the mobile setup small/fast.
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )

        def read(path):
            texts = []
            for res in ocr.predict(str(path)):
                texts.extend(res["rec_texts"])
            return texts
        return read

    def easy():
        import easyocr
        reader = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
        return lambda path: reader.readtext(str(path), detail=0)

    return [
        ("paddle_default(ch/en/ja)", lambda: paddle("PP-OCRv5_mobile_rec")),
        ("paddle_korean", lambda: paddle("korean_PP-OCRv5_mobile_rec")),
        ("easyocr(ko+en)", easy),
    ]


def main():
    RESULTS.mkdir(exist_ok=True)
    images = sorted(SAMPLES.iterdir())
    report = []
    for name, loader in make_engines():
        t0 = time.perf_counter()
        read = loader()
        load_s = time.perf_counter() - t0
        read(images[0])  # warm-up, not timed
        for img in images:
            doc = img.stem.split("__")[0]
            t0 = time.perf_counter()
            texts = read(img)
            sec = time.perf_counter() - t0
            joined = norm(" ".join(texts))
            hits = {k: norm(v) in joined for k, v in TRUTH[doc].items()}
            report.append({"engine": name, "image": img.name, "sec": round(sec, 2),
                           "load_s": round(load_s, 1), "hits": hits})
            (RESULTS / f"{name.split('(')[0]}__{img.stem}.txt").write_text("\n".join(texts), encoding="utf-8")
            print(f"{name:26s} {img.name:24s} {sum(hits.values())}/{len(hits)}  {sec:.2f}s  miss={[k for k, h in hits.items() if not h]}")
    (RESULTS / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
