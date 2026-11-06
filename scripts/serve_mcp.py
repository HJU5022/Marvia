"""규정 검색 MCP 서버를 streamable HTTP로 띄운다 (설계 9절, done 2.4). 키(Voyage)와 DB가 필요하다.

실행: MARVIA_MCP_TOKEN=<토큰> uv run python scripts/serve_mcp.py --port 8766
      바깥 클라이언트는 http://127.0.0.1:8766/mcp 에 "Authorization: Bearer <토큰>"으로 붙는다.
[주의] 토큰이 비면 뜨지 않는다. 8000번은 다른 서비스가 쓴다. 띄운 서버는 다 쓰면 끈다(Ctrl-C).
"""

import argparse
from functools import partial

import uvicorn

from marvia.config import Settings
from marvia.db import read_pool
from marvia.graph.rag import top_ranked
from marvia.rag.live import live_deps
from marvia.rag.mcp import build_server, http_app

parser = argparse.ArgumentParser()
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=8766)
args = parser.parse_args()

settings = Settings()
# [왜] 오래 도는 서버는 요청마다 풀에서 연결을 빌린다. 연결 하나를 겹치는 요청이 함께 쓰지 않는다 (R-066)
with read_pool(settings.database_url) as pool:
    rag = live_deps(settings, pool)
    server = build_server(partial(top_ranked, rag.search, rag.rerank))
    uvicorn.run(
        http_app(server, settings.mcp_token.get_secret_value(), args.host), host=args.host, port=args.port
    )
