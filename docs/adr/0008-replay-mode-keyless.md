# 0008. REPLAY_MODE로 키 없이 데모와 평가를 재현한다

상태: 채택

## 맥락
ShipFinder와 UNI-PASS 약관상 실제 응답 원본을 레포에 커밋할 수 없다. 팀원과 처음 받아 보는 사람이 키 없이도 돌려 볼 수 있어야 한다. 완료 기준은 clone 후 10분 안에 `/health` 200과 데모 B/L 1건 응답이다 ([SDD 6.6절](../Marvia_SDD.md)).

## 결정
- `REPLAY_MODE=true`면 외부 API 대신 `evals/fixtures/`의 가공 응답을 읽는다. 데모 B/L은 13건(라이브 데모 `DEMO..` 10건 + 평가셋 TESTBL01, 04, 26)이다.
- fixture는 실제 응답과 형식만 같은 가공값이다. 실제 수집값은 DB에만 둔다.
- 평가는 시계를 문항의 clock(2026-09-22 12:00)에 맞추고 돌린다 (`evals/run_eval.py`).
- 데모 위치는 약 5시간 반 뒤 오래된 위치가 되므로, 재생 모드 서버는 4시간마다 재생 파일을 다시 만든다 ([SDD 6.1절](../Marvia_SDD.md)).
- 재생 모드는 키 없는 재현, 로컬 데모, 평가용이다. 배포 서버는 쓰지 않는다 ([0010](0010-deployed-server-real-mode.md)).

## 결과
- 좋아진 것: 테스트와 평가가 키 없이 돈다. 재생 모드에서는 하루 토큰 한도도 두지 않는다 ([0018](0018-daily-token-quota.md)).
- 대가: 지연이 실제보다 짧고, 실제 API 오류 모양은 문항으로 만든 것만 본다 ([EVAL_REPORT 3-1절](../../EVAL_REPORT.md)). SDD 6.6절의 "다른 노트북에서 재현"은 기록이 없다.

## 근거
- [CLAUDE.md](../../CLAUDE.md) "할 것": "REPLAY_MODE=true면 외부 API 대신 evals/fixtures/를 읽어 데모 B/L이 키 없이 동작해야 한다"
- [SDD](../Marvia_SDD.md) 6.1절, 6.4절, 6.6절
- [EVAL_REPORT.md](../../EVAL_REPORT.md) 3절, 3-1절
- 커밋 `c577c56`(4시간마다 재생 파일 갱신)
