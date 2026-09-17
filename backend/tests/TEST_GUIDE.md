# TEST_GUIDE

backend 자동 테스트. API 키 없이 돌아야 한다.

```
pytest backend/tests
```

## 무엇을 검사하나

- `app/domain/`: 규칙 적용, 출발 시각 역산, 전환 조건, 라우팅 판단. 순수 계산이라 바로 검사된다
- `app/schemas/`: 스키마 위반이 실제로 잡히는지. 한자·가나, transport가 None인데 missing에 없는 경우 등 (docs/SDD.md 3절 검증 규칙)
- `app/services/pipeline.py`: 단계 순서와 실패 경로. 외부 호출은 `fixtures/`로 대체

## fixtures/

실제 API 응답 원문을 저장해둔 것. docs/PRD.md 9절 스파이크에서 받은 샘플이 여기로 온다.
카카오·TMAP·공공데이터 응답 형식이 바뀌면 그때 다시 받는다.

## 여기 있으면 안 되는 것

- 진짜 외부 API 호출. 카카오 무료 한도를 먹는다 (미래 운행 일 5,000건). `fixtures/`를 쓴다
- 키가 있어야 도는 테스트. CI에 키가 없다
- 부대명·고객사명 실제 이름. "진해 기지", "여의도 고객사" 수준까지만 (루트 CLAUDE.md)

## 완료 기준

테스트 통과 없이 "완료"라고 하지 않는다.
평가셋(`evals/`)은 별개다. 이건 코드가 맞는지, 그건 서비스가 좋은지를 본다.
