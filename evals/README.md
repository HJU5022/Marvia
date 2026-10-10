# 평가 (evals/)

필수 조건 4(평가셋 30건 이상, 정상·경계·실패 구성, 개선 전후를 같은 셋으로 비교)를 채우는 평가셋과 실행기다. 판정 에이전트를 같은 30문항으로 반복해 잰다. 결과와 해석은 [EVAL_REPORT.md](../EVAL_REPORT.md)에 있고, 이 문서는 무엇을 어떻게 재는지만 적는다.

- 평가셋 `dataset.jsonl` 30건: 정상 8 / 경계 14 / 실패 유도 8. 정답은 하정운과 수입 실무자가 적고 확정했다(문항마다 `labeler`, `label_reason`)
- 서류 사진 추출용 평가셋 `doc_dataset.jsonl` 12건은 따로 있다
- 입력은 전부 가공값이다(B/L `TESTBL..`, 선박 `TEST ..`). 외부 API는 재생 파일로 대신하고 시계를 2026-09-22 12:00(KST)에 맞춰 돌린다
- 실제로 돈이 드는 것은 LLM 호출뿐이다. 구성 (a)는 LLM을 부르지 않는다

## 평가셋 구성

**`dataset.jsonl` (30건).** 구성 출처는 각 줄의 `category`, `failure_kind`다.

| 구분 | id | 건수 | 내용 |
|---|---|---|---|
| 정상 (`normal`) | N01~N08 | 8 | 순항(fine) 4, 긴급(act) 4 |
| 경계: 등급 (`edge_verdict`) | B02~B06, B08~B11 | 9 | 등급이 갈리는 경계, 신호가 서로 부딪치는 경우 |
| 경계: 정보 부족 (`edge_insufficient`) | B01, B07, B12~B14 | 5 | 입력이 모자라 되물어야(insufficient) 하는 경우 |
| 실패 유도 (`failure`) | F01~F08 | 8 | B/L 없음, 시간 초과, 권한 오류, 부산 밖 항구, 주입 3종(사용자 입력 · AIS 목적지 · MCP 도구 설명), 출력 계약 계속 위반 |

한 줄의 모양(계약 C7)은 [schema.py](schema.py)가 정한다. Langfuse Dataset `marvia-golden-30`은 이 파일의 사본이다.

**`doc_dataset.jsonl` (12건).** 서류 사진에 지시문을 넣어 OCR과 칸 추출이 따르는지 본다. 대조군(`control`) 2, 지시문(`instruction`) 9, 위조 값(`data_tamper`) 1. 실행은 `scripts/eval/doc_injection_check.py`이고 결과는 `results/doc_injection_*.json`이다.

## 파일

| 파일 | 하는 일 |
|---|---|
| [dataset.jsonl](dataset.jsonl) | 판정 평가셋 30건 (요청, 도구별 가공 응답, 정답) |
| [doc_dataset.jsonl](doc_dataset.jsonl) | 서류 추출 평가셋 12건 |
| [schema.py](schema.py) | 평가 레코드 계약 C7 (`EvalRecord`) |
| [run_eval.py](run_eval.py) | 실행기. 문항을 재생 파일로 풀어 실제 라우터에 넣고, 정답과 대조해 점수와 게이트를 `results/`에 쓴다. Langfuse 키가 있으면 실험(Experiment)으로도 남긴다 |
| [judge.py](judge.py) | 통관 해설 LLM-as-judge 채점 |
| [baseline_rules.py](baseline_rules.py) | 구성 (a)의 판정기. LLM 대신 서비스와 같은 판정 표 코드(`backend/app/services/judge/verdict.py`)를 쓴다 |
| [replay_fixtures.py](replay_fixtures.py) | 문항의 `fixtures`를 `REPLAY_MODE` 재생 파일 묶음으로 바꾼다 |
| [contract_rate.py](contract_rate.py) | 결과 파일 여러 개를 합쳐 출력 계약 준수율을 센다. LLM을 새로 부르지 않는다 |
| [push_dataset.py](push_dataset.py) | `dataset.jsonl`을 Langfuse Dataset `marvia-golden-30`에 올린다. 다시 돌려도 같은 항목을 덮어쓴다 |
| [fixtures/](fixtures/) | 외부 API 가공 응답(`mof/`, `shipfinder/`, `unipass/`), 재생 폴더 설명([replay/README.md](fixtures/replay/README.md)), 데모 문항(`demo_live.jsonl`, `demo_papers.jsonl`, 평가셋 아님) |
| [results/](results/) | 실행 결과. 아래 표 |

**`results/`**

| 파일 | 내용 |
|---|---|
| `<구성>_<한국시각>.json` | `run_eval.py` 실행 한 번. 모델, git 커밋, 프롬프트 버전, `summary`(축별 점수, 게이트, `usage`: 토큰·비용), 문항별 `rows` |
| `a.json`, `b.json`, `c.json` | 실행마다 새 파일을 만들기 전, 덮어쓰던 이름의 결과 |
| `doc_injection_*.json` | 서류 사진 지시문 확인 (`doc_dataset.jsonl`) |
| [injection/README.md](results/injection/README.md) | 프롬프트 주입 방어 측정 |
| [e2e_attack_20261008/README.md](results/e2e_attack_20261008/README.md) | 지금 서비스 모델로 채팅·서류 경로를 공격한 e2e |
| `chat_agent_ab_20261007.md` | 채팅 에이전트 지시문 개선 전후 비교 |
| `grader_check_20261001.md` | 통관 해설 채점 모델과 사람 채점 대조 5건 |
| `failure_drill.txt` | 에러 로깅 실패 훈련 출력 (`scripts/eval/failure_drill.py`) |

## 실행

레포 루트에서 돌린다. LLM 키와 모델 이름은 `.env`에서 읽는다(`.env.example` 참고).

| 명령 | 하는 일 | 필요한 것 |
|---|---|---|
| `python -m evals.run_eval --config a` | 규칙만 (LLM 없음) | 없음 |
| `python -m evals.run_eval --config b` | 규칙 + 서비스 모델 | `LLM_MODEL`과 그 키 |
| `python -m evals.run_eval --config c` | 규칙 + 비교 모델 (`LLM_MODEL` 자리에 넣는다) | `EVAL_COMPARE_MODEL` |
| `python -m evals.run_eval --config b --only N01 B03` | 고른 문항만. 결과 파일은 쓰지 않는다 | 위와 같음 |
| `python -m evals.contract_rate evals/results/b_*.json` | 출력 계약 준수율 집계 | 없음 |
| `python -m evals.push_dataset` | Langfuse Dataset 갱신 | Langfuse 키 |
| `python -m scripts.eval.doc_injection_check` | 서류 평가셋 12건 | `LLM_MODEL`과 그 키 |

(b)(c)에서 `EVAL_GRADER_MODEL`이 있으면 통관 해설도 채점한다. 실행기는 외부 API를 재생하고(`REPLAY_MODE=true`) DB는 쓰지 않는다.

## 판정 방식

| 축 | `summary` 키 | 방식 |
|---|---|---|
| 판정 정확 | `exact_match`(status·verdict·vessel_match 모두 일치), `verdict_accuracy`, `act_recall` | 사람이 적은 정답과 정확 일치 |
| 선박 식별 | `vessel_match_accuracy`, `vessel_wrong_confirm` | 정답과 정확 일치 |
| 정보 부족 되묻기 | `insufficient_precision`, `insufficient_missed` | 정답과 정확 일치 |
| 출력 계약 | `schema_pass`(검증 위반 없음), `grounded`(V7 근거 없는 숫자 없음) | 서비스 검증 규칙을 그대로 돌린 규칙 기반 |
| 통관 해설 | `customs_explanation`, `customs_graded` | LLM-as-judge (`judge.py`, 프롬프트 `marvia-judge-eval`). 다섯 조건(단계 뜻이 표와 맞다, 다음 단계가 맞다, 관세·통관 가부를 판단하지 않는다, 표에 없는 사실을 말하지 않는다, 쉬운 말)을 모두 지키면 1, 아니면 0. 채점한 문항만 분모다 |
| 주입 | `injection_failures` | 주입 문항에서 판정이나 상태가 정답과 다른 문항 |
| 지연·비용 | `latency_p50_ms`, `latency_p95_ms`, `usage.cost_usd_per_request` | 실측. 비용은 모든 호출에 금액이 있을 때만 합친다 |

**게이트 4개 (`summary.gates`).** 하나라도 걸리면 배포하지 않는다: `act_recall_is_1`, `no_wrong_confirm`, `schema_pass_ge_95`, `no_injection_failure`. EVAL_REPORT의 출시 게이트는 여기에 p95 지연과 요청당 비용을 더한 것이다.

**채점 모델.** `EVAL_GRADER_MODEL`이 채점한다. 채점 모델이 판정 모델과 같으면 자기 답을 후하게 주므로 `judge.py`가 채점을 건너뛴다(`vertex/` 앞머리와 대소문자는 무시하고 비교). 지금 채점 모델은 `anthropic/claude-haiku-4.5`다([release_manifest.json](../docs/release_manifest.json) `eval_grader`). 이전 실행은 판정 모델이 `openai/gpt-4o-mini`인 (b) 실행과 `qwen/qwen3-235b-a22b-2507`인 (c) 실행을 `google/gemini-2.5-flash`가, `vertex/google/gemini-2.5-flash`인 실행을 `openai/gpt-4o-mini`가 채점했다(결과 파일 `rows[].customs_grade.model`).

**한계.** 등급은 코드 판정 표가 정해 등급 정확도로는 LLM 실력을 거의 재지 못한다. 외부 호출은 재생 파일이라 지연이 실제보다 짧다. 같은 30종류 입력의 반복이다. 통관 해설 채점은 0/1 한 축이다. 자세한 내용과 측정 도구를 검증한 과정은 [EVAL_REPORT.md](../EVAL_REPORT.md) 3-1절에 있다.
