"""별표 원본(HWP 5.0·HWPX)을 받아 단위 파일로 만든다 (설계 5.2, 계획 3b Task 1).

실행: uv run --with olefile==0.47 python scripts/build_annex.py
결과: corpus/units/{doc_id}.annex.jsonl과 corpus/annex_manifest.json(저장소에 올림),
corpus/raw/annex/*(올리지 않음)
[왜] olefile은 HWP 5.0의 OLE 상자를 여는 데만 쓴다. 이 스크립트 밖에서는 쓰지 않아 프로젝트 의존성에 넣지
않는다.
     레코드에서 글을 뽑고 자르는 일은 marvia.rag.annex(표준 라이브러리만)가 한다.
"""

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import httpx
import yaml

from marvia.rag.annex import amended_on, hwp_paragraphs, hwpx_paragraphs, split_annex

CORPUS = Path(__file__).resolve().parents[1] / "corpus"
MAGIC = {"hwp": b"\xd0\xcf\x11\xe0", "hwpx": b"PK"}  # HWP 5.0은 OLE, HWPX는 zip


def hwp_lines(path: Path) -> list[str]:
    """HWP 5.0 파일의 문단 글. olefile로 FileHeader와 BodyText/SectionN 스트림을 꺼낸다."""
    import olefile  # [왜] uv run --with olefile로만 있다

    with olefile.OleFileIO(str(path)) as ole:
        sections = []
        while ole.exists(f"BodyText/Section{len(sections)}"):
            sections.append(ole.openstream(f"BodyText/Section{len(sections)}").read())
        return hwp_paragraphs(ole.openstream("FileHeader").read(), sections)


laws = {m["doc_id"]: m for m in json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))}
units: dict[str, list] = {}
records = []
for src in yaml.safe_load((CORPUS / "annexes.yaml").read_text(encoding="utf-8")):
    path = CORPUS / "raw" / "annex" / f"{src['doc_id']}-{src['number']}.{src['format']}"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://www.law.go.kr/LSW/flDownload.do?flSeq={src['flseq']}"
        response = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        response.raise_for_status()
        path.write_bytes(response.content)
    data = path.read_bytes()
    if not data.startswith(MAGIC[src["format"]]):
        sys.exit(f"[멈춤] {path.name}: {src['format']} 파일이 아니다 (앞 바이트 {data[:4].hex()})")
    lines = hwp_lines(path) if src["format"] == "hwp" else hwpx_paragraphs(data)
    law = laws[src["doc_id"]]
    made = split_annex(
        lines,
        doc_id=src["doc_id"],
        law_name=law["name"],
        number=src["number"],
        # [왜] 단위 시행일은 법령 판의 시행일이다. 별표 자체의 개정일은 기록에만 남긴다 (사전 부검 F2)
        effective=date.fromisoformat(law["effective"]),
        source_url=src["view_url"],
    )
    units.setdefault(src["doc_id"], []).extend(made)
    amended = amended_on(lines)
    records.append(
        src
        | {
            "lines": len(lines),
            "units": len(made),
            "file_sha256": hashlib.sha256(data).hexdigest(),
            "amended": amended.isoformat() if amended else None,
        }
    )
    print(f"{src['doc_id']} 별표 {src['number']}: 글 {len(lines)}줄, 단위 {len(made)}개")
for doc_id, made in units.items():
    text = "".join(u.model_dump_json() + "\n" for u in made)
    (CORPUS / "units" / f"{doc_id}.annex.jsonl").write_text(text, encoding="utf-8")
(CORPUS / "annex_manifest.json").write_text(
    json.dumps(records, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
)
