"""소형 모델(GGUF)로 슬롯을 뽑는다. (SDD 5절 1단계, 8절 "소형 (GGUF) 또는 대형 폴백")

파인튜닝한 모델은 학습 때와 같은 프롬프트로 불러야 한다. 형식이 다르면 스키마를 지키지 않고
제멋대로 키를 지어낸다 (09-20 실측). 그래서 학습 저장소에서 가져온 두 파일을 그대로 쓴다.

  backend/app/models/kanana_2.1b.prompt.json   system·instruction·separator·stop (학습 설정에서 추출)
  backend/app/models/grammar.gbnf              출력 JSON 문법. 형식을 벗어난 토큰을 아예 막는다

모델과 두 파일이 없으면 이 파일은 "쓸 수 없음"만 알려 주고, llm.py 가 대형 모델로 간다.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

DEFAULT_MODEL_PATH = "backend/app/models/kanana_2.1b-Q4_K_M.gguf"
GRAMMAR_NAME = "grammar.gbnf"
N_THREADS = int(os.environ.get("MODEL_SMALL_THREADS", "8"))

_lock = threading.Lock()  # llama.cpp 인스턴스는 동시 호출에 안전하지 않다
_llm: Any | None = None
_grammar: Any | None = None
_spec: dict[str, Any] | None = None


def model_path() -> Path:
    return Path(os.environ.get("MODEL_SMALL_PATH", DEFAULT_MODEL_PATH))


def prompt_spec_path() -> Path:
    """GGUF 와 짝인 프롬프트 설정. 파일 이름은 모델 이름에서 만든다."""
    path = model_path()
    stem = path.name.split("-")[0]  # kanana_2.1b-Q4_K_M.gguf -> kanana_2.1b
    return path.with_name(f"{stem}.prompt.json")


def available() -> bool:
    """세 파일이 다 있고 llama_cpp 를 import 할 수 있는가."""
    if not (model_path().exists() and prompt_spec_path().exists()):
        return False
    if not (model_path().parent / GRAMMAR_NAME).exists():
        return False
    try:
        import llama_cpp  # noqa: F401
    except ImportError:
        return False
    return True


def _load() -> tuple[Any, Any, dict[str, Any]]:
    """모델을 한 번만 올린다. 1.3GiB 라 요청마다 올리면 답이 안 나온다."""
    global _llm, _grammar, _spec
    if _llm is None:
        from llama_cpp import Llama, LlamaGrammar

        spec = json.loads(prompt_spec_path().read_text(encoding="utf-8"))
        _llm = Llama(
            model_path=str(model_path()),
            n_ctx=int(spec.get("n_ctx", 2048)),
            n_threads=N_THREADS,
            verbose=False,
        )
        _grammar = LlamaGrammar.from_file(str(model_path().parent / GRAMMAR_NAME), verbose=False)
        _spec = spec
    return _llm, _grammar, _spec  # type: ignore[return-value]


def build_prompt(spec: dict[str, Any], text: str) -> str:
    """학습 때와 같은 문자열 (finetune/common/prompting.py 의 render_prompt).

    Llama-3 계열 템플릿이다. system 에 스키마 설명이 통째로 들어간다. 이걸 빼면 모델이 학습한
    출력 형식을 잊고 제 나름의 키를 만든다.
    """
    user = f"{spec['instruction']}{spec['separator']}{text}"
    # <|begin_of_text|> 를 직접 붙이지 않는다. llama.cpp 가 BOS 를 자동으로 넣어 두 번 들어가고,
    # 그러면 학습 때와 토큰 열이 달라진다 (학습 설정도 add_bos: false)
    return (
        "<|start_header_id|>system<|end_header_id|>\n\n"
        f"{spec['system']}<|eot_id|>"
        "<|start_header_id|>user<|end_header_id|>\n\n"
        f"{user}<|eot_id|>"
        "<|start_header_id|>assistant<|end_header_id|>\n\n"
    )


def extract_json(text: str) -> str:
    """모델 출력에서 JSON 문자열만. 파싱과 검증은 부르는 쪽(llm.py)이 한다."""
    llm, grammar, spec = _load()
    with _lock:
        out = llm(
            build_prompt(spec, text),
            max_tokens=int(spec.get("max_new_tokens", 400)),
            temperature=float(spec.get("temperature", 0.0)),
            stop=spec.get("stop") or [],
            grammar=grammar,
        )
    return str(out["choices"][0]["text"]).strip()


def model_name() -> str:
    """결과에 남길 이름. 어느 모델로 뽑았는지 화면과 로그에서 보인다."""
    return f"local/{model_path().stem}"
