"""1차 코퍼스를 국가법령정보센터에서 한 번 받아 단위 파일로 저장한다 (설계 5.1·5.2, 2절 결정 15).

실행: uv run python scripts/fetch_corpus.py
결과: corpus/units/{doc_id}.jsonl과 corpus/manifest.json(저장소에 올림), corpus/raw/{doc_id}.html(올리지 않음)
[주의] 시행일이 오늘보다 뒤인 판(시행 예정판)은 저장하지 않고 SKIP으로 알린다 (3차 측정 때 생긴 문제).
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import date
from pathlib import Path

import httpx
import yaml

from marvia.rag import fetch
from marvia.rag.lawpage import split_units

CORPUS = Path(__file__).resolve().parents[1] / "corpus"


def kind_of(doc: dict) -> str:
    """문서 종류: 법률·시행령·시행규칙·고시."""
    if doc["type"] == "admrul":
        return "고시"
    for suffix in ("시행규칙", "시행령"):
        if doc["name"].endswith(suffix):
            return suffix
    return "법률"


def main() -> None:
    today = date.today()
    sources = yaml.safe_load((CORPUS / "sources.yaml").read_text(encoding="utf-8"))
    (CORPUS / "raw").mkdir(parents=True, exist_ok=True)
    (CORPUS / "units").mkdir(exist_ok=True)
    manifest = []
    # [왜] follow_redirects: 행정규칙 이름 주소는 다른 주소로 넘겨 준다. timeout: 60초 안에 답이 없으면 멈춘다
    with httpx.Client(follow_redirects=True, timeout=60) as client:

        def get(url: str) -> str:
            time.sleep(0.5)  # [왜] 공공 사이트에 부담을 주지 않게 요청 사이를 띄운다
            response = client.get(url)
            response.raise_for_status()
            return response.text

        for doc in sources:
            if doc["type"] == "law":
                info = fetch.law_info(get(fetch.law_search_url(doc["name"])))
                if info is None:
                    print("MISS", doc["name"])
                    continue
                law_id, seq, effective = info
                doc_id, url = f"L{law_id}", fetch.law_body_url(seq, effective)
                body = get(url)
            else:
                seq = fetch.rule_seq(get(fetch.rule_search_url(doc["name"])))
                if seq is None:
                    print("MISS", doc["name"])
                    continue
                url = fetch.rule_body_url(seq)
                body = get(url)
                info = fetch.rule_info(body)
                if info is None:
                    print("MISS", doc["name"])
                    continue
                rule_id, effective = info
                doc_id = f"A{rule_id}"
            if effective > today:
                print("SKIP 시행 예정판", doc["name"], effective)
                manifest.append(
                    {"name": doc["name"], "effective": effective.isoformat(), "status": "시행 예정판"}
                )
                continue
            (CORPUS / "raw" / f"{doc_id}.html").write_text(body, encoding="utf-8")
            units = split_units(
                body,
                doc_id=doc_id,
                law_name=doc["name"],
                kind=kind_of(doc),
                effective=effective,
                source_url=url,
            )
            ids = [u.unit_id for u in units]
            if len(ids) != len(set(ids)):
                raise SystemExit(f"{doc['name']}: 같은 unit_id가 두 번 나왔다. 자르는 규칙을 확인한다")
            lines = "".join(u.model_dump_json() + "\n" for u in units)
            (CORPUS / "units" / f"{doc_id}.jsonl").write_text(lines, encoding="utf-8")
            manifest.append(
                {
                    "name": doc["name"],
                    "title": fetch.title(body),  # name과 같은지 사람이 확인한다
                    "doc_id": doc_id,
                    "kind": kind_of(doc),
                    "effective": effective.isoformat(),
                    "url": url,
                    "units": len(units),
                    "page_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                    "status": "ok",
                }
            )
            print("OK", doc["name"], effective, f"단위 {len(units)}개")
    text = json.dumps(manifest, ensure_ascii=False, indent=1) + "\n"
    (CORPUS / "manifest.json").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
