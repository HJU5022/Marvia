# Langfuse 도착 기록 (집계)

`python scripts/eval/langfuse_evidence.py`가 Langfuse Cloud 공개 API에서 읽은 집계값이다. 생성 2026-10-02T13:03:17+00:00 (UTC), 기간 2026-09-01T00:00:00Z ~ 2026-10-02T23:59:59Z.
트레이스 입력·출력 원문은 담지 않는다. 같은 값이 `langfuse_summary.json`에 있다.

이번 실행에서 API 한도(429)로 못 받아 이전 실행 값을 그대로 둔 항목과 그 값을 받은 시각: {'observations_by_type': '2026-10-02T12:46:29+00:00', 'observations_by_environment': '2026-10-02T12:46:29+00:00', 'observations_by_name': '2026-10-02T12:46:29+00:00', 'generations_total': '2026-10-02T12:46:29+00:00', 'generations_by_model': '2026-10-02T12:46:29+00:00', 'generations_by_prompt': '2026-10-02T12:46:29+00:00', 'generations_by_day': '2026-10-02T12:46:29+00:00', 'generations_eval_sessions': '2026-10-02T12:46:29+00:00', 'tool_observations_by_name': '2026-10-02T12:46:29+00:00', 'tool_observations_by_day': '2026-10-02T12:46:29+00:00', 'tool_observations_eval_sessions': '2026-10-02T12:46:29+00:00', 'distinct_ids': '2026-10-02T12:46:29+00:00', 'scores_by_name': '2026-10-02T12:46:29+00:00'}

## 관측 종류별 개수

| 종류 | 개수 |
|---|---|
| SPAN | 2203 |
| GENERATION | 2058 |
| EVALUATOR | 714 |
| TOOL | 566 |

GENERATION은 LLM 호출, TOOL은 MCP 도구 호출(services/mcp_client.py가 남김), EVALUATOR·SPAN 대부분은 평가 실험(run_experiment)이 문항마다 연 기록이다. TOOL 566개가 MCP 도구 span 도착 근거다.

## 환경별 (평가 실험 vs 그 밖)

| environment | 개수 |
|---|---|
| sdk-experiment | 3936 |
| default | 1605 |

sdk-experiment는 평가 실행기가 남긴 것, default는 서버·스크립트 호출이다.

## LLM 호출 합계

| 호출 | 입력 토큰 | 출력 토큰 | 비용 합 (USD) | p50 지연 (ms) | p95 지연 (ms) |
|---|---|---|---|---|---|
| 2058 | 6235471 | 769036 | 3.000717 | 2061 | 12393.45 |

평가 세션(session_id가 eval-로 시작)만:

| 호출 | 입력 토큰 | 출력 토큰 | 비용 합 (USD) | p50 지연 (ms) | p95 지연 (ms) |
|---|---|---|---|---|---|
| 1232 | 4923316 | 730975 | 2.622249 | 2743.5 | 15032.35 |

## 모델별 LLM 호출

| 모델 | 호출 | 입력 토큰 | 출력 토큰 | 비용 합 (USD) | p95 지연 (ms) |
|---|---|---|---|---|---|
| google/gemini-2.5-flash | 1062 | 3422384 | 497241 | 2.247093 | 12842.0 |
| openai/gpt-4o-mini | 626 | 2033705 | 64778 | 0.222905 | 4603.25 |
| replay/invalid | 118 | 0 | 0 | 0 | 2 |
| qwen/qwen3-235b-a22b-2507 | 68 | 318714 | 146576 | 0.147928 | 23040.95 |
| None | 63 | 0 | 0 | 0 | 8822.3 |
| upstage/solar-pro4 | 43 | 135165 | 10579 | 0.011586 | 13899.0 |
| openai/gpt-4.1-mini | 30 | 120184 | 6026 | 0.027994 | 4108.7 |
| google/gemini-3.8-flash | 24 | 110112 | 43008 | 0.243864 | 29150.3 |
| anthropic/claude-haiku-4.5 | 24 | 95207 | 828 | 0.099347 | 2300.1 |

## 프롬프트 이름·버전별 LLM 호출

| 프롬프트 | 버전 | 호출 |
|---|---|---|
| marvia-judge | 8 | 398 |
| marvia-judge | 2 | 293 |
| marvia-judge-eval | 3 | 231 |
| marvia-judge | 1 | 168 |
| marvia-judge | 3 | 105 |
| marvia-chat-route | 1 | 105 |
| marvia-judge-eval | 1 | 104 |
| None | None | 100 |
| marvia-judge | 4 | 83 |
| marvia-doc-extract | 1 | 80 |
| marvia-pick-vessel | 1 | 48 |
| marvia-judge | 7 | 43 |
| marvia-judge-eval | 2 | 41 |
| marvia-follow-up | 3 | 40 |
| marvia-doc-extract | 4 | 38 |
| marvia-doc-extract | 3 | 36 |
| marvia-port-match | 1 | 28 |
| marvia-follow-up | 5 | 26 |
| marvia-judge | 6 | 25 |
| marvia-judge | 5 | 24 |
| marvia-pick-vessel | 3 | 16 |
| marvia-follow-up | 2 | 11 |
| marvia-follow-up | 4 | 8 |
| marvia-pick-vessel | 2 | 4 |
| marvia-doc-extract | 5 | 3 |

프롬프트가 비어 있는 행은 Langfuse Prompt를 못 읽고 레포 파일(local)로 돈 호출이거나 프롬프트를 쓰지 않는 호출이다.

## 날짜별 LLM 호출

| 날짜 (UTC) | 호출 | 비용 합 (USD) |
|---|---|---|
| 2026-09-28 | 195 | 0.894898 |
| 2026-09-29 | 591 | 1.111637 |
| 2026-09-30 | 249 | 0.151209 |
| 2026-10-01 | 499 | 0.315759 |
| 2026-10-02 | 524 | 0.527214 |

## MCP 도구 호출 (TOOL)

| 도구 | 호출 | p95 지연 (ms) |
|---|---|---|
| mcp:estimate_distance | 198 | 50.9 |
| mcp:get_vessel_candidates | 168 | 454.9 |
| mcp:get_port_schedule | 114 | 1521 |
| mcp:get_live_position | 86 | 299.25 |

| 날짜 (UTC) | 호출 |
|---|---|
| 2026-10-02 | 566 |

## 관측 이름별 개수

| 이름 | 개수 |
|---|---|
| marvia-judge | 1142 |
| experiment-item-evaluation | 714 |
| experiment-item-run | 714 |
| experiment-item-task | 714 |
| evaluator | 714 |
| marvia-judge-eval | 426 |
| mcp:estimate_distance | 198 |
| mcp:get_vessel_candidates | 168 |
| marvia-doc-extract | 157 |
| marvia-chat-route | 128 |
| mcp:get_port_schedule | 114 |
| marvia-follow-up | 87 |
| mcp:get_live_position | 86 |
| marvia-pick-vessel | 68 |
| eval <문항> | 60 |
| marvia-port-match | 44 |
| marvia-memory-write | 5 |
| link-check | 1 |
| link-check-gen | 1 |

## 고유 ID 수

| user_id | session_id | trace |
|---|---|---|
| 169 | 2812 | 2194 |

## 평가 점수 (Dataset 실험이 남긴 score)

| 점수 이름 | 개수 | 평균 |
|---|---|---|
| exact_match | 780 | 0.924359 |
| schema_pass | 780 | 1 |
| verdict_match | 565 | 0.941593 |
| customs_explanation | 353 | 0.790368 |

기간 전체 실험(모델·프롬프트가 다른 실행 포함)을 합친 평균이라 한 실행의 성적이 아니다. 실행별 수치는 evals/results/*.json.

## Prompt Management

| 프롬프트 | 버전 목록 | production | production 등록 | 커밋 메시지 |
|---|---|---|---|---|
| marvia-chat-route | [1] | 1 | 2026-10-01T03:25:30.139Z | None |
| marvia-doc-extract | [1, 2, 3, 4, 5] | 5 | 2026-10-01T05:23:02.174Z | 10-01 역할 고정 문장 2줄 추가 (프롬프트 주입 방어, commit ebd8f84). 기존 글은 그대로 |
| marvia-follow-up | [1, 2, 3, 4, 5] | 5 | 2026-10-01T05:23:00.874Z | 10-01 역할 고정 문장 2줄 추가 (프롬프트 주입 방어, commit ebd8f84). 기존 글은 그대로 |
| marvia-judge | [1, 2, 3, 4, 5, 6, 7, 8] | 8 | 2026-10-01T05:23:00.194Z | 10-01 역할 고정 문장 2줄 추가 (프롬프트 주입 방어, commit ebd8f84). 기존 글은 그대로 |
| marvia-judge-eval | [1, 2, 3] | 3 | 2026-10-01T05:23:02.803Z | 10-01 역할 고정 문장 2줄 추가 (프롬프트 주입 방어, commit ebd8f84). 기존 글은 그대로 |
| marvia-pick-vessel | [1, 2, 3] | 3 | 2026-10-01T05:23:01.543Z | 10-01 역할 고정 문장 2줄 추가 (프롬프트 주입 방어, commit ebd8f84). 기존 글은 그대로 |
| marvia-port-match | [1] | 1 | 2026-10-01T03:25:30.464Z | None |

## Dataset

| 이름 | 문항 | 생성 | 실행 수 |
|---|---|---|---|
| marvia-golden-30 | 30 | 2026-09-29T13:20:44.737Z | 26 |

## 평가 실험 (Experiments)

| 실행 이름 | 시작 (UTC) | 문항 | exact_match | verdict_match | schema_pass | customs_explanation |
|---|---|---|---|---|---|---|
| b google/gemini-2.5-flash thinking=0 10-02 12:42 | 2026-10-02T03:42:44.740Z | 29 | 29/29 | 22/22 | 30/30 | 15/20 |
| c qwen/qwen3-235b-a22b-2507 thinking=0 10-02 11:58 | 2026-10-02T02:58:39.321Z | 30 | 30/30 | 22/22 | 30/30 | 20/21 |
| b openai/gpt-4o-mini thinking=0 10-02 11:54 | 2026-10-02T02:54:15.258Z | 30 | 30/30 | 22/22 | 30/30 | 14/21 |
| b openai/gpt-4o-mini thinking=0 10-02 11:50 | 2026-10-02T02:51:00.946Z | 30 | 30/30 | 22/22 | 30/30 | 13/21 |
| b openai/gpt-4o-mini thinking=0 10-02 11:47 | 2026-10-02T02:47:42.486Z | 30 | 30/30 | 22/22 | 30/30 | 14/21 |
| b openai/gpt-4o-mini thinking=0 10-02 11:44 | 2026-10-02T02:44:39.745Z | 29 | 29/29 | 21/21 | 29/29 | 16/21 |
| b openai/gpt-4o-mini thinking=0 10-02 11:41 | 2026-10-02T02:41:23.852Z | 30 | 30/30 | 22/22 | 30/30 | 17/21 |
| b vertex/google/gemini-2.5-flash thinking=0 10-02 11:34 | 2026-10-02T02:34:47.357Z | 26 | 2/30 | 0/22 | 30/30 |  |
| b openai/gpt-4o-mini thinking=0 10-01 21:29 | 2026-10-01T12:29:30.851Z | 30 | 30/30 | 22/22 | 30/30 | 11/21 |
| c qwen/qwen3-235b-a22b-2507 thinking=0 10-01 20:03 | 2026-10-01T11:03:12.245Z | 30 | 28/30 | 22/22 | 30/30 | 17/18 |
| b openai/gpt-4o-mini thinking=0 10-01 19:50 | 2026-10-01T10:50:44.167Z | 30 | 28/30 | 22/22 | 30/30 | 12/23 |
| b openai/gpt-4o-mini thinking=0 10-01 19:44 | 2026-10-01T10:45:02.174Z | 30 | 28/30 | 22/22 | 30/30 |  |
| b openai/gpt-4o-mini thinking=0 10-01 16:33 | 2026-10-01T07:33:05.422Z | 30 | 28/30 | 22/22 | 30/30 |  |
| a baseline/rules 10-01 16:31 | 2026-10-01T07:31:08.987Z | 30 | 27/30 | 22/22 | 30/30 |  |
| b vertex/google/gemini-2.5-flash thinking=0 10-01 10:35 | 2026-10-01T01:35:50.277Z | 30 | 30/30 | 22/22 | 30/30 | 19/20 |
| b vertex/google/gemini-2.5-flash thinking=0 10-01 10:06 | 2026-10-01T01:06:14.872Z | 30 | 30/30 | 22/22 | 30/30 | 19/21 |
| b vertex/google/gemini-2.5-flash thinking=0 09-30 12:29 | 2026-09-30T03:29:09.500Z | 30 | 30/30 | 22/22 | 30/30 | 16/21 |
| b vertex/google/gemini-2.5-flash thinking=0 09-30 12:17 | 2026-09-30T03:17:49.370Z | 30 | 30/30 | 22/22 | 30/30 | 19/21 |
| b vertex/google/gemini-2.5-flash thinking=0 09-30 01:15 | 2026-09-29T16:15:57.293Z | 30 | 30/30 | 22/22 | 30/30 | 20/21 |
| b vertex/google/gemini-2.5-flash thinking=0 09-30 00:19 | 2026-09-29T15:19:45.047Z | 30 | 29/30 | 20/21 | 30/30 | 18/20 |
| b vertex/google/gemini-2.5-flash thinking=0 09-29 22:49 | 2026-09-29T13:49:42.295Z | 30 | 27/30 | 18/21 | 30/30 | 19/21 |
| a baseline/rules 09-29 22:49 | 2026-09-29T13:49:20.321Z | 30 | 27/30 | 21/21 | 30/30 |  |
| b vertex/google/gemini-2.5-flash thinking=0 09-29 22:35 | 2026-09-29T13:35:35.430Z | 30 | 26/30 | 17/21 | 30/30 |  |
| a baseline/rules 09-29 22:34 | 2026-09-29T13:34:47.503Z | 30 | 27/30 | 21/21 | 30/30 |  |

점수 칸은 맞은 수/채점한 수다. 실행 구간(시작 ~ 끝 + 5초)에 남은 score를 metrics API로 센 값이다.

Dataset 실행 이름 중 Experiments 목록에 없는 것: ['a baseline/rules 09-29 22:30', 'b vertex/google/gemini-2.5-flash thinking=0 09-29 22:31'], 이름이 겹친 실행: []

## 막힌 옛 API

- `/api/public/traces`: HTTP 410
- `/api/public/scores`: HTTP 410
- `/api/public/sessions`: HTTP 410

