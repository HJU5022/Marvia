"""Build the OCR test images for the candidate comparison.

Responsibility: turn one real B/L scan and one fabricated Korean arrival
notice into a small set of images that look like what users will upload.
Why: we only have one real document, and it is a clean scan. Users will
mostly upload phone photos, so we derive tilted / blurred / low-res /
heavily-compressed variants from each document with code.
Reference: wiki 프로젝트/Marvia-모델-선정.md "비전" row (2-stage, decided 09-29).

The real B/L stays local (samples/ is not in any repo) and is never sent
to an external service (user decision 09-29: local OCR only).
"""
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

HERE = Path(__file__).parent
SAMPLES = HERE / "samples"
BL_PDF = HERE.parent / "Info" / "BILL OF LADING.pdf"
KO_FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"


def pdf_to_png(pdf: Path, out_stem: Path, dpi: int = 200) -> Path:
    # pdftoppm (poppler) renders the single page; -singlefile drops the "-1" suffix.
    subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-singlefile", str(pdf), str(out_stem)], check=True)
    return out_stem.with_suffix(".png")


def make_korean_notice(path: Path) -> None:
    # Fabricated arrival notice. All names/numbers are fake on purpose.
    img = Image.new("RGB", (1240, 1754), "white")  # A4 at 150 dpi
    d = ImageDraw.Draw(img)
    title = ImageFont.truetype(KO_FONT, 56)
    body = ImageFont.truetype(KO_FONT, 34)
    d.text((380, 90), "화물 도착 통지서", font=title, fill="black")
    d.text((80, 190), "(주)가나다포워딩  부산광역시 중구 중앙대로 000", font=body, fill="black")
    rows = [
        ("수하인", "가나다무역"),
        ("B/L NO.", "MRVA2026090001"),
        ("선명 / 항차", "SEA STAR / 0925W"),
        ("선적항", "QINGDAO, CHINA"),
        ("양하항", "부산 신항"),
        ("입항 예정일 (ETA)", "2026-10-02"),
        ("품명", "건고추"),
        ("수량 / 중량", "120 BAGS / 2,400 KGS"),
    ]
    y = 300
    for label, value in rows:
        d.rectangle([80, y, 1160, y + 90], outline="black", width=2)
        d.line([440, y, 440, y + 90], fill="black", width=2)
        d.text((100, y + 25), label, font=body, fill="black")
        d.text((460, y + 25), value, font=body, fill="black")
        y += 90
    d.text((80, y + 60), "※ 화물 반출 전 운임 및 부대비용을 정산하여 주시기 바랍니다.", font=body, fill="black")
    img.save(path)


def variants(src: Path) -> None:
    # Each variant imitates one common phone-photo problem, plus one combined.
    img = Image.open(src).convert("RGB")
    stem = src.stem
    img.rotate(3, expand=True, fillcolor=(235, 235, 230)).save(SAMPLES / f"{stem}__tilt3.png")
    img.filter(ImageFilter.GaussianBlur(1.5)).save(SAMPLES / f"{stem}__blur.png")
    half = img.resize((img.width // 2, img.height // 2))
    half.save(SAMPLES / f"{stem}__half.png")
    img.save(SAMPLES / f"{stem}__jpeg25.jpg", quality=25)
    phone = img.rotate(2, expand=True, fillcolor=(210, 205, 195)).filter(ImageFilter.GaussianBlur(1.0))
    phone = ImageEnhance.Brightness(phone).enhance(0.85)
    phone = phone.resize((int(phone.width * 0.7), int(phone.height * 0.7)))
    phone.save(SAMPLES / f"{stem}__phone.jpg", quality=50)


if __name__ == "__main__":
    SAMPLES.mkdir(exist_ok=True)
    bl = pdf_to_png(BL_PDF, SAMPLES / "bl")
    ko = SAMPLES / "ko_notice.png"
    make_korean_notice(ko)
    for src in (bl, ko):
        variants(src)
    for p in sorted(SAMPLES.iterdir()):
        w, h = Image.open(p).size
        print(f"{p.name:28s} {w}x{h}")
