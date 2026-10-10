"""Build harder test images: 10 kinds of "messy" + 3 new notice layouts.

Responsibility:
  messy/   - the SAME fabricated Korean notice, each damaged in one way
             (stamp, shadow, perspective, crumple, fax, tiny text, 90 deg,
             watermark, handwriting-like values, mixed Korean/English/Chinese).
             Used for the reading-only test (read_test.py).
  layouts/ - 3 fabricated notices with layouts the stage-2 prompt has never
             seen (two-column table, English form, plain sentence letter).
             Used for stage 2 (stage2.py) to see if label-value pairing holds.
Why: the first stage-2 run used one clean layout the prompt was written for,
so 42/42 was likely optimistic (09-29). Every name/number here is fake.
Reference: wiki 프로젝트/Marvia-근거-원장.md "OCR 1단계 후보 비교".

Usage: .venv/bin/python make_messy.py
"""
import math
import random
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).parent
KO = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
HAND_EN = "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf"
ZH = "/System/Library/Fonts/Supplemental/Songti.ttc"
W, H = 1240, 1754  # A4 at 150 dpi

ROWS = [("수하인", "가나다무역"), ("B/L NO.", "MRVA2026090001"), ("선명 / 항차", "SEA STAR / 0925W"),
        ("선적항", "QINGDAO, CHINA"), ("양하항", "부산 신항"), ("입항 예정일 (ETA)", "2026-10-02"),
        ("품명", "건고추"), ("수량 / 중량", "120 BAGS / 2,400 KGS")]
random.seed(7)  # same "handwriting" every run


def font(path, size):
    return ImageFont.truetype(path, size)


def draw_jittered(d, xy, text, path, size):
    # Handwriting stand-in: each character gets its own size, tilt and offset.
    x, y = xy
    for ch in text:
        s = int(size * random.uniform(0.85, 1.15))
        f = font(path, s)
        glyph = Image.new("RGBA", (s * 2, s * 2), (0, 0, 0, 0))
        ImageDraw.Draw(glyph).text((s // 2, s // 3), ch, font=f, fill=(20, 20, 60, 255))
        glyph = glyph.rotate(random.uniform(-12, 12), resample=Image.BICUBIC)
        d._image.paste(glyph, (int(x - s // 2), int(y + random.uniform(-6, 6) - s // 3)), glyph)
        x += f.getlength(ch) * random.uniform(0.95, 1.1)


def notice(rows=ROWS, body=34, value_style="plain", extra=()):
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.text((380, 90), "화물 도착 통지서", font=font(KO, 56), fill="black")
    d.text((80, 190), "(주)가나다포워딩  부산광역시 중구 중앙대로 000", font=font(KO, max(body - 4, 12)), fill="black")
    row_h = int(body * 2.6)
    y = 300
    for label, value in list(rows) + list(extra):
        d.rectangle([80, y, 1160, y + row_h], outline="black", width=2)
        d.line([440, y, 440, y + row_h], fill="black", width=2)
        label_font = ZH if any("\u4e00" <= c <= "\u9fff" for c in label) else KO  # Korean font has no Chinese glyphs
        d.text((100, y + row_h // 4), label, font=font(label_font, body), fill="black")
        vx, vy = 460, y + row_h // 4
        if value_style == "hand":
            if value.isascii():
                d.text((vx, vy - 4), value, font=font(HAND_EN, body + 4), fill=(20, 20, 60))
            else:
                draw_jittered(d, (vx, vy), value, KO, body)
        elif any("一" <= c <= "鿿" for c in value):
            d.text((vx, vy), value, font=font(ZH, body), fill="black")
        else:
            d.text((vx, vy), value, font=font(KO, body), fill="black")
        y += row_h
    d.text((80, y + 60), "※ 화물 반출 전 운임 및 부대비용을 정산하여 주시기 바랍니다.", font=font(KO, max(body - 4, 12)), fill="black")
    return img


# ---- damage functions: each takes and returns a PIL image ----

def stamp(img):
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    for cx, cy, word in ((620, 420, "통관필"), (900, 700, "RECEIVED"), (640, 900, "확인")):
        d.ellipse([cx - 130, cy - 130, cx + 130, cy + 130], outline=(210, 30, 30, 170), width=10)
        d.text((cx - 100, cy - 30), word, font=font(KO, 52), fill=(210, 30, 30, 170))
    return Image.alpha_composite(img.convert("RGBA"), over).convert("RGB")


def shadow(img):
    a = np.asarray(img).astype(np.float32)
    ramp = np.linspace(0.30, 1.0, img.width)[None, :, None]  # left side at 30% light
    return Image.fromarray((a * ramp).clip(0, 255).astype(np.uint8))


def perspective(img):
    a = np.asarray(img)
    w, h = img.width, img.height
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[w * 0.10, h * 0.04], [w * 0.93, 0], [w, h], [0, h * 0.97]])
    m = cv2.getPerspectiveTransform(src, dst)
    return Image.fromarray(cv2.warpPerspective(a, m, (w, h), borderValue=(200, 195, 185)))


def crumple(img):
    a = np.asarray(img)
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    map_x = xx + 6 * np.sin(yy / 45.0)
    map_y = yy + 5 * np.sin(xx / 60.0)
    out = Image.fromarray(cv2.remap(a, map_x, map_y, cv2.INTER_LINEAR, borderValue=(255, 255, 255)))
    d = ImageDraw.Draw(out)
    for y in (h // 3, 2 * h // 3):  # folds: dark crease + light edge
        d.line([0, y, w, y + 15], fill=(120, 120, 120), width=4)
        d.line([0, y + 5, w, y + 20], fill=(245, 245, 245), width=3)
    return out


def fax(img):
    g = img.convert("L").resize((img.width // 2, img.height // 2))
    a = (np.asarray(g) > 150).astype(np.uint8) * 255
    noise = np.random.default_rng(1).random(a.shape)
    a[noise < 0.02] = 0
    a[noise > 0.985] = 255
    return Image.fromarray(a).resize(img.size, Image.NEAREST).convert("RGB")


def watermark(img):
    over = Image.new("RGBA", (img.width * 2, img.height * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    for y in range(0, over.height, 160):
        for x in range(0, over.width, 420):
            d.text((x, y), "COPY 사본", font=font(KO, 60), fill=(90, 90, 90, 90))
    over = over.rotate(30).crop((img.width // 2, img.height // 2, img.width * 3 // 2, img.height * 3 // 2))
    return Image.alpha_composite(img.convert("RGBA"), over).convert("RGB")


# ---- stage-2 layouts the prompt has never seen ----

def layout_two_col():
    img = Image.new("RGB", (W, 900), "white")
    d = ImageDraw.Draw(img)
    d.text((420, 50), "수입화물 도착 안내", font=font(KO, 50), fill="black")
    pairs = [("B/L NO.", "MRVA2026090001", "품명", "건고추"),
             ("선명", "SEA STAR", "항차", "0925W"),
             ("선적항", "QINGDAO, CHINA", "양하항", "부산 신항"),
             ("ETA", "2026-10-02", "수하인", "가나다무역")]
    y = 180
    for l1, v1, l2, v2 in pairs:
        for x0, lab, val in ((60, l1, v1), (640, l2, v2)):
            d.rectangle([x0, y, x0 + 540, y + 90], outline="black", width=2)
            d.line([x0 + 170, y, x0 + 170, y + 90], fill="black", width=2)
            d.text((x0 + 15, y + 25), lab, font=font(KO, 30), fill="black")
            d.text((x0 + 185, y + 25), val, font=font(KO, 30), fill="black")
        y += 90
    return img


def layout_english():
    img = Image.new("RGB", (W, 1100), "white")
    d = ImageDraw.Draw(img)
    d.text((440, 50), "ARRIVAL NOTICE", font=font(KO, 50), fill="black")
    boxes = [("B/L No", "MRVA2026090001", 60, 160), ("Vessel", "SEA STAR", 60, 300), ("Voyage No", "0925W", 640, 300),
             ("Port of Loading", "QINGDAO, CHINA", 60, 440), ("Port of Discharge", "BUSAN NEW PORT, KOREA", 640, 440),
             ("Estimated Time of Arrival", "02-OCT-2026", 60, 580),
             ("Description of Goods", "120 BAGS OF DRIED RED PEPPER", 60, 720)]
    for label, value, x, y in boxes:
        d.rectangle([x, y, x + 1120 if x == 60 and label.startswith(("B/L", "Desc", "Est")) else x + 540, y + 120],
                    outline="black", width=2)
        d.text((x + 12, y + 10), label, font=font(KO, 22), fill="black")
        d.text((x + 12, y + 55), value, font=font(KO, 34), fill="black")
    return img


def layout_sentence():
    img = Image.new("RGB", (W, 900), "white")
    d = ImageDraw.Draw(img)
    lines = ["가나다무역 귀하", "",
             "귀사의 수입 화물(B/L 번호 MRVA2026090001, 품명 건고추 120포)이",
             "SEA STAR호 0925W 항차로 중국 QINGDAO에서 선적되어",
             "2026년 10월 2일 부산 신항에 입항할 예정임을 알려드립니다.", "",
             "(주)가나다포워딩 드림"]
    y = 120
    for line in lines:
        d.text((80, y), line, font=font(KO, 34), fill="black")
        y += 70
    return img


if __name__ == "__main__":
    messy, layouts = HERE / "messy", HERE / "layouts"
    messy.mkdir(exist_ok=True)
    layouts.mkdir(exist_ok=True)
    base = notice()
    jobs = {
        "stamp": stamp(base), "shadow": shadow(base), "perspective": perspective(base),
        "crumple": crumple(base), "fax": fax(base), "tiny": notice(body=15),
        "rot90": base.rotate(90, expand=True), "watermark": watermark(base),
        "handwriting": notice(value_style="hand"),
        "mixed_cjk": notice(extra=[("发货人", "青岛红辣椒贸易有限公司"), ("品名(中)", "干辣椒")]),
    }
    for name, img in jobs.items():
        img.save(messy / f"{name}.png")
    layout_two_col().save(layouts / "two_col.png")
    layout_english().save(layouts / "english_form.png")
    layout_sentence().save(layouts / "sentence.png")
    print(sorted(p.name for p in messy.iterdir()), sorted(p.name for p in layouts.iterdir()))
