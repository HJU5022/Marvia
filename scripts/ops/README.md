# scripts/ops: 실제 DB와 계정을 바꾸는 스크립트

이 폴더의 스크립트는 `.env`의 `DATABASE_URL`(운영 Supabase일 수 있다), 암호화 열쇠, Supabase 관리자 키로 진짜 데이터를 바꾼다. 네 개 모두 "정말 할까요?" 같은 확인 단계 없이 명령을 치면 바로 실행된다. 돌리기 전에 파일 머리 주석(docstring)을 읽고 `DATABASE_URL`이 어느 DB를 가리키는지 확인한다.

| 명령 | 하는 일 | 안전장치 |
|---|---|---|
| `python -m scripts.ops.grant_operator <이메일>` | 최초 운영자 등록. 이력에 등록자는 `bootstrap`으로 남는다. 두 번째부터는 관리 화면에서 등록한다 | 등록 전에 마이그레이션(`009_operators.sql` 포함)을 적용하므로 서버를 한 번도 안 띄운 DB에도 쓸 수 있다 |
| `python -m scripts.ops.encrypt_operator_emails` | 운영자·이력의 평문 이메일을 지문·암호문·가린 값으로 옮기고 평문을 비운다 | 한 트랜잭션. 열쇠가 없어 하나라도 못 잠그면 전부 되돌린다. 다시 돌려도 평문이 남은 행만 건드린다 |
| `python -m scripts.ops.rekey_personal_data` | 개인정보를 `BL_ENCRYPTION_KEY`에서 `PII_ENCRYPTION_KEY`로 다시 잠근다 | 한 트랜잭션. 못 풀거나 못 잠그면 전부 되돌린다. 이미 새 열쇠로 잠긴 값은 건너뛴다 |
| `python -m scripts.ops.seed_test_users` | 테스트 고객 3명(Supabase 계정과 가공 회원 정보) 만들기 | 이미 있는 계정은 건너뛰고 회원 정보만 가공값으로 다시 맞춘다 |

로컬에서 시험할 때는 `.env`의 `DATABASE_URL`을 로컬 docker DB(`localhost:5433`)로 바꿔서 돌린다. 시험 데이터가 운영 DB에 쌓이지 않게 하기 위해서다([CLAUDE.md "하지 말 것"](../../CLAUDE.md#하지-말-것)).
