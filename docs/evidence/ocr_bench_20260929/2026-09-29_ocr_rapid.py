"""Same Korean mobile PaddleOCR models, run through ONNX Runtime (RapidOCR).

Responsibility: run all 12 samples with RapidOCR using the SAME models as the
09-29 winner (PP-OCRv5 mobile det + korean_PP-OCRv5 mobile rec), and report
field hits and time in the same way as compare_ocr.py / speed_ocr.py.
Why: speed_ocr.py showed ~20 s per B/L is almost all recognition, and the Mac
Paddle build has no oneDNN CPU acceleration. ONNX Runtime is accelerated on
both Mac ARM and x86, so a speed-up here should carry over to Cloud Run [guess].
Accuracy must stay at 89/90, otherwise the conversion changed the model.

Usage: .venv/bin/python rapid_ocr.py
"""
import json
import statistics
import time
from pathlib import Path

from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

from compare_ocr import TRUTH, norm

HERE = Path(__file__).parent
SAMPLES = HERE / "samples"
RESULTS = HERE / "results"


def main():
    engine = RapidOCR(params={
        "Global.use_cls": False,  # text-line rotation off, same as the Paddle run
        "Global.log_level": "warning",
        "Det.ocr_version": OCRVersion.PPOCRV5,
        "Det.model_type": ModelType.MOBILE,
        "Rec.lang_type": LangRec.KOREAN,
        "Rec.ocr_version": OCRVersion.PPOCRV5,
        "Rec.model_type": ModelType.MOBILE,
    })

    def read(path):
        out = engine(str(path))
        return list(out.txts or [])

    images = sorted(SAMPLES.iterdir())
    read(images[0])  # warm-up
    report, total_hits, total = [], 0, 0
    for img in images:
        times = []
        for _ in range(3):
            t0 = time.perf_counter()
            texts = read(img)
            times.append(time.perf_counter() - t0)
        sec = statistics.median(times)
        truth = TRUTH[img.stem.split("__")[0]]
        joined = norm(" ".join(texts))
        hits = {k: norm(v) in joined for k, v in truth.items()}
        total_hits += sum(hits.values())
        total += len(hits)
        report.append({"engine": "rapidocr_korean_mobile", "image": img.name, "sec": round(sec, 2), "hits": hits})
        (RESULTS / f"rapid__{img.stem}.txt").write_text("\n".join(texts), encoding="utf-8")
        print(f"{img.name:24s} {sum(hits.values())}/{len(hits)}  {sec:5.2f}s  lines={len(texts)}  miss={[k for k, h in hits.items() if not h]}")
    print(f"TOTAL {total_hits}/{total}")
    (RESULTS / "report_rapid.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
