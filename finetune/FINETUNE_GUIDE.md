# FINETUNE_GUIDE

슬롯 추출용 소형 모델 학습. 가산 항목이다. 필수 조건을 다 채운 뒤에만 가산된다.
이 폴더는 배포 이미지에 들어가지 않는다.

## 데이터

- `data/finetune_dataset.jsonl`: 440건. `gen_dataset.py`가 템플릿 + random(seed 20260917)으로 만든다. LLM 호출 없음
- 형식: instruction / input / output. output은 `backend/app/schemas/slots.py`의 Slots와 완전히 같아야 한다 (docs/SDD.md 3절)
- 스키마가 바뀌면 이 데이터와 평가셋이 같이 깨진다. 그래서 스키마를 임의로 바꾸지 않는다

## 모델 비교 (EVAL_REPORT.md 2-1절)

| 자리 | 모델 |
|---|---|
| 우리 모델 | Qwen3 0.6B 파인튜닝 (또는 HyperCLOVA X SEED 1.5B) |
| 비교군 | 같은 모델 학습 전 베이스, 다른 소형 모델. HF에서 받는다 |
| 상한선 | Sonnet 5 프롬프트만 |

같은 평가셋, 같은 프롬프트, 온도 0.

## 흐름

```
data/ → 학습 → GGUF 변환·4비트 양자화 → HF 업로드 → Docker 빌드 시 받아 이미지에 넣음
```

서버가 켜질 때 받는 게 아니라 이미지 만들 때 한 번 받는다. 콜드 스타트에 다운로드가 안 붙는다 (SDD 1절).

## git에 넣지 않는 것

`*.gguf`, `*.safetensors`, 학습 체크포인트. 나중에 지워도 기록에 남으니 처음부터 `.gitignore`에 둔다.
`data/`의 jsonl(457KB)은 커밋을 권한다 (재현 증거). 아직 미결정.

## 부대명 점검

루트 CLAUDE.md 규칙: 부대명·항만 세부는 "진해 기지" 수준까지만. `gen_dataset.py`의 지명 사전이 이 선을 넘지 않는지 확인한다.
