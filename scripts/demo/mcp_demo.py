"""MCP 도구 4종 시연 (작업 B10 제출 캡처용).

서버에 붙어 도구 목록을 보이고, 실제 부산항 데이터로 네 개를 차례로 부른다.
화면 캡처를 염두에 두고 한 단계씩 제목을 붙여 출력한다.

    python -m scripts.demo.mcp_demo --ship-name <선명> --mmsi <MMSI> --call-sign <호출부호>
    python -m scripts.demo.mcp_demo --url http://localhost:8000/mcp --token <MCP_TOKEN> --ship-name ... --mmsi ... --call-sign ...

토큰을 생략하면 환경변수 MCP_TOKEN을 쓴다. 서버에 토큰이 걸려 있는데 안 주면 401이 난다.
시연 선박은 실행할 때 인자로 준다. 실제 선명·MMSI·호출부호를 레포에 두지 않기 위해서다
(ShipFinder 이용 조건, CLAUDE.md "실제 응답 원본은 커밋하지 않는다", 라이선스 점검).
동명 선박이 여러 척인 이름을 주면 되묻기 상황을 보여 줄 수 있다.
"""
import argparse
import asyncio
import json
import os

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

load_dotenv()  # MCP_TOKEN을 .env에서 읽는다


def _print_result(title: str, payload) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")
    print(json.dumps(payload, ensure_ascii=False, indent=2)[:1200])


async def run(url: str, token: str | None, ship_name: str, mmsi: int, call_sign: str) -> None:
    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            info = await session.initialize()
            print(f"연결: {info.serverInfo.name} (protocol {info.protocolVersion})")
            print(f"주소: {url} / 토큰: {'있음' if token else '없음'}")

            tools = (await session.list_tools()).tools
            print(f"\n도구 {len(tools)}개")
            for tool in tools:
                first = (tool.description or "").strip().splitlines()[0] if tool.description else ""
                args = ", ".join(tool.inputSchema.get("properties", {}))
                print(f"  - {tool.name}({args})\n      {first}")

            async def call(name: str, args: dict):
                result = await session.call_tool(name, args)
                payload = json.loads(result.content[0].text) if result.content else {}
                _print_result(f"{name}  {args}", payload)
                return payload

            candidates = await call("get_vessel_candidates", {"ship_name": ship_name})
            first = (candidates.get("candidates") or [{}])[0]
            await call("get_live_position", {"mmsi": first.get("mmsi", mmsi)})
            await call("get_port_schedule", {"call_sign": call_sign})
            await call("estimate_distance", {"lat": 34.5, "lng": 128.8, "sog": 12})

            print("\n시연 끝. 후보가 여러 척이면 어느 배인지는 도구가 정하지 않고 되묻는 근거로 쓴다.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MCP 도구 시연")
    parser.add_argument("--url", default="http://localhost:8000/mcp")
    parser.add_argument("--token", default=os.environ.get("MCP_TOKEN"))
    parser.add_argument("--ship-name", required=True, help="get_vessel_candidates에 넣을 선명")
    parser.add_argument("--mmsi", type=int, required=True, help="후보가 없을 때 get_live_position에 쓸 MMSI")
    parser.add_argument("--call-sign", required=True, help="get_port_schedule에 넣을 호출부호")
    args = parser.parse_args()
    asyncio.run(run(args.url, args.token, args.ship_name, args.mmsi, args.call_sign))
