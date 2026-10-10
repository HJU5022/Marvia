# skills

도메인 지식과 판단 재료를 두는 곳이다. 폴더는 6개다. 폴더마다 `SKILL.md`가 있고, 코드가 읽는 값이 있는 폴더에는 `rules.md`도 있다(`import-basics`는 `SKILL.md`만 있다).

| 파일 | 내용 | 누가 읽나 |
|---|---|---|
| `SKILL.md` | 도메인 지식과 결과 설명법(글). 호출마다 필요한 폴더의 문서를 시스템 프롬프트에 통째로 넣는다. 문서를 청킹해 검색하는 RAG가 아니다 | LLM. 묶음에 든 폴더의 `*.md`를 모두 넣는다(`backend/app/services/llm.py`의 `_skills_text`). 어느 폴더를 넣을지는 같은 파일의 Skill 묶음 상수가 정한다 (아래 표) |
| `rules.md` 프론트매터 | 임계값, 목록, 판정 표 재료. 계약 C6이다([docs/Marvia_SDD.md](../docs/Marvia_SDD.md) 3.6절) | 코드와 LLM. 코드에서는 `backend/app/services/judge/rules.py`가 모든 폴더의 `rules.md` 프론트매터를 합쳐 `rule(key)`로 준다. 같은 폴더 문서라 LLM 프롬프트에도 함께 들어간다(`llm.py`의 `_skills_text`) |

규칙:
- 키 하나는 한 파일에만 둔다. 두 파일에 있으면 로드가 실패한다(`ValueError`).
- 판정 문장을 SKILL.md와 코드에 같이 쓰지 않는다.
- 프론트매터는 서버가 처음 한 번만 읽는다. 고치면 서버를 다시 띄우고 pytest를 다시 돌린다.
- 프론트매터는 계약 파일이라 바꾸려면 먼저 알리고 PR 리뷰를 거친다.

## 폴더

| 폴더 | SKILL.md | rules.md 프론트매터 |
|---|---|---|
| `ais-reliability/` | AIS 신뢰도: 신호 7종, 출처 우선순위, 정박일 때 위치 읽기 | 신호 기준 시간·속도(`position_stale_hours`, `eta_conflict_hours`, `anchor_speed_kn`, `anchor_wait_hours` 등), 출처 우선순위, 캐시 TTL |
| `cargo-verdict/` | 등급(fine, watch, act)과 되묻기·보류·실패 결과를 설명하는 법 | 2층 판정 표 재료(`margin_act_days`, `act_signals`, `gray_signals`, `ignore_signals`), 판매 예정일 문장 검사 낱말 |
| `customs-stages/` | 통관 단계 읽는 법, 관세사 확인이 필요한 때 | 통관 단계 목록, 통관 보류 낱말(`customs_hold_words`), 통관 평가 문장 검사 낱말 |
| `port-busan/` | 부산항 부두·정박지 이름의 뜻, 하역 장소 문장 규칙 | 부산 기준점·반경·항구 코드, 해수부 입항 일정 조회 기간·선명 비교 기준 |
| `import-basics/` | 수입 실무 기초: B/L 번호를 찾는 곳, 포워더 확인, A/N 같은 낱말. 웹 검색 대신 고정 문서로 둔다([ADR 0020](../docs/adr/0020-remove-web-search-use-skill.md)) | 없다. 글만 있는 Skill이다 |
| `referrals/` | 답 끝에 붙는 "확인처:" 줄의 Skill. LLM 프롬프트에는 넣지 않는다 | 신호별 확인처 문장, 공식 창구 주소·전화. `backend/app/services/chat/referrals.py`가 `rule()`로 읽어 붙인다 |

`port-busan/cargo-vessels.md`는 따로 읽는 파일이다. 입항 예정 선박 검색에서 수입 화물선으로 보는 선종과 입항 목적 목록이 프론트매터에 있다. `rule()` 합치기에는 들어가지 않는다. 코드에서는 `backend/app/services/chat/ids.py`가 읽고, port-busan이 든 묶음(후속 질문, 채팅 에이전트)에서는 프롬프트에도 들어간다.

## 프롬프트에 넣는 묶음

`backend/app/services/llm.py`의 상수가 정한다.

| 상수 | 폴더 | 쓰는 곳 |
|---|---|---|
| `JUDGE_SKILLS` | ais-reliability, customs-stages, cargo-verdict | 판정 설명 |
| `PICK_SKILLS` | ais-reliability | 선박 후보 판단 |
| `FOLLOW_UP_SKILLS` | ais-reliability, customs-stages, port-busan, cargo-verdict, import-basics | 후속 질문 |
| `CHAT_AGENT_SKILLS` | `FOLLOW_UP_SKILLS`와 같다 | 채팅 에이전트 |
| `GRADE_SKILLS` | customs-stages | 통관 해설 채점 (평가 때만) |

`referrals`는 어느 묶음에도 없다. `import-basics`는 후속 질문과 채팅 에이전트에만 들어간다.

## 테스트

```bash
pytest backend/tests/unit/test_rules.py backend/tests/unit/test_signals.py backend/tests/unit/test_verdict.py
```
