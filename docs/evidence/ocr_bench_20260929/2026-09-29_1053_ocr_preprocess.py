"""OCR front end used by read_test.py and stage2.py: red-stamp removal + page rotation.

Responsibility: turn one image into OCR lines, fixing the two failures found on 09-29
(stamp 3/8, 90-degree photo 0/8; both 8/8 after the fixes in preprocess_try.py).
  - remove_red: paint strongly red pixels white (red stamps only).
  - read_lines: OCR at 0 deg first; if that read is already confident, stop.
    Otherwise also try 180 and 270 and keep the clearly (5%+) best one.
Why only 0/180/270: OCR already reads a page turned one way (it rotates tall
text boxes itself), so 90 is covered by 0; the other sideways case needs 270,
upside-down needs 180. Upright is kept on ties because 270 on an upright page
scores the same but returns the lines in reverse order (seen 09-29).
Reference: wiki 프로젝트/Marvia-근거-원장.md "전처리 2종 시도".
"""
import numpy as np
from PIL import Image

CONFIDENT_MEAN = 0.9  # mean line confidence of a normal upright page was ~0.98 (09-29)
CONFIDENT_LINES = 5


def remove_red(img):
    a = np.asarray(img.convert("RGB")).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    a[(r > 150) & (r - g > 60) & (r - b > 60)] = 255
    return Image.fromarray(a.astype(np.uint8))


def read_lines(ocr, path):
    """Return (lines, rotation_degrees, number_of_ocr_runs)."""
    img = remove_red(Image.open(path))
    best, runs = None, 0
    for deg in (0, 180, 270):
        out = ocr(np.asarray(img.rotate(deg, expand=True)))
        runs += 1
        scores = list(out.scores or [])
        total = sum(scores)
        if best is None or total > best[0] * 1.05:
            best = (total, deg, list(out.txts or []))
        if deg == 0 and len(scores) >= CONFIDENT_LINES and total / len(scores) >= CONFIDENT_MEAN:
            break  # normal upright page: one read is enough
    return best[2], best[1], runs
