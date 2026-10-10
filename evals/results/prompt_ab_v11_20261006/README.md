# 통관 진행 평가 금지 문단 전후 비교 (follow-up 6)

judge·follow-up 프롬프트에 "통관이 잘 될 것처럼 안심시키는 문장을 쓰지 않는다" 문단을 넣기 전과 뒤를 같은 조건으로 돌린 결과다. 이 측정으로 follow-up 6을 올리고 judge는 그대로 뒀다 ([docs/prompt_versions.md](../../../docs/prompt_versions.md) follow-up 6 행).

## 조건

| 항목 | 값 |
|---|---|
| 코드 | 커밋 `334f255` 사본 |
| LLM | Vertex `gemini-3.5-flash-lite`, 해설 채점 끔, Langfuse·OpenRouter 안 씀, 로컬 프롬프트 파일 |
| 문항 | N04·N05·N06·B06, `evals.run_eval --config b --only` 51회 = 204번 |

## 결과 (`python count_only.py <폴더>`로 다시 센다)

| 폴더 | 프롬프트 | V11 위반 (판정/후속) | 1회 통과 | 정답 |
|---|---|---|---|---|
| `v11_vertex_before/` | 넣기 전 | 15 (4/11) | 188/204 | 200/204 |
| `v11_vertex_after/` | 2차 (`prompts_v2/`) | 9 (9/0) | 195/204 | 203/204 |
| `v11_vertex_after_v3/` | 3차 judge (`prompts_v3/`) | 6 (6/0) | 198/204 | 203/204 |

- 후속 답 V11은 11 → 0이라 follow-up 문단을 채택했다
- 판정 쪽 V11은 4 → 9 → 6으로 넣기 전보다 나아지지 않아 judge 문단은 채택하지 않았다
- `n04_after_answers_67.jsonl`은 2차 judge로 N04를 돌린 답 원문이다. V11에 걸린 문장 모양을 보려고 남겼다
- 정답이 아닌 몇 건은 동시 실행으로 생긴 Vertex 429다

## 파일

| 파일 | 무엇 |
|---|---|
| `ab_v11.sh`, `ab_v11_v3.sh` | 실행 스크립트. 코드 사본을 둔 임시 폴더를 `S`로 넘긴다 |
| `count_only.py` | `run_*.txt`에서 문항별 V11·다른 위반·1회 통과를 센다 |
| `prompts_v2/`, `prompts_v3/` | 바꿔 끼운 프롬프트 (`orig_judge.md`는 넣기 전 judge) |
