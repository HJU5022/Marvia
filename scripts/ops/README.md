# scripts/ops: 실제 DB와 계정을 바꾸는 스크립트

주의: 이 폴더의 스크립트는 .env의 DATABASE_URL(운영 Supabase일 수 있다)과 암호화 열쇠, Supabase 관리자 키로 진짜 데이터를 바꾼다.
돌리기 전에 파일 머리 주석(docstring)을 읽고, 어느 DB를 가리키는지(.env의 DATABASE_URL) 확인한다.
아래 네 개 모두 실행 전에 "정말 할까요?" 하고 묻는 단계가 없다. 명령을 치면 바로 실행된다 (기능을 더하지 않고 있는 그대로 적는다).

| 스크립트 | 하는 일 | 확인 단계 | 안전장치 |
|---|---|---|---|
| `python -m scripts.ops.grant_operator <이메일>` | 최초 운영자 등록 (이력에 등록자 `bootstrap`) | 없음 (이메일 인자만 받는다) | 마이그레이션 009를 먼저 적용한다 |
| `python -m scripts.ops.encrypt_operator_emails` | 운영자·이력의 평문 이메일을 암호문으로 옮기고 평문을 비운다 | 없음 | 한 트랜잭션. 열쇠가 없어 하나라도 못 잠그면 전부 되돌린다. 다시 돌려도 평문이 남은 행만 건드린다 |
| `python -m scripts.ops.rekey_personal_data` | 개인정보를 BL 열쇠에서 PII 열쇠로 다시 잠근다 | 없음 | 한 트랜잭션. 못 풀거나 못 잠그면 전부 되돌린다. 이미 새 열쇠인 값은 건너뛴다 |
| `python -m scripts.ops.seed_test_users` | 테스트 고객 3명(Supabase 계정 + 회원 정보) 만들기 | 없음 | 이미 있는 계정은 건너뛰고 회원 정보만 가공값으로 다시 맞춘다 |

로컬 시험은 로컬 docker DB(localhost:5433)로 바꿔서 한다 (CLAUDE.md "하지 말 것").
