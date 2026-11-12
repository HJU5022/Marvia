"""구독의 `claude -p`를 LangChain 채팅 모델로 감싼다 (설계 13절, MARVIA_LLM_VIA=cli).

API 키 없이 평가를 돌리는 길이다. 호출 한 번이 CLI 프로세스 하나다. CLI 자체 도구는 끄고(--tools ""),
시스템 프롬프트는 우리 것으로 바꾸고, 사용자·프로젝트 설정은 읽지 않는다(--setting-sources "").
- 도구 호출: 도구의 이름·설명·스키마만 알려 주는 MCP 서버(cli_tools_stub.py)를 붙여 모델이 도구 호출을
  내게 하고, 첫 모델 메시지가 끝나면(message_stop) 프로세스를 멈춘다. 도구는 에이전트 루프가 돌린다.
- 구조화 출력: --json-schema. CLI가 StructuredOutput 도구로 받아 API 요청이 두 번 나간다.
하지 않는 일: 재시도(CLI가 안에서 한다), 온도·최대 토큰 지정(CLI에 옵션이 없다), 지연 시간 측정.
[주의] API 길과 다른 조건이다: 대화 기록이 JSON 글 하나로 사용자 메시지에 들어가고, 모델에게 도구 이름이
       mcp__marvia__ 접두어로 보이고, CLI가 환경 정보 약 620토큰을 덧붙이고, 생각(thinking)이 켜져 있다
       (11-12 실측). 이 길로 잰 값은 API로 잰 값과 섞어 견주지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import jsonschema
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, Field, ValidationError

from marvia.llm import CLIFailed
from marvia.prompts import render
from marvia.tools.rules import load_rules

SERVER = "marvia"  # MCP 서버 이름. CLI가 도구 이름 앞에 mcp__<이름>__을 붙인다
PREFIX = f"mcp__{SERVER}__"
STUB = str(Path(__file__).with_name("cli_tools_stub.py"))
# 구조화 출력 한 번에 CLI가 내는 API 요청 수: StructuredOutput 도구 호출 1 + 확인 1 (11-12 실측).
# 이보다 많으면 답의 모양이 틀려 CLI가 다시 시킨 것이다
FIRST_TRY_REQUESTS = 2
# CLI가 다시 시키고도 끝내 모양을 못 맞췄을 때의 결과 종류 (CLI 문서: structured outputs)
SHAPE_FAILED = "error_max_structured_output_retries"
_LOG_LOCK = threading.Lock()


def transcript(messages: Sequence[BaseMessage]) -> str:
    """시스템 메시지를 뺀 대화를 JSON 글로 만든다."""
    # [왜] CLI는 사용자 글 하나만 받는다. JSON으로 감싸면 도구 결과 글이 메시지 경계를 흉내 낼 수 없다
    rows: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, AIMessage):
            calls = [{"id": c["id"], "name": c["name"], "args": c["args"]} for c in message.tool_calls]
            rows.append({"role": "assistant", "text": str(message.text), "tool_calls": calls})
        elif message.type == "tool":
            rows.append(
                {
                    "role": "tool",
                    "tool_call_id": getattr(message, "tool_call_id", ""),
                    "name": message.name,
                    "status": getattr(message, "status", "success"),
                    "content": str(message.text),
                }
            )
        else:
            rows.append({"role": "human", "content": str(message.text)})
    return json.dumps(rows, ensure_ascii=False)


def invalid_calls(calls: list[tuple[str, dict]], tools: list[dict]) -> int:
    """모르는 도구이거나 그 도구의 인자 스키마를 통과하지 못한 호출 수."""
    by_name = {t["name"]: t.get("parameters") or {} for t in tools}
    bad = 0
    for name, args in calls:
        try:
            if name not in by_name:
                raise jsonschema.ValidationError("모르는 도구")
            jsonschema.validate(args, by_name[name])
        except jsonschema.ValidationError:
            bad += 1
    return bad


def cli_version() -> str:
    """설치된 CLI의 판 번호 글(`claude --version`). 평가 결과의 meta에 남긴다."""
    done = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=30)  # noqa: S603, S607
    return done.stdout.strip()


class ClaudeCLIChat(BaseChatModel):
    """`claude -p`를 부르는 채팅 모델. bind_tools와 with_structured_output(pydantic)을 지원한다."""

    model: str
    timeout: float  # 호출 한 번의 시간 제한(초). 넘으면 프로세스를 죽인다
    # [왜] 빈 폴더에서 돌려야 프로젝트 CLAUDE.md·설정이 섞이지 않는다
    cwd: str = Field(default_factory=lambda: tempfile.mkdtemp(prefix="marvia-cli-"))
    specs_dir: str = Field(default_factory=lambda: tempfile.mkdtemp(prefix="marvia-cli-specs-"))
    log_dir: str = ""  # 비어 있지 않으면 호출마다 CLI 원본 출력과 요약 한 줄(calls.jsonl)을 남긴다

    @property
    def _llm_type(self) -> str:
        return "claude-cli"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Runnable:
        # [왜] tool_choice 같은 공급자 옵션은 CLI에 넘길 곳이 없어 버린다
        return self.bind(tools=[convert_to_openai_tool(tool)["function"] for tool in tools])

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Runnable:
        if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
            raise NotImplementedError("pydantic 클래스만 받는다")

        def parse(message: AIMessage) -> BaseModel:
            try:
                return schema.model_validate(message.additional_kwargs["structured"])
            except ValidationError as error:
                # [왜] 모양이 다른 답은 API 길과 같은 오류로 올린다
                # [주의] 오류 글에 모델이 낸 값을 싣지 않는다
                raise OutputParserException(f"ValidationError({error.error_count()})") from error

        return self.bind(json_schema=schema.model_json_schema()) | RunnableLambda(parse)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        *,
        tools: list[dict] | None = None,
        json_schema: dict | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        system = "\n\n".join(str(m.text) for m in messages if m.type == "system")
        rest = [m for m in messages if m.type != "system"]
        # [왜] 사람 메시지 하나뿐이면 그 글을 그대로 넘긴다(API 길과 같은 입력). 그 밖에는 기록을 JSON으로
        single = len(rest) == 1 and rest[0].type == "human" and not tools
        prompt = str(rest[0].text) if single else transcript(rest)
        if not single:
            system = f"{system}\n\n{render('cli_transcript')}"
        out = self._run_tools(system, prompt, tools) if tools else self._run(system, prompt, json_schema)

        usage = out.get("usage") or {}
        cached = {
            "cache_creation": usage.get("cache_creation_input_tokens") or 0,
            "cache_read": usage.get("cache_read_input_tokens") or 0,
        }
        tokens_in = (usage.get("input_tokens") or 0) + sum(cached.values())
        tokens_out = usage.get("output_tokens") or 0
        structured = out.get("structured_output")
        failed = out.get("is_error") or out.get("subtype") != "success"
        failed = failed or (json_schema is not None and structured is None)
        found: list[tuple[str, dict]] = out.get("calls", [])
        models = out.get("models") or []
        metadata: dict[str, Any] = {
            "model_name": models[0] if models else self.model,
            "model_provider": "claude-cli",
        }
        if json_schema is not None:
            # [왜] 출력 계약 준수율(첫 시도에 스키마 통과)을 세려고 남긴다. 구조화 호출에만 있다.
            #      요청 수가 없는 결과는 통과로 치지 않는다: None은 "알 수 없음"이다 (R-094)
            turns = out.get("num_turns")
            metadata["api_requests"] = turns
            metadata["structured_first_try"] = None if turns is None else turns <= FIRST_TRY_REQUESTS
        self._log(
            {
                "kind": "tools" if tools else "schema" if json_schema else "text",
                "subtype": out.get("subtype"),
                "is_error": bool(out.get("is_error")),
                "api_error_status": out.get("api_error_status"),
                "api_requests": out.get("num_turns"),
                "stop_reason": out.get("stop_reason"),
                "models": models,
                "in": tokens_in,
                "out": tokens_out,
                **cached,
                "tool_calls": [name for name, _ in found],
                # [왜] 통과 못 한 호출도 그대로 넘겨 앱의 도구 검사가 오류 결과를 돌려주게 하고, 수만 센다
                "bad_calls": invalid_calls(found, tools or []),
            },
            out.get("raw", ""),
        )
        if json_schema is not None and out.get("subtype") == SHAPE_FAILED:
            # [왜] 모양을 못 맞춘 것은 CLI 실패가 아니라 답 모양 오류다. API 길과 같은 오류로 올린다
            raise OutputParserException(SHAPE_FAILED)
        if failed:
            # [주의] 종류 이름과 상태 코드만 남긴다. 오류 글에는 요청 내용이 섞일 수 있다
            raise CLIFailed(f"CLI({out.get('subtype')},{out.get('api_error_status')})")
        message = AIMessage(
            content=str(out.get("result") or ""),
            tool_calls=[
                {"name": name, "args": args, "id": f"cli_{uuid.uuid4().hex[:12]}", "type": "tool_call"}
                for name, args in found
            ],
            additional_kwargs={"structured": structured} if json_schema else {},
            usage_metadata={
                "input_tokens": tokens_in,
                "output_tokens": tokens_out,
                "total_tokens": tokens_in + tokens_out,
                "input_token_details": cached,  # type: ignore[typeddict-item]
            },
            response_metadata=metadata,
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _command(self, system: str) -> list[str]:
        """두 호출 길이 함께 쓰는 명령 앞부분."""
        return [
            "claude", "-p",
            "--model", self.model,
            "--system-prompt", system,
            "--tools", "",  # CLI 자체 도구(Bash·Read 등)를 모두 끈다
            "--setting-sources", "",  # 사용자·프로젝트·로컬 설정(훅, 플러그인, CLAUDE.md)을 읽지 않는다
            "--strict-mcp-config",  # 계정에 연결된 MCP 서버를 붙이지 않는다
            "--disable-slash-commands",
            "--no-session-persistence",  # 세션 파일을 남기지 않는다
        ]  # fmt: skip

    @staticmethod
    def _env() -> dict[str, str]:
        """CLI 프로세스에 넘길 환경 변수: rules/agent.yaml llm.cli_env에 적은 이름만."""
        # [왜] ANTHROPIC_API_KEY가 넘어가면 CLI가 구독 대신 그 키로 과금한다. Voyage 키, 데이터 키, DB 주소도
        #      CLI와 도구 스텁 프로세스가 가질 까닭이 없다. 필요한 이름만 넘긴다
        names = load_rules("agent")["llm"]["cli_env"]
        return {name: os.environ[name] for name in names if name in os.environ}

    def _run(self, system: str, prompt: str, schema: dict | None) -> dict:
        """도구 없는 호출: 결과 JSON 하나를 받는다. 시간 초과나 깨진 출력은 실패 모양의 dict로 돌려준다."""
        command = [*self._command(system), "--output-format", "json"]
        if schema:
            command += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
        try:
            done = subprocess.run(  # noqa: S603
                command,
                input=prompt,
                capture_output=True,
                text=True,
                cwd=self.cwd,
                timeout=self.timeout,
                env=self._env(),
            )
            out = json.loads(done.stdout)
        except subprocess.TimeoutExpired:
            return {"subtype": "timeout", "is_error": True}
        except json.JSONDecodeError:
            return {"subtype": "bad_output", "is_error": True}
        if not isinstance(out, dict):
            return {"subtype": "bad_output", "is_error": True}
        # [주의] 계정 정보가 든 칸은 원본 기록에 남기지 않는다
        raw = json.dumps({k: v for k, v in out.items() if k != "credential_expires_at"}, ensure_ascii=False)
        return out | {"models": list(out.get("modelUsage", {})), "raw": raw}

    def _run_tools(self, system: str, prompt: str, tools: list[dict]) -> dict:
        """도구 있는 호출: 스트림에서 첫 모델 메시지(글, 도구 호출)를 읽고 message_stop에서 멈춘다."""
        specs = json.dumps(tools, ensure_ascii=False)
        path = Path(self.specs_dir, hashlib.sha256(specs.encode()).hexdigest()[:16] + ".json")
        if not path.exists():
            path.write_text(specs, encoding="utf-8")
        servers = {"mcpServers": {SERVER: {"command": sys.executable, "args": [STUB, str(path)]}}}
        command = [
            *self._command(system),
            "--mcp-config", json.dumps(servers),
            "--permission-prompts", "none",  # 멈추기 전에 도구 실행까지 가도 아무도 승인하지 않는다
            "--output-format", "stream-json", "--verbose", "--include-partial-messages",
        ]  # fmt: skip
        process = subprocess.Popen(  # noqa: S603
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            cwd=self.cwd,
            env=self._env(),
        )
        timed_out = threading.Event()

        def expire() -> None:
            timed_out.set()
            process.kill()  # [왜] 죽이면 아래 읽기 루프가 끝난다

        timer = threading.Timer(self.timeout, expire)
        timer.start()
        out: dict[str, Any] = {"subtype": "no_message", "is_error": True, "calls": [], "num_turns": 1}
        text, lines, usage, models = "", [], {}, []
        try:
            assert process.stdin and process.stdout
            process.stdin.write(prompt)
            process.stdin.close()
            for line in process.stdout:
                lines.append(line)
                event = json.loads(line)
                kind = event.get("type")
                if kind == "system" and event.get("subtype") == "init":
                    status = {s["name"]: s["status"] for s in event.get("mcp_servers", [])}
                    if status.get(SERVER) != "connected":
                        # [왜] 도구 서버가 안 붙으면 모델이 도구 없이 답한다. 넘어가지 않고 실패로 남긴다
                        out["subtype"] = "mcp_not_connected"
                        break
                elif kind == "assistant":
                    models = [event["message"].get("model")]
                    for block in event["message"]["content"]:
                        if block["type"] == "tool_use":
                            out["calls"].append((block["name"].removeprefix(PREFIX), block["input"]))
                        elif block["type"] == "text":
                            text += block["text"]
                elif kind == "stream_event":
                    inner = event["event"]
                    if inner["type"] == "message_start":
                        usage = dict(inner["message"].get("usage") or {})
                    elif inner["type"] == "message_delta":
                        usage |= {k: v for k, v in (inner.get("usage") or {}).items() if v is not None}
                        out["stop_reason"] = inner["delta"].get("stop_reason")
                    elif inner["type"] == "message_stop":
                        out |= {"subtype": "success", "is_error": False}
                        break
                elif kind == "result":
                    # [왜] 모델 메시지가 끝나기 전에 결과가 왔다(사용량 한도, API 오류). 실패로 남긴다
                    out |= {
                        "subtype": event.get("subtype"),
                        "api_error_status": event.get("api_error_status"),
                    }
                    break
            if timed_out.is_set() and out["subtype"] == "no_message":
                out["subtype"] = "timeout"
            if out["subtype"] == "success" and out.get("stop_reason") == "tool_use" and not out["calls"]:
                # [왜] 모델은 도구를 부르며 끝냈는데 읽은 호출이 없다. CLI의 이벤트 순서가 바뀌었을 수 있다.
                #      그대로 두면 도구 없이 답한 것처럼 보인다. 실패로 남긴다
                out |= {"subtype": "tool_use_without_calls", "is_error": True}
        except json.JSONDecodeError:
            out["subtype"] = "bad_output"
        finally:
            timer.cancel()
            process.kill()
            process.wait()
        return out | {"result": text, "usage": usage, "models": models, "raw": "".join(lines)}

    def _log(self, row: dict, raw: str) -> None:
        if not self.log_dir:
            return
        with _LOG_LOCK:
            os.makedirs(self.log_dir, exist_ok=True)
            with open(os.path.join(self.log_dir, "calls.jsonl"), "a", encoding="utf-8") as file:
                n = file.tell()
                file.write(json.dumps(row, ensure_ascii=False) + "\n")
            Path(self.log_dir, f"raw-{n:08d}.jsonl").write_text(raw, encoding="utf-8")
