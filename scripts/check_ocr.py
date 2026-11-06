"""RapidOCR가 이 컴퓨터 안에서 B/L 번호를 읽는지 합성 사진 한 장으로 본다 (계획 3d). 돈이 들지 않는다.

[주의] Docker 안에서 돌린다(호스트에 엔진 실행 흔적을 남기지 않는다). 실제 서류 사진은 쓰지 않는다.
실행 (저장소 루트. 호스트 .venv를 건드리지 않게 이름 붙은 볼륨에 환경을 만든다):
  docker run --rm -v "$PWD":/work -w /work -v marvia-uv-cache:/root/.cache/uv \\
    -v marvia-scratch-venv:/venv -e UV_PROJECT_ENVIRONMENT=/venv -e UV_LINK_MODE=copy \\
    ghcr.io/astral-sh/uv@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58 \\
    sh -c "uv sync --frozen -q && uv run python scripts/check_ocr.py"
Pillow는 rapidocr가 함께 설치한다(사진 만들기에만 쓴다).
"""

import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from marvia.identify.ocr import photo_clues, read_image

# fixture 규칙대로 DEMO·MOCK·TEST 접두어의 가공 번호만 쓴다
LINES = ["B/L No. DEMO0001", "SHIPPER: TEST TRADING CO", "MBL: MOCK12345678TEST87654321"]

with tempfile.TemporaryDirectory() as folder:
    path = Path(folder) / "bl.png"
    image = Image.new("RGB", (900, 320), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=44)  # [왜] Pillow에 든 글꼴이라 따로 받지 않는다
    for i, line in enumerate(LINES):
        draw.text((30, 30 + 90 * i), line, fill="black", font=font)
    image.save(path)
    text = read_image(path)

print("읽은 글:", text.replace("\n", " / "))
clues = photo_clues(text)
print("번호 덩어리:", clues)
assert clues == "DEMO0001 MOCK12345678TEST87654321", clues
print("OK")
