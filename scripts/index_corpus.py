"""corpus/units를 로컬 DB에 색인한다 (계획 2 Task 10). OpenRouter 키 필요(--context면 Anthropic 키도).

실행: uv run python scripts/index_corpus.py            맥락 문장 없이 (약 $0.1)
      uv run python scripts/index_corpus.py --context  맥락 문장 포함 (약 $1, 1시간 안팎)
"""

import argparse
from pathlib import Path

from marvia.config import Settings
from marvia.db import connect
from marvia.llm import chat_model, structured
from marvia.rag import openrouter
from marvia.rag.context import Context, make_contextualizer
from marvia.rag.index import index_units, read_units

parser = argparse.ArgumentParser()
parser.add_argument("--context", action="store_true", help="맥락 문장을 만들어 함께 색인한다")
args = parser.parse_args()

settings = Settings()
units = read_units(Path(__file__).resolve().parents[1] / "corpus" / "units")
contextualize = make_contextualizer(structured(chat_model(settings), Context)) if args.context else None


def embed(texts: list[str]) -> list[list[float]]:
    return openrouter.embed(texts, settings)


with connect(settings.database_url) as conn:
    print(f"색인 {index_units(conn, units, embed, contextualize)}개")
