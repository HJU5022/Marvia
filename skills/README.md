# skills

도메인 지식과 판단 재료를 두는 곳. 폴더마다 두 종류의 파일이 있다.

| 파일 | 내용 | 누가 읽나 |
|---|---|---|
| `SKILL.md` | 도메인 지식과 결과 설명법(글). 호출마다 필요한 것을 시스템 프롬프트에 통째로 넣는다. 문서를 청킹해 검색하는 RAG가 아니다 | LLM (`backend/app/services/llm.py`의 `JUDGE_SKILLS` 등) |
| `rules.md` 프론트매터 | 임계값, 목록, 판정 표 재료(계약 C6) | 코드. `backend/app/services/rules.py`가 모든 폴더의 프론트매터를 합쳐 `rule(key)`로 준다 |

규칙: 키 하나는 한 파일에만 둔다(두 파일에 있으면 로드가 실패한다). 판정 문장을 SKILL.md와 코드에 같이 쓰지 않는다. 프론트매터를 고치면 서버를 다시 띄우고 pytest를 다시 돌린다. 프론트매터는 계약 파일이라 바꾸려면 먼저 알리고 PR 리뷰를 거친다.

## 폴더

| 폴더 | SKILL.md | rules.md 프론트매터 |
|---|---|---|
| `ais-reliability/` | AIS 신뢰도: 신호 7종, 출처 우선순위, 정박일 때 위치 읽기 | 신호 기준 시간·속도(`position_stale_hours`, `eta_conflict_hours`, `anchor_speed_kn`, `anchor_wait_hours` 등), 출처 우선순위, 캐시 TTL |
| `cargo-verdict/` | 등급(fine, watch, act)과 되묻기·보류·실패 결과를 설명하는 법 | 2층 판정 표 재료(`margin_act_days`, `act_signals`, `gray_signals`, `ignore_signals`), 판매 예정일 문장 검사 낱말 |
| `customs-stages/` | 통관 단계 읽는 법, 관세사 확인이 필요한 때 | 통관 보류 낱말(`customs_hold_words`), 통관 평가 문장 검사 낱말 |
| `port-busan/` | 부산항 부두·정박지 이름의 뜻, 하역 장소 문장 규칙 | 부산 기준점·반경·항구 코드, 해수부 입항 일정 조회 기간·선명 비교 기준 |
| `port-busan/cargo-vessels.md` | | 입항 예정 선박 검색에서 수입 화물선으로 보는 선종·입항 목적 목록 (`services/chat.py`가 읽는다) |
| `import-basics/` | 수입 실무 기초: B/L 번호를 찾는 곳, 포워더 확인, A/N 같은 낱말. 웹 검색 대신 고정 문서로 둔다 (docs/adr/0020) | 없음. 글만 있는 Skill이라 `rules.md`가 없다 |
| `referrals/` | 안내처 Skill. 프롬프트에 넣지 않는다 | 신호별 안내 문장, 공식 창구 주소·전화 (`services/referrals.py`가 읽어 붙인다) |

프롬프트에 넣는 조합은 `llm.py`가 정한다: 판정은 `ais-reliability`, `customs-stages`, `cargo-verdict`, 선박 후보 판단은 `ais-reliability`, 후속 질문과 채팅 답은 `referrals`를 뺀 다섯 폴더 전부(`import-basics` 포함).

## 테스트

```bash
pytest backend/tests/test_rules.py backend/tests/test_signals.py backend/tests/test_verdict.py
```
