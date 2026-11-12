"""cli_model 시험: `claude -p`를 부르지 않고 가짜 프로세스로 명령·스트림 읽기·실패 모양을 확인한다."""

import json
import threading

import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.tools import tool
from pydantic import BaseModel, ValidationError

from marvia import cli_model
from marvia.cli_model import ClaudeCLIChat
from marvia.cli_tools_stub import list_result
from marvia.config import Settings
from marvia.graph.agent import MODEL_ERRORS
from marvia.llm import CLIFailed, LLMFailed, chat_model, structured
from marvia.tools.rules import load_rules

INIT = {"type": "system", "subtype": "init", "mcp_servers": [{"name": "marvia", "status": "connected"}]}
USAGE = {"input_tokens": 2, "cache_creation_input_tokens": 10, "cache_read_input_tokens": 5}


def event(kind: str, **fields) -> dict:
    return {"type": "stream_event", "event": {"type": kind, **fields}}


def tool_use(name: str, args: dict) -> dict:
    block = {"type": "tool_use", "name": f"mcp__marvia__{name}", "input": args}
    return {"type": "assistant", "message": {"model": "claude-haiku-5-5", "content": [block]}}


class Answer(BaseModel):
    label: str


@tool
def find(items: list[str]) -> str:
    """찾는다."""
    return "ok"


class FakeStdin:
    def __init__(self):
        self.text = ""

    def write(self, text):
        self.text += text

    def close(self):
        pass


class FakeProcess:
    """정해 둔 줄을 내는 가짜 CLI 프로세스. hang이면 줄을 다 낸 뒤 kill될 때까지 기다린다."""

    def __init__(self, events, hang=False):
        self.stdin, self.killed, self.hang = FakeStdin(), threading.Event(), hang
        self.lines = [json.dumps(e, ensure_ascii=False) + "\n" for e in events]
        self.stdout = self.read()

    def read(self):
        yield from self.lines
        if self.hang:
            self.killed.wait(5)

    def kill(self):
        self.killed.set()

    def wait(self):
        return 0


@pytest.fixture
def popen(monkeypatch):
    """subprocess.Popen을 가짜로 바꾸고, 불린 명령과 프로세스를 돌려준다."""
    seen = {}

    def start(events, hang=False):
        def fake(command, **kwargs):
            seen.update(command=command, env=kwargs["env"], process=FakeProcess(events, hang))
            return seen["process"]

        monkeypatch.setattr(cli_model.subprocess, "Popen", fake)
        return seen

    return start


def cli(timeout: float = 5, **fields) -> ClaudeCLIChat:
    return ClaudeCLIChat(model="claude-haiku-5-5", timeout=timeout, **fields)


def test_tool_calls_are_read_from_the_stream_until_the_first_message_ends(popen, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    events = [
        INIT,
        event("message_start", message={"usage": USAGE}),
        tool_use("find", {"items": ["a"]}),
        tool_use("find", {"items": "틀린 모양"}),
        event("message_delta", delta={"stop_reason": "tool_use"}, usage={"output_tokens": 7}),
        event("message_stop"),
        tool_use("find", {"items": ["멈춘 뒤의 줄"]}),
    ]
    seen = popen(events)
    out = cli(log_dir=str(tmp_path)).bind_tools([find]).invoke([("system", "시스템"), ("human", "찾아줘")])
    # 접두어를 떼고, 틀린 호출도 앱으로 넘긴다(앱의 도구 검사가 오류로 답한다). 멈춘 뒤 줄은 읽지 않는다
    assert [(c["name"], c["args"]) for c in out.tool_calls] == [
        ("find", {"items": ["a"]}),
        ("find", {"items": "틀린 모양"}),
    ]
    assert out.usage_metadata["input_tokens"] == 17 and out.usage_metadata["output_tokens"] == 7
    assert out.response_metadata["model_name"] == "claude-haiku-5-5"
    assert seen["process"].killed.is_set()
    command = seen["command"]
    # CLI 자체 도구와 사용자·프로젝트 설정을 끄고, 우리 시스템 프롬프트로 바꾼다
    assert command[command.index("--tools") + 1] == ""
    assert command[command.index("--setting-sources") + 1] == ""
    assert command[command.index("--system-prompt") + 1].startswith("시스템")
    assert "--strict-mcp-config" in command and "--no-session-persistence" in command
    servers = json.loads(command[command.index("--mcp-config") + 1])["mcpServers"]
    assert servers["marvia"]["args"][0].endswith("cli_tools_stub.py")
    assert "ANTHROPIC_API_KEY" not in seen["env"]  # 있으면 CLI가 구독 대신 그 키로 과금한다
    assert json.loads(seen["process"].stdin.text)[0] == {"role": "human", "content": "찾아줘"}
    line = json.loads((tmp_path / "calls.jsonl").read_text(encoding="utf-8"))
    assert line["bad_calls"] == 1 and line["tool_calls"] == ["find", "find"]


@pytest.mark.parametrize(
    ("events", "hang", "name"),
    [
        ([INIT | {"mcp_servers": [{"name": "marvia", "status": "failed"}]}], False, "mcp_not_connected"),
        # 사용량 한도처럼 모델 메시지 없이 결과가 먼저 온다
        (
            [INIT, {"type": "result", "subtype": "success", "is_error": True, "api_error_status": 429}],
            False,
            "CLI(success,429)",
        ),
        ([INIT], False, "no_message"),
        ([INIT], True, "timeout"),
    ],
)
def test_a_cli_failure_is_raised_and_never_becomes_an_empty_answer(popen, events, hang, name):
    popen(events, hang)
    with pytest.raises(CLIFailed, match=name.replace("(", r"\(").replace(")", r"\)")):
        cli(timeout=0.05 if hang else 5).bind_tools([find]).invoke("찾아줘")


def fake_run(monkeypatch, out: dict | None) -> dict:
    seen = {}

    class Done:
        stdout = json.dumps(out) if out is not None else "한도에 닿았어요"

    def run(command, **kwargs):
        seen.update(command=command, prompt=kwargs["input"])
        return Done()

    monkeypatch.setattr(cli_model.subprocess, "run", run)
    return seen


def test_structured_output_goes_through_json_schema(monkeypatch):
    ok = {"subtype": "success", "is_error": False, "usage": USAGE | {"output_tokens": 3}}
    seen = fake_run(
        monkeypatch, ok | {"structured_output": {"label": "x"}, "modelUsage": {"claude-haiku-5-5": {}}}
    )
    assert cli().with_structured_output(Answer, method="json_schema").invoke("질문") == Answer(label="x")
    assert seen["prompt"] == "질문"  # 사람 메시지 하나는 글 그대로 간다
    schema = json.loads(seen["command"][seen["command"].index("--json-schema") + 1])
    assert schema["properties"]["label"]["type"] == "string"
    # 모양이 다른 답은 API 길과 같은 오류(OutputParserException)다
    fake_run(monkeypatch, ok | {"structured_output": {"label": 3}})
    with pytest.raises(OutputParserException):
        cli().with_structured_output(Answer).invoke("질문")
    # CLI가 다시 시키고도 끝내 모양을 못 맞춘 것도 모양 오류다 (CLI 실패가 아니다)
    fake_run(monkeypatch, {"subtype": "error_max_structured_output_retries", "is_error": True})
    with pytest.raises(OutputParserException):
        cli().with_structured_output(Answer).invoke("질문")


@pytest.mark.parametrize(("requests", "first_try"), [(2, True), (3, False), (None, None)])
def test_a_structured_answer_says_whether_the_cli_had_to_ask_again(monkeypatch, requests, first_try):
    # [왜] CLI는 StructuredOutput 도구 호출 1번 + 확인 1번이 첫 시도다.
    #      그보다 많으면 모양이 틀려 다시 시킨 것이다
    out = {
        "subtype": "success",
        "is_error": False,
        "structured_output": {"label": "x"},
        "num_turns": requests,
    }
    fake_run(monkeypatch, out)
    message = cli().bind(json_schema=Answer.model_json_schema()).invoke("질문")
    assert message.response_metadata["structured_first_try"] is first_try
    # [왜] "첫 시도 = 요청 2"라는 전제를 실행마다 확인할 수 있게 요청 수를 그대로 남긴다.
    #      요청 수가 없는 결과는 통과로 치지 않는다(None = 알 수 없음)
    assert message.response_metadata["api_requests"] == requests


@pytest.mark.parametrize(
    "out",
    [
        None,  # JSON이 아닌 출력
        {"subtype": "error_during_execution", "is_error": True},
        {"subtype": "success", "is_error": False},  # 구조화 출력 칸이 없다
    ],
)
def test_a_failed_structured_call_is_a_cli_failure(monkeypatch, out):
    fake_run(monkeypatch, out)
    with pytest.raises(CLIFailed):
        cli().with_structured_output(Answer).invoke("질문")


def test_the_switch_builds_the_cli_model_without_an_api_key(monkeypatch):
    monkeypatch.delenv("MARVIA_ANTHROPIC_API_KEY", raising=False)
    llm = chat_model(Settings(_env_file=None, llm_via="cli"))
    assert isinstance(llm, ClaudeCLIChat) and llm.model == "claude-haiku-5-5"
    assert llm.timeout == load_rules("agent")["llm"]["cli_timeout_s"]
    assert Settings(_env_file=None).llm_via == "api"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_via="sdk")


def test_cli_failures_are_model_errors_by_name():
    assert CLIFailed in MODEL_ERRORS

    class Broken:
        def with_structured_output(self, schema, method):
            return self

        def invoke(self, prompt):
            raise CLIFailed("CLI(timeout,None)")

    with pytest.raises(LLMFailed, match="CLIFailed"):
        structured(Broken(), Answer)("프롬프트")


def test_the_stub_lists_tools_with_their_schemas():
    spec = {"name": "find", "description": "찾는다.", "parameters": {"type": "object", "properties": {}}}
    listed = list_result([spec]).tools[0]
    assert (listed.name, listed.description, listed.input_schema) == ("find", "찾는다.", spec["parameters"])
