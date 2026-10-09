# Langfuse 도착 기록 (집계)

`python scripts/eval/langfuse_evidence.py`가 Langfuse Cloud 공개 API에서 읽은 집계값이다. 생성 2026-10-07T12:47:33+00:00 (UTC), 기간 2026-09-01T00:00:00Z ~ 2026-10-08T23:59:59Z.
트레이스 입력·출력 원문은 담지 않는다. 같은 값이 `langfuse_summary.json`에 있다.



## 관측 종류별 개수

| 종류 | 개수 |
|---|---|
| SPAN | 3953 |
| TOOL | 3855 |
| GENERATION | 3832 |
| EVALUATOR | 1224 |

GENERATION은 LLM 호출, TOOL은 MCP 도구 호출(services/mcp_client.py가 남김), EVALUATOR·SPAN 대부분은 평가 실험(run_experiment)이 문항마다 연 기록이다. TOOL 3855개가 MCP 도구 span 도착 근거다.

## 환경별 (평가 실험 vs 그 밖)

| environment | 개수 |
|---|---|
| sdk-experiment | 8400 |
| default | 4243 |
| demo | 221 |

sdk-experiment는 평가 실행기가 남긴 것, default는 서버·스크립트 호출이다.

## LLM 호출 합계

| 호출 | 입력 토큰 | 출력 토큰 | 비용 합 (USD) | p50 지연 (ms) | p95 지연 (ms) |
|---|---|---|---|---|---|
| 3832 | 18856424 | 969212 | 6.899718 | 2042.5 | 10907.85 |

평가 세션(session_id가 eval-로 시작)만:

| 호출 | 입력 토큰 | 출력 토큰 | 비용 합 (USD) | p50 지연 (ms) | p95 지연 (ms) |
|---|---|---|---|---|---|
| 1639 | 8066710 | 803415 | 3.455242 | 2444 | 13426.9 |

## 모델별 LLM 호출

| 모델 | 호출 | 입력 토큰 | 출력 토큰 | 비용 합 (USD) | p95 지연 (ms) |
|---|---|---|---|---|---|
| google/gemini-2.5-flash | 1142 | 3623661 | 499479 | 2.294128 | 12411.85 |
| openai/gpt-4o-mini | 1138 | 3606741 | 103735 | 0.388903 | 4665.1 |
| google/gemini-3.5-flash-lite | 669 | 8472866 | 101632 | 2.677105 | 8575.6 |
| anthropic/claude-haiku-4.5 | 247 | 991828 | 4173 | 1.012693 | 2315.1 |
| None | 193 | 0 | 0 | 0 | 22590.8 |
| replay/invalid | 160 | 0 | 0 | 0 | 2006 |
| deepseek/deepseek-v4-flash | 118 | 1477153 | 54004 | 0.095517 | 56374.35 |
| qwen/qwen3-235b-a22b-2507 | 68 | 318714 | 146576 | 0.147928 | 23040.95 |
| upstage/solar-pro4 | 43 | 135165 | 10579 | 0.011586 | 13899.0 |
| openai/gpt-4.1-mini | 30 | 120184 | 6026 | 0.027994 | 4108.7 |
| google/gemini-3.8-flash | 24 | 110112 | 43008 | 0.243864 | 29150.3 |

## 프롬프트 이름·버전별 LLM 호출

| 프롬프트 | 버전 | 호출 |
|---|---|---|
| marvia-judge-eval | 3 | 532 |
| marvia-judge | 8 | 469 |
| marvia-judge | 10 | 330 |
| None | None | 297 |
| marvia-judge | 2 | 293 |
| marvia-chat-agent | 10 | 234 |
| marvia-judge | 1 | 168 |
| marvia-chat-route | 1 | 149 |
| marvia-chat-title | 1 | 146 |
| marvia-judge | 3 | 105 |
| marvia-judge-eval | 1 | 104 |
| marvia-judge | 9 | 97 |
| marvia-judge | 4 | 83 |
| marvia-doc-extract | 1 | 80 |
| marvia-follow-up | 5 | 70 |
| marvia-memory-write | 1 | 60 |
| marvia-port-match | 1 | 53 |
| marvia-chat-agent | 12 | 49 |
| marvia-pick-vessel | 1 | 48 |
| marvia-doc-extract | 6 | 47 |
| marvia-judge | 7 | 43 |
| marvia-judge-eval | 2 | 41 |
| marvia-follow-up | 3 | 40 |
| marvia-doc-extract | 4 | 38 |
| marvia-doc-extract | 3 | 36 |
| marvia-chat-agent | 14 | 29 |
| marvia-judge | 6 | 25 |
| marvia-judge | 5 | 24 |
| marvia-chat-agent | 13 | 24 |
| marvia-chat-agent | 11 | 22 |
| marvia-pick-vessel | 3 | 18 |
| marvia-chat-route | 2 | 14 |
| marvia-follow-up | 9 | 13 |
| marvia-chat-agent | 3 | 13 |
| marvia-follow-up | 2 | 11 |
| marvia-follow-up | 4 | 8 |
| marvia-pick-vessel | 2 | 4 |
| marvia-doc-extract | 5 | 3 |
| marvia-chat-agent | 2 | 3 |
| marvia-chat-agent | 9 | 3 |
| marvia-follow-up | 6 | 2 |
| marvia-follow-up | 8 | 2 |
| marvia-chat-agent | 7 | 1 |
| marvia-chat-agent | 4 | 1 |

프롬프트가 비어 있는 행은 Langfuse Prompt를 못 읽고 레포 파일(local)로 돈 호출이거나 프롬프트를 쓰지 않는 호출이다.

## 날짜별 LLM 호출

| 날짜 (UTC) | 호출 | 비용 합 (USD) |
|---|---|---|
| 2026-09-28 | 195 | 0.894898 |
| 2026-09-29 | 591 | 1.111637 |
| 2026-09-30 | 249 | 0.151209 |
| 2026-10-01 | 499 | 0.315759 |
| 2026-10-02 | 524 | 0.527214 |
| 2026-10-05 | 262 | 0.554383 |
| 2026-10-06 | 1166 | 2.285917 |
| 2026-10-07 | 346 | 1.058702 |

## MCP 도구 호출 (TOOL)

| 도구 | 호출 | p95 지연 (ms) |
|---|---|---|
| mcp:estimate_distance | 1314 | 87 |
| mcp:get_vessel_candidates | 930 | 489.55 |
| mcp:get_port_schedule | 737 | 1509.2 |
| mcp:get_live_position | 660 | 317.05 |
| unipass:fetch | 76 | 565 |
| mof:find_plan_by_mrn | 35 | 2476.2 |
| shipfinder.VesselPositionSingle | 30 | 291.45 |
| mof:sailing_plans_all | 22 | 5222.2 |
| shipfinder.VesselSearch | 21 | 222 |
| ocr:read | 17 | 54165.2 |
| shipfinder.VesselFlagInfo | 8 | 44.3 |
| vessel_watch.resolve_mmsi | 5 | 209.8 |

| 날짜 (UTC) | 호출 |
|---|---|
| 2026-10-02 | 566 |
| 2026-10-05 | 315 |
| 2026-10-06 | 2401 |
| 2026-10-07 | 573 |

## 관측 이름별 개수

| 이름 | 개수 |
|---|---|
| marvia-judge | 1640 |
| mcp:estimate_distance | 1314 |
| experiment-item-task | 1224 |
| evaluator | 1224 |
| experiment-item-evaluation | 1224 |
| experiment-item-run | 1224 |
| mcp:get_vessel_candidates | 930 |
| mcp:get_port_schedule | 737 |
| marvia-judge-eval | 729 |
| mcp:get_live_position | 660 |
| marvia-chat-agent | 389 |
| marvia-doc-extract | 204 |
| marvia-memory-write | 194 |
| marvia-chat-route | 186 |
| marvia-follow-up | 148 |
| marvia-chat-title | 146 |
| request:/api/chat/stream | 107 |
| request:/api/agent | 82 |
| unipass:fetch | 76 |
| marvia-pick-vessel | 70 |
| marvia-port-match | 69 |
| eval <문항> | 60 |
| web_search | 56 |
| mof:find_plan_by_mrn | 35 |
| shipfinder.VesselPositionSingle | 30 |
| mof:sailing_plans_all | 22 |
| shipfinder.VesselSearch | 21 |
| ocr:read | 17 |
| request:/api/chat | 13 |
| request:/api/document | 9 |
| request:/api/document/bl | 8 |
| shipfinder.VesselFlagInfo | 8 |
| vessel_watch.resolve_mmsi | 5 |
| sim-experiment-item-run | 1 |
| link-check | 1 |
| link-check-gen | 1 |

## 고유 ID 수

| user_id | session_id | trace |
|---|---|---|
| 1327 | 7516 | 4187 |

## 평가 점수 (Dataset 실험이 남긴 score)

| 점수 이름 | 개수 | 평균 |
|---|---|---|
| exact_match | 1290 | 0.931783 |
| schema_pass | 1290 | 1 |
| verdict_match | 939 | 0.941427 |
| customs_explanation | 653 | 0.849923 |

기간 전체 실험(모델·프롬프트가 다른 실행 포함)을 합친 평균이라 한 실행의 성적이 아니다. 실행별 수치는 evals/results/*.json.

## Prompt Management

| 프롬프트 | 버전 목록 | production | production 등록 | 커밋 메시지 |
|---|---|---|---|---|
| marvia-chat-agent | [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] | 14 | 2026-10-07T08:23:20.296Z | None |
| marvia-chat-route | [1, 2] | 2 | 2026-10-07T00:10:51.600Z | 10-07 실사용 2·3·5·6: 답 꼬리표 삭제, B/L 표기, 회사 연락처는 검색 결과만, 한글 배 이름 |
| marvia-chat-title | [1] | 1 | 2026-10-05T17:09:20.124Z | None |
| marvia-doc-extract | [1, 2, 3, 4, 5, 6] | 6 | 2026-10-06T04:11:59.985Z | 10-06: 10-02 칸(doc_kind, original_bl, to_order_bank, freight_term, incoterm, contact) + etd. 레포 backend/app/prompts/marvia-doc-extract.md 전체 |
| marvia-follow-up | [1, 2, 3, 4, 5, 6, 7, 8, 9] | 9 | 2026-10-07T03:33:18.686Z | None |
| marvia-judge | [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 10 | 2026-10-06T04:56:37.949Z | 10-06: 통관 해설 예시를 뜻이 들어간 문장으로 (judge 9 회귀 수정) |
| marvia-judge-eval | [1, 2, 3] | 3 | 2026-10-01T05:23:02.803Z | 10-01 역할 고정 문장 2줄 추가 (프롬프트 주입 방어, commit ebd8f84). 기존 글은 그대로 |
| marvia-memory-write | [1] | 1 | 2026-10-07T06:28:00.233Z | None |
| marvia-pick-vessel | [1, 2, 3] | 3 | 2026-10-01T05:23:01.543Z | 10-01 역할 고정 문장 2줄 추가 (프롬프트 주입 방어, commit ebd8f84). 기존 글은 그대로 |
| marvia-port-match | [1] | 1 | 2026-10-01T03:25:30.464Z | None |

## Dataset

| 이름 | 문항 | 생성 | 실행 수 |
|---|---|---|---|
| marvia-golden-30 | 30 | 2026-09-29T13:20:44.737Z | 43 |

## 평가 실험 (Experiments)

| 실행 이름 | 시작 (UTC) | 문항 | exact_match | verdict_match | schema_pass | customs_explanation |
|---|---|---|---|---|---|---|
| b vertex/google/gemini-3.5-flash-lite 10-07 09:33 | 2026-10-07T00:33:31.288Z | 30 |  |  |  |  |
| b google/gemini-3.5-flash-lite 10-06 23:04 | 2026-10-06T14:04:31.950Z | 30 |  |  |  |  |
| b google/gemini-3.5-flash-lite 10-06 23:02 | 2026-10-06T14:02:44.506Z | 30 |  |  |  |  |
| b google/gemini-3.5-flash-lite 10-06 23:00 | 2026-10-06T14:00:54.477Z | 30 |  |  |  |  |
| b google/gemini-3.5-flash-lite 10-06 22:59 | 2026-10-06T13:59:10.929Z | 30 |  |  |  |  |
| b google/gemini-3.5-flash-lite 10-06 22:57 | 2026-10-06T13:57:30.284Z | 30 |  |  |  |  |
| b google/gemini-3.5-flash-lite 10-06 22:09 | 2026-10-06T13:09:10.842Z | 30 |  |  |  |  |
| b google/gemini-3.5-flash-lite 10-06 22:07 | 2026-10-06T13:07:15.668Z | 30 |  |  |  |  |
| b google/gemini-3.5-flash-lite thinking=0 10-06 22:03 | 2026-10-06T13:03:31.890Z | 30 |  |  |  |  |
| a baseline/rules 10-06 21:57 | 2026-10-06T12:57:49.129Z | 30 |  |  |  |  |
| b openai/gpt-4o-mini thinking=0 10-06 17:37 | 2026-10-06T08:37:32.918Z | 30 |  |  |  |  |
| b openai/gpt-4o-mini thinking=0 10-06 13:56 | 2026-10-06T04:56:55.116Z | 30 |  |  |  |  |
| b openai/gpt-4o-mini thinking=0 10-06 13:48 | 2026-10-06T04:48:13.686Z | 30 |  |  |  |  |
| b openai/gpt-4o-mini thinking=0 10-06 10:49 | 2026-10-06T01:49:39.085Z | 30 |  |  |  |  |
| b openai/gpt-4o-mini thinking=0 10-06 10:48 | 2026-10-06T01:48:59.988Z | 30 |  |  |  |  |
| b google/gemini-3.5-flash-lite thinking=0 10-06 00:44 | 2026-10-05T15:44:09.530Z | 30 |  |  |  |  |
| b google/gemini-3.5-flash-lite thinking=0 10-05 22:03 | 2026-10-05T13:03:04.171Z | 30 |  |  |  |  |
| b google/gemini-2.5-flash thinking=0 10-02 12:42 | 2026-10-02T03:42:44.740Z | 29 |  |  |  |  |
| c qwen/qwen3-235b-a22b-2507 thinking=0 10-02 11:58 | 2026-10-02T02:58:39.321Z | 30 |  |  |  |  |
| b openai/gpt-4o-mini thinking=0 10-02 11:54 | 2026-10-02T02:54:15.258Z | 30 |  |  |  |  |
| b openai/gpt-4o-mini thinking=0 10-02 11:50 | 2026-10-02T02:51:00.946Z | 30 |  |  |  |  |
| b openai/gpt-4o-mini thinking=0 10-02 11:47 | 2026-10-02T02:47:42.486Z | 30 |  |  |  |  |
| b openai/gpt-4o-mini thinking=0 10-02 11:44 | 2026-10-02T02:44:39.745Z | 29 |  |  |  |  |
| b openai/gpt-4o-mini thinking=0 10-02 11:41 | 2026-10-02T02:41:23.852Z | 30 |  |  |  |  |
| b vertex/google/gemini-2.5-flash thinking=0 10-02 11:34 | 2026-10-02T02:34:47.357Z | 26 |  |  |  |  |
| b openai/gpt-4o-mini thinking=0 10-01 21:29 | 2026-10-01T12:29:30.851Z | 30 |  |  |  |  |
| c qwen/qwen3-235b-a22b-2507 thinking=0 10-01 20:03 | 2026-10-01T11:03:12.245Z | 30 |  |  |  |  |
| b openai/gpt-4o-mini thinking=0 10-01 19:50 | 2026-10-01T10:50:44.167Z | 30 |  |  |  |  |
| b openai/gpt-4o-mini thinking=0 10-01 19:44 | 2026-10-01T10:45:02.174Z | 30 |  |  |  |  |
| b openai/gpt-4o-mini thinking=0 10-01 16:33 | 2026-10-01T07:33:05.422Z | 30 |  |  |  |  |
| a baseline/rules 10-01 16:31 | 2026-10-01T07:31:08.987Z | 30 |  |  |  |  |
| b vertex/google/gemini-2.5-flash thinking=0 10-01 10:35 | 2026-10-01T01:35:50.277Z | 30 |  |  |  |  |
| b vertex/google/gemini-2.5-flash thinking=0 10-01 10:06 | 2026-10-01T01:06:14.872Z | 30 |  |  |  |  |
| b vertex/google/gemini-2.5-flash thinking=0 09-30 12:29 | 2026-09-30T03:29:09.500Z | 30 |  |  |  |  |
| b vertex/google/gemini-2.5-flash thinking=0 09-30 12:17 | 2026-09-30T03:17:49.370Z | 30 |  |  |  |  |
| b vertex/google/gemini-2.5-flash thinking=0 09-30 01:15 | 2026-09-29T16:15:57.293Z | 30 |  |  |  |  |
| b vertex/google/gemini-2.5-flash thinking=0 09-30 00:19 | 2026-09-29T15:19:45.047Z | 30 |  |  |  |  |
| b vertex/google/gemini-2.5-flash thinking=0 09-29 22:49 | 2026-09-29T13:49:42.295Z | 30 |  |  |  |  |
| a baseline/rules 09-29 22:49 | 2026-09-29T13:49:20.321Z | 30 |  |  |  |  |
| b vertex/google/gemini-2.5-flash thinking=0 09-29 22:35 | 2026-09-29T13:35:35.430Z | 30 |  |  |  |  |
| a baseline/rules 09-29 22:34 | 2026-09-29T13:34:47.503Z | 30 |  |  |  |  |

점수 칸은 맞은 수/채점한 수다. 실행 구간(시작 ~ 끝 + 5초)에 남은 score를 metrics API로 센 값이다.

Dataset 실행 이름 중 Experiments 목록에 없는 것: ['a baseline/rules 09-29 22:30', 'b vertex/google/gemini-2.5-flash thinking=0 09-29 22:31'], 이름이 겹친 실행: []

## 막힌 옛 API

- `/api/public/traces`: HTTP 410
- `/api/public/scores`: HTTP 410
- `/api/public/sessions`: HTTP 410

