# compare.md - 소형 모델 비교 기록

작성: 2026-09-20. 실측만 적는다. 추정치는 4절에 따로 둔다.

소스: HF `kimseunguk/converge-slot-extractor` 모델카드 (valid 40건, 2026-09-18 측정), SDD 11절 (09-18 실측).

## 1. 정확도 (valid 40건)

| 모델 | 단계 | exact_match | slot_f1 | field_acc 평균 |
|---|---|---|---|---|
| Qwen3-0.6B | base (학습 전) | 0.0% | 32.5% | 31.2% |
| Qwen3-0.6B | lora (학습 후) | 47.5% | 95.3% | 94.8% |
| Kanana-1.5-2.1B-Instruct | base (학습 전) | 7.5% | 47.8% | 53.8% |
| Kanana-1.5-2.1B-Instruct | lora (학습 후) | 85.0% | 99.8% | 98.8% |
| Qwen3-1.7B | base (학습 전) | 7.5% | 38.1% | 49.7% |
| Qwen3-1.7B | lora (학습 후) | 45.0% | 96.4% | 92.0% |

슬롯별 lora F1 (pickup / pickup_at): 0.6B 100.0% / 100.0%, kanana 100.0% / 85.7%, 1.7B 100.0% / 100.0%.

학습 설정: QLoRA 4bit, rank 16, epoch 3, lr 2.0e-4, 배치 16, max_seq 1152, Colab T4.

## 2. 지연 (실측)

T4 GPU fp16, 건당 생성 시간 (lora):

| 모델 | p50 (s) | p95 (s) |
|---|---|---|
| Qwen3-0.6B | 9.31 | 11.85 |
| Kanana-2.1B | 8.65 | 11.95 |
| Qwen3-1.7B | 8.80 | 11.98 |

GGUF CPU (Colab CPU, 스레드 2, 1건, 스키마 검사 통과):

| 모델 | 파일 | CPU 생성 시간 (s) |
|---|---|---|
| Qwen3-0.6B | qwen3_0.6b-Q4_K_M.gguf (0.37 GiB) | 43.45 |
| Kanana-2.1B | kanana_2.1b-Q4_K_M.gguf (1.30 GiB) | 109.62 |
| Qwen3-1.7B | qwen3_1.7b-Q4_K_M.gguf (1.03 GiB) | 82.18 |

모델카드 명시: 실제 서빙 환경에서는 반드시 재측정해야 한다.

OpenRouter (SDD 11절): `openai/gpt-4o-mini`로 slot-extract v2 실호출 1건 통과, 11초, 재시도 없음. 평가셋 30건 기준 통과율은 미측정.

## 3. 크기·비용

| 모델 | GGUF 크기 | VRAM 추정 (Q4, n_ctx 2048) |
|---|---|---|
| Qwen3-0.6B | 0.37 GiB | 약 1 GB |
| Kanana-2.1B | 1.30 GiB | 약 2~2.5 GB |
| Qwen3-1.7B | 1.03 GiB | 약 2 GB |

요청당 비용 추정: Cloud Run GPU L4 약 $0.004, OpenRouter 소형 약 $0.0005. 상한 `COST_LIMIT_USD_PER_REQUEST=0.05` (게이트: 상한 이하).

## 4. 추정치 (실측 아님, 타깃 머신에서 재측정 전 잠정치)

CPU 스레드 증가 추정 (Colab 2스레드 실측 기준, 2->4 약 1.6x, 4->8 약 1.4x 가정):

| 모델 | 2스레드 (실측) | 4스레드 (추정) | 8스레드 (추정) |
|---|---|---|---|
| Qwen3-0.6B | 43.45초 | 약 24~27초 | 약 15~20초 |
| Kanana-2.1B | 109.62초 | 약 65~70초 | 약 45~50초 |
| Qwen3-1.7B | 82.18초 | 약 50초 | 약 33~38초 |

## 5. 현 판단 (2026-09-20)

- 정확도 선택: kanana (EM 85.0%). 대안 0.6B 47.5%, 1.7B 45.0%.
- 지연 게이트 (p95 15초 이하, 콜드 스타트 제외): GPU에서 세 모델 모두 통과. CPU 단독은 kanana 불가, 0.6B는 8vCPU + 최적화 시 가능선.
- KANANA 전제 시 GPU가 필요하다. T4/L4 가장 싼 급으로 충분 (VRAM 2~2.5 GB).

## 6. 미측정 (다음 작업)

- 제출용 평가셋 30건 EM·F1·계약준수율 (EVAL_REPORT.md 빈칸)
- 타깃 머신 llama-bench pp/tg 분리 실측 (`-p 1152 -n 400 -t 2,4,8`)
- GPU 엔드포인트 p50·p95
- 라우팅 전후 요청당 비용 (40번, GGUF 서빙 뒤에 실측)
