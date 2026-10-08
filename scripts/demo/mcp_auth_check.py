"""MCP 접근 제어 확인 (작업 B10 제출 캡처용).

토큰 없이·틀린 토큰·맞는 토큰 세 경우를 차례로 불러 /mcp에 인증이 걸려 있음을 보인다.

    python -m scripts.demo.mcp_auth_check                       # localhost:8000 (API 서버 안의 /mcp)
    python -m scripts.demo.mcp_auth_check --url http://...      # 배포 주소

서버에 MCP_TOKEN이 없으면 인증이 걸리지 않아 앞의 두 경우도 통과한다. 그때는 그렇게 알린다.
"""
import argparse
import asyncio
import os

import httpx
from dotenv import load_dotenv

from scripts.demo.mcp_check import list_tools

load_dotenv()

LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
ACCEPT = "application/json, text/event-stream"


def _blocked(url: str, label: str, token: str | None) -> None:
    """막혀야 하는 경우. 401이면 정상이다."""
    headers = {"Accept": ACCEPT, "Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    response = httpx.post(url, json=LIST_TOOLS, headers=headers, timeout=10)
    verdict = "차단됨" if response.status_code == 401 else "통과(인증 안 걸림)"
    print(f"{label:10} HTTP {response.status_code}  {verdict}  {response.text[:50].strip()}")


def _allowed(url: str, token: str) -> None:
    """통과해야 하는 경우. MCP 세션을 열고 도구 목록까지 받아 본다."""
    names = asyncio.run(list_tools(url, token))
    print(f"{'맞는 토큰':10} 연결 성공     도구 {len(names)}개: {', '.join(names)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="MCP 접근 제어 확인")
    parser.add_argument("--url", default="http://localhost:8000/mcp")
    parser.add_argument("--token", default=os.environ.get("MCP_TOKEN"))
    args = parser.parse_args()

    print(f"대상: {args.url}\n")
    _blocked(args.url, "토큰 없이", None)
    _blocked(args.url, "틀린 토큰", "wrong-token")
    if args.token:
        _allowed(args.url, args.token)
    else:
        print(f"{'맞는 토큰':10} MCP_TOKEN이 없어 확인할 수 없다. .env에 값을 넣어야 인증이 걸린다")


if __name__ == "__main__":
    main()
