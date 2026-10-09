"""LLM 호출 결과와 오류의 모양 (services/llm.py에서 옮김). SDK는 import하지 않는다. llm.LLMError 등으로 그대로 쓸 수 있다."""
from __future__ import annotations

from dataclasses import field, dataclass
from pydantic import BaseModel
from backend.app.services.llm_config import RETRYABLE_CODES

@dataclass
class LLMResult:
    """chat() 결과. 로그 4필드(요청 ID·모델·토큰·지연, 작업 A5)를 같이 들고 다닌다."""

    content: str | None                 # 모델이 쓴 본문. tool을 부르면 비어 있을 수 있다
    tool_calls: list[dict] = field(default_factory=list)  # [{"id":..., "name":..., "arguments": "<JSON 문자열>"}]
    model: str = ""                     # 실제로 답한 모델
    provider: str | None = None         # OpenRouter가 보낸 제공사. 무료 모델은 한 곳뿐인 경우가 많다
    request_id: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: int = 0                 # 마지막 시도 하나의 지연. 재시도 대기는 빠진다
    attempts: int = 1                   # 몇 번 만에 답을 받았나. Langfuse retry_count 자리 (SDD 5.11)
    # 입력 중 제공사 캐시에서 읽은 토큰. 프롬프트 + Skill처럼 매번 같은 앞부분이 자동 캐시된다 (확인: Vertex
    # Gemini 2.5 Flash 판정 입력 4,348 중 두 번째 호출부터 3,514). 요청 옵션 없이 응답 usage.prompt_tokens_details에 온다
    cached_tokens: int | None = None
    cost: float | None = None           # OpenRouter가 응답 usage.cost에 준 실제 금액 (크레딧 = USD). 무료 모델은 0. Vertex는 안 줘서 None
    finish_reason: str | None = None    # "length"면 토큰 한도에서 잘린 답. 형식 오류와 구분한다 (truncated)

class LLMError(Exception):
    """OpenRouter·Vertex AI가 답 대신 에러를 준 경우. code가 RETRYABLE_CODES면 chat()이 한 번 더 부른다.

    kind는 실패 종류다. 로그(log_failure)에 코드 대신 이 이름을 남긴다. 해결책이 종류마다 달라서 나눈다
    (평가 c에서 qwen 무료가 21건 실패했는데 429 말고는 왜 실패했는지 알 수 없었다).
      rate_limited  429 요청이 너무 잦음        overloaded  5xx 제공사 과부하
      auth          401·403·Vertex 로그인 문제   bad_request 그 밖의 4xx (요청 모양·지원 안 하는 옵션)
      connection    연결 실패                   no_choices  200인데 답 없이 error만 옴
      timeout       TIMEOUT_SEC 안에 답이 없음 (전체 시간 상한, _create_with_deadline)
      not_configured 모델 이름이 설정에 없음
      truncated·bad_format은 LLMFormatError 쪽 (답은 왔는데 쓸 수 없음)
    """

    def __init__(self, message: str, code: int | None = None, latency_ms: int = 0, kind: str = "unknown"):
        super().__init__(message)
        self.code = code
        self.latency_ms = latency_ms
        self.kind = kind

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE_CODES

class LLMFormatError(LLMError):
    """LLM이 답은 했는데 JSON이 아니거나 필수 칸이 빠지는 등 모양이 스키마와 다른 경우.

    호출 실패(네트워크·키·과부하)와 구분한다. 라우터는 이것을 규칙 위반처럼 보고 무엇이 틀렸는지 붙여 다시 묻는다.
    세 번 다 깨지면 failed다 (SDD 5.7 "3단계 재시도 뒤 failed", 평가셋 F08).
    LLMError를 물려받으므로 이것을 따로 잡지 않는 곳(pick_vessel·후속 질문)은 지금처럼 LLM 실패로 처리한다.
    """

    def __init__(self, message: str, detail: str, kind: str = "bad_format"):
        super().__init__(message, kind=kind)
        self.detail = detail  # LLM에 다시 물을 때 붙일 설명 (영어, 프롬프트와 같은 언어)

class _DeadlineExceeded(Exception):
    """_create_with_deadline이 TIMEOUT_SEC 안에 답을 못 받았을 때. _call_once가 LLMError(kind=timeout)로 바꾼다."""

@dataclass
class LLMAnswer:
    """judge()·pick_vessel()·answer_follow_up()의 결과. 검사를 통과한 출력과 함께
    트레이스에 남길 값(모델·토큰·지연·프롬프트 버전)을 들고 다닌다 (SDD 5.11)."""

    output: BaseModel  # 함수마다 JudgeOutput·PickOutput·FollowUpOutput
    llm: LLMResult
    prompt_version: str
    # LLM이 부른 도구와 결과 [{"name", "arguments", "result"}]. 후속 질문만 쓴다. 라우터가 근거 카드로 붙인다
    tool_calls: list[dict] = field(default_factory=list)
