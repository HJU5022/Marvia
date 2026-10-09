# Marvia PRD

기준 문서: 2차 팀 프로젝트 가이드 v4 · 유형: [유형 1] 도메인 특화 LLM 서비스

- **누구:** 포워더가 일일이 챙겨 주지 않는 소량 해상 수입자. 부산항으로 들어오는 화물 몇 건을 관리한다.
- **문제:** 추적 서비스의 ETA를 믿어도 되는지, 그 배가 내 배가 맞는지, 통관 단계가 무슨 뜻인지 판단하지 못한다.
- **해결:** 채팅에 B/L을 넣으면 **순항 / 주의 / 긴급**과 할 일을 근거와 함께 답한다. 등급은 코드 판정 표가 정하고, LLM은 설명·되묻기·회색 지대 상향을 맡는다.
- **차별점:** ① 배를 확정하지 못하면 판정 대신 되묻는다 ② 서로 어긋나는 신호 중 무엇을 믿는지 근거로 밝힌다.
- **읽는 순서:** 이 문서(무엇을, 왜) → [SDD](Marvia_SDD.md)(어떻게) → [EVAL_REPORT](../EVAL_REPORT.md)(얼마나 잘) → [ADR](adr/README.md)(왜 그렇게 정했나). 처음 계획과 달라진 점은 맨 끝 표에 모았다.

## 1. 한 줄 정의

B/L 번호(판매 예정일은 선택)를 채팅으로 넣으면 "내 화물, 지금 신경 써야 하나?"에 **순항 / 주의 / 긴급**(코드 값 fine / watch / act)으로 답하는 에이전트. 그 배가 내 화물 배가 맞는지 확정하고, 서로 안 맞는 신호 중 무엇을 믿을지 근거로 가르고, 확정 못 하면 판정 대신 되묻는다. 모든 판정에 출처와 조회 시각이 붙는다.

## 2. 문제와 사용자

**사용자:** 포워더가 일일이 챙겨주지 않는 소량 해상 수입자(스마트스토어 수입 셀러, 구매대행). 자기 B/L 번호를 알고, 부산항으로 들어오는 화물 몇 건을 관리한다.

**문제:** 추적 서비스의 ETA를 믿어도 되는지, 그 배가 내 배가 맞는지, 유니패스 통관 단계가 무슨 뜻인지 판단하지 못해 포워더 문의와 직접 확인에 시간을 쓰고, 지연을 늦게 알아 판매 일정이 틀어진다.

| 현재 하는 일 | 문제 |
| --- | --- |
| 추적 서비스에서 ETA 확인 | 위치가 오래됐거나 값이 깨져도 ETA가 그대로 보임 |
| 선명으로 배 찾기 | 동명 선박이 여러 척이면 어느 게 내 배인지 모름 |
| 유니패스 통관 단계 조회 | 단계명의 뜻과 다음 할 일을 모름 |
| 포워더에 문의 | 응답이 늦고 소량 화주는 우선순위가 낮음 |

**도메인 근거:** 팀원 한 명이 해군 함정에서 AIS·항해 상태·입출항 절차를 직접 다뤘다. 이 문서는 그를 **AIS 판독 경험자**라고 부른다. 군함 데이터는 기밀이라 같은 해운 도메인의 상선 공개 데이터(AIS·UNI-PASS·해수부 공공데이터)로 대입했다. 이 경험은 AIS 값이 언제 깨지는지 아는 판독 경험이며 Skill 판정 기준이 된다. 사용자(수입자) 쪽 업무 흐름은 팀원 가족의 중국·동남아 농수산물 수입/수출/가공 경험에서 빌렸다. 수입자 경험은 직접이 아니라 간접이다.

## 3. 유사 제품과 차별점

같은 문제를 푸는 서비스가 있다는 것은 문제가 실재한다는 근거다. 세 곳을 봤다.

| 서비스 | 누구 대상 | 하는 것 | 이 서비스와 다른 점 |
| --- | --- | --- | --- |
| 트레드링스 | 화주 일반, 무료 | B/L 추적, 선박 위치, AI-ETA, 지연 알림 | ETA를 주지만 "믿어도 되는지, 왜"는 안 준다. 배가 내 배인지는 전제 |
| 쉽다(ShipDa) | 스마트스토어 셀러·소량 수입자 (우리 사용자와 겹침) | 디지털 포워딩 + 선박 항적 지도, 통관 지원 | 쉽다로 운송을 맡겨야 추적된다. 이 서비스는 어느 포워더 B/L이든 된다 |
| 삼성SDS Cello Square | 대형 화주 | 항만 혼잡도까지 넣은 예측 ETA, 출항일 예측 | 대형용. 예측이 블랙박스라 근거·되묻기가 없다 |

셋의 공통 빈칸이 곧 차별점이다: 그 배가 내 배인가 · 이 ETA를 왜 믿거나 못 믿나 · 판매 예정일 대비 뭘 해야 하나. 가장 가까운 트레드링스와 항목별로 비교하면 아래와 같다.

| 구분 | 트레드링스 | 이 서비스 |
| --- | --- | --- |
| 선박 위치·ETA | 제공 | 제공 |
| 내 화물 배가 맞는지 | 사용자가 맞다고 전제 | 확정할 근거가 없으면 확정하지 않고 되묻는다 |
| ETA를 믿어도 되는지 | 확률 범위 | 왜 못 믿는지 근거(53일 전 위치, 깨진 목적지, 속도 0인데 항해 중) |
| 판정 기준 | 일반 지연 | 사용자 판매 예정일 대비 여유 일수 (판매 예정일을 주면) |
| 할 일 | 지연 알림 | 3단계 판정 + 사용자 상황에 맞는 할 일 |
| 통관 단계 | 단계명 그대로 | 뜻·다음 단계·할 일 |

차별점의 중심은 선박 식별 되묻기와 신호 상충 해석 둘이다. 트레드링스 화면은 사업자 로그인이 필요해 직접 확인하지 못했고, 비교표는 공개 소개 페이지 기준이다.

## 4. 범위

| 구분 | 내용 | 상세 |
| --- | --- | --- |
| P0 | B/L → 선박 식별(불확실하면 되묻기) · 위치·ETA · 판정과 할 일 · 통관 단계 해설 · 하역 장소 · 근거 카드 · 후속 질문(근거 안에서만) · 출력 계약·재시도·폴백 · 평가셋 30건 + 규칙만 버전과 비교 | [SDD 4.1](Marvia_SDD.md) |
| P1 (구현함) | 서류 사진·PDF(입항 통지서, B/L 사본)에서 B/L·선명·ETA 등 칸 추출. 서류에서 읽은 B/L은 가려서 LLM에 준다 | [specs/document-extract.md](specs/document-extract.md), SDD 4.7 |

**처음 범위 밖이던 것 가운데 만든 것.** 코드와 라우터(`backend/app/routers/`)가 있는 것만 적었다.

| 기능 | 만든 것 | 상세 |
|---|---|---|
| 채팅 창구 | 화면의 기본 입력. 자연어 한 줄을 채팅 에이전트가 받아 도구를 골라 쓴다(`/api/chat`, 진행 단계 스트림 `/api/chat/stream`). 지난 대화 목록·삭제 | [specs/chat-search.md](specs/chat-search.md), [specs/chat-progress.md](specs/chat-progress.md), SDD 4.5·4.6, [ADR 0016](adr/0016-chat-agent-with-tools-and-guard.md) |
| 로그인·회원 | Supabase 로그인, 조회를 사용자에 묶기, B/L·회원 정보 암호화 저장, 탈퇴 | [specs/user-profile.md](specs/user-profile.md), SDD 5.15 |
| 기억 | 지난 조회·말에서 뽑은 화물 표와 메모장. 보기·지우기. 등급에는 쓰지 않는다 | [specs/memory.md](specs/memory.md), [ADR 0017](adr/0017-memory-feature-decisions.md) |
| 지켜보기·알림 | 사용자가 켠 화물(1명당 최대 5건, `services/watch/watch.py` `MAX_WATCH`)의 배 위치 지도, 카카오톡 "나에게 보내기". 워커의 자동 재판정은 배포에서 꺼져 있다(`docs/release_manifest.json` `deploy.worker`). 이메일·푸시는 없다 | [specs/cargo-watch.md](specs/cargo-watch.md), [ADR 0019](adr/0019-watch-user-opt-in-limit.md) |
| MRN 대체 조회 | 세관에 아직 없는 화물은 MRN으로 해수부 입항 신고를 찾아 배 상태까지 답한다 | [specs/mrn-fallback.md](specs/mrn-fallback.md) |
| 통관 이력 원문 | UNI-PASS 처리 이력을 화면에 그대로 보여 준다(LLM에 주지 않음) | [specs/customs-detail.md](specs/customs-detail.md) |
| 내 화물 현황표 | 신용장별 묶음 표와 엑셀 받기(`/api/cargo/sheet`) | SDD 5.19 |
| 운영자 | 고객 목록·정지·삭제, 운영자 권한, 운영 지표(`/api/admin/*`, `/api/metrics`) | [specs/operator-admin.md](specs/operator-admin.md) |
| 토큰 한도 | 1명당 하루 LLM 토큰 한도(`.env.example` `DAILY_TOKENS_PER_USER=100000`), 넘으면 다음 요청부터 429 | [specs/token-quota.md](specs/token-quota.md), [ADR 0018](adr/0018-daily-token-quota.md) |
| 안내처 | 답하지 않는 부분은 누구에게 어디서 확인하는지 코드가 붙인다 | [specs/referral-guide.md](specs/referral-guide.md) |
| 화면 | 채팅, 지켜보는 화물 지도, 내 화물, 이력, 설정, 운영자, 지표, 소개 (Next.js) | [web/README.md](../web/README.md) |

**안 만드는 것:** 항공·육상 · 창고 수령일 예측 · 세액·통관 가부 판단(틀리면 사용자가 돈으로 다치는 영역, 통관은 단계 해설까지만) · 결제·다중 조직 · 군함 데이터

**확장 가능성(이번 범위 밖, 막힌 건 아님):** 부산 외 국내 항만(해수부 청 코드·기준 좌표·부두 Skill 교체) · 해외 항만(입항 실적 출처가 없어 별도 설계) · 대형 화주(다중 조직·ERP 연동)

**쓰지 않는 것:** LangGraph, RAG. 도메인 지식은 Skill 문서를 통째로 넣고, 실시간 데이터는 MCP 도구로 받는다([ADR 0003](adr/0003-no-rag-whole-skill-docs.md)).

## 5. 사용자 흐름

```
정상    채팅에 B/L(+ 판매 예정일, 선택) → 코드가 B/L을 [BL1]로 가림 → 채팅 에이전트가 화물 조회 도구 선택
        → UNI-PASS 조회(코드) → 선박 식별 → 위치·입항 예정·남은 거리(MCP 도구)
        → 1층 신호(코드) → 등급(코드 판정 표) → 설명·할 일·통관 해설(LLM) → 검증(코드)
        → 화면: 판정·할 일·위치·통관 해설·하역 장소·근거
되묻기  선명 "TEST PAN"(가상) 후보 3척, 서류 대조로도 확정 불가 → 판정 없이 "항차 번호나 포워더 ETA를 알려주세요"
        → 입력 후 식별 확정 → 정상 흐름
서류    서류 사진·PDF 올림 → 칸 추출 → 사용자가 확인 → 정상 흐름
실패    없는 B/L → "B/L 번호와 마스터·하우스 구분을 다시 확인" / ShipFinder 시간 초과 → 재시도 후 캐시 값으로 부분 응답, 마지막 확인 시각 표시
```

단계별 처리와 분기는 [SDD 4.1~4.7](Marvia_SDD.md)이 정본이다.

## 6. 설계

### 6.1 LLM이 하는 것 / 코드가 하는 것

| LLM | 코드 |
| --- | --- |
| 등급에 맞춘 이유·상충 해석·할 일 문장 | B/L 형식 검증, B/L 가리기, UNI-PASS 조회 |
| 회색 지대에서만 표 등급 이상으로 올리기 | 1층 신호 판정, 등급 판정 표 |
| 동명 선박 중 고르기(사용자가 항차·포워더 ETA를 준 경우만) | MRN → 호출부호 식별, 서류 대조 식별, MMSI 중복 시 최신 선택 |
| 통관 단계 풀어 설명, 후속 질문 답 | 여유 일수·freshness·거리 계산, 근거 카드 조립 |
| 채팅 에이전트의 도구 선택과 답, 서류 칸 채우기, 기억 뽑기 | 출력 검증, 재시도, 폴백, 주입 차단, 토큰 한도 |

### 6.2 판정 (2층)

**결론:** 등급은 코드 판정 표가 정한다. LLM은 등급을 가르는 신호를 모르는 회색 지대에서만 표 등급 이상으로 올릴 수 있고 낮출 수 없다. 처음 계획은 LLM이 등급을 정하는 것이었으나, LLM이 판정 표를 따르지 않는 문항이 있어 바꿨다([ADR 0001](adr/0001-verdict-by-code-table.md), `backend/app/services/judge/verdict.py`).

**1층 · 신호(코드):** 7종이고 각각 triggered·clear·unknown이다. 임계값은 `skills/ais-reliability/rules.md` 프론트매터에 있고 코드가 읽는다.

| 신호 | 켜지는 조건 |
| --- | --- |
| position_stale | 위치 갱신 6시간 넘게 끊김 |
| eta_conflict | AIS ETA와 해수부 입항 예정 12시간 넘게 차이 |
| anchor_wait | 부산 인근 0.5노트 이하로 24시간 이상 정지 |
| dest_changed | 목적지가 비었거나 부산이 아님 |
| navstat_mismatch | 항해상태와 속도 불일치 |
| customs_hold | 통관 검사 지정·보류 |
| sales_date_exceeded | 신뢰 ETA가 판매 예정일을 넘김(배가 정상이어도) |

**2층 · 등급(코드 판정 표, `skills/cargo-verdict/rules.md`):**

| 등급 | 조건 |
| --- | --- |
| 긴급 (act) | anchor_wait·customs_hold·sales_date_exceeded 중 하나라도 켜짐. 또는 다른 신호가 켜졌는데 여유가 2일 미만 |
| 주의 (watch) | 위 셋은 꺼져 있고 다른 신호가 하나라도 켜짐. 또는 켜진 신호가 없어도 여유가 2일 미만 |
| 순항 (fine) | 켜진 신호 없음. unknown은 켜진 것으로 세지 않는다 |
| 판정 보류 | 선박 식별 불확정, 위치 없음, 판매 예정일을 줬는데 믿을 도착일이 없음 → LLM 없이 물을 것 1개 이상 |

- 세지 않는 신호: navstat_mismatch, 깨지거나 빈 목적지. 배 상태가 아니라 AIS 입력 오류일 수 있어서다.
- 회색 지대: anchor_wait·customs_hold가 unknown이면 표가 등급을 낮게 낼 수 있어 이때만 LLM이 올린다.
- 판매 예정일이 없으면 여유 조건은 보지 않고 배 상태만으로 정한다.

**울타리(코드가 LLM을 막는 것), 대표 4개:** stale이면 "현재 위치" 표현 금지 / act·watch면 1층 규칙 이름 필수 / 식별 uncertain이면 판정 금지 / 근거에 없는 숫자 거부. 전체 V1~V15는 [SDD 5.7](Marvia_SDD.md).

### 6.3 아키텍처

```
사용자 → Next.js (Railway marvia-web)
       → FastAPI (Railway marvia-api): /api/chat · /api/chat/stream · /api/agent · /api/document · /mcp(토큰 인증) · /health
   FastAPI ─ UNI-PASS 직접 조회(코드)
          ├ services/llm.py (LLM 호출 단일 지점, Skill 통째 주입) ─ OpenRouter google/gemini-3.5-flash-lite
          ├ /mcp (FastMCP, 같은 서버) ─ ShipFinder · 해수부(서울 Cloud Run 릴레이 mof-relay 경유) · searoute
          ├ Supabase (Postgres, 로그인)
          └ Langfuse (트레이스 · 프롬프트 버전 · 평가셋)
```

- 배포 서버는 실제 외부 API를 부른다(`REPLAY_MODE=false`). 키 없는 재현·평가는 재생 모드로 한다([ADR 0008](adr/0008-replay-mode-keyless.md), [ADR 0010](adr/0010-deployed-server-real-mode.md)).
- 배포 위치는 [ADR 0009](adr/0009-deploy-railway-not-vercel.md), 해수부 릴레이는 [ADR 0011](adr/0011-mof-seoul-relay.md), 서비스 모델은 [ADR 0012](adr/0012-service-model-gemini-flash-lite.md). 배포 주소와 버전은 [release_manifest.json](release_manifest.json).
- B/L 원문은 LLM에 넘기지 않고(숫자 오기·주입 방지) 트레이스에서 가린다. 판정에 필요 없는 UNI-PASS 필드도 넘기지 않는다. 필드별 처리는 [SDD 3.5](Marvia_SDD.md), [ADR 0005](adr/0005-bl-masking-not-to-llm.md).
- 라우터·UI는 LLM SDK를 직접 import하지 않는다([ADR 0002](adr/0002-llm-sdk-only-in-llm-py.md)).
- 컴포넌트와 배포 도식 전체는 [SDD 2.1·2.2](Marvia_SDD.md).

### 6.4 Skill (시스템 프롬프트에 통째로, RAG 아님)

6개다(`skills/`). 넣는 곳은 `backend/app/services/llm.py`의 Skill 묶음이 정한다.

| 폴더 | 내용 | 넣는 곳 |
| --- | --- | --- |
| `skills/ais-reliability/` | AIS 신뢰도 규칙, 1층 신호 정의와 임계값, 상충 시 우선순위 | 판정, 선박 고르기, 후속 질문, 채팅 |
| `skills/customs-stages/` | 유니패스 단계 용어·순서·단계별 할 일·관세사 확인 기준 | 판정, 후속 질문, 채팅 (평가 채점도) |
| `skills/port-busan/` | 부산항 부두·정박지, 하역 장소 안내 문장 규칙 | 후속 질문, 채팅 |
| `skills/cargo-verdict/` | 등급 판정 표(코드가 읽음), 등급·되묻기 설명법 | 판정, 후속 질문, 채팅 |
| `skills/import-basics/` | 수입 실무 기초(B/L 번호 찾기, 도착통지서, 반출 절차 등). 웹 검색 대신 고정 문서로 답한다([ADR 0020](adr/0020-remove-web-search-use-skill.md)) | 후속 질문, 채팅 (판정에는 없음) |
| `skills/referrals/` | 안내처 표 | LLM에 넣지 않고 코드가 문장에 붙인다 |

AIS 신뢰도 규칙(ShipFinder 실제 응답에서 확인): MMSI 중복(IMO 하나에 MMSI 2개 → 최신 선택) · 동명 선박(한 선명에 국적·선종이 다른 배가 섞임 → 선명만으로 확정 금지) · 53일 전 위치를 정상으로 반환 → 6시간 초과면 "마지막 수신 위치" · 깨진 목적지 문자열 → 해수부로 교차검증 · 항해상태 "항해 중"인데 속도 0 → 속도·위치로 판단.

**상충 우선순위:** 해수부 관제 실적 > 해수부 입항 예정 > AIS ETA > AIS 목적지 문자열(`skills/ais-reliability/rules.md` `priority`). AIS 목적지·ETA는 사람이 손으로 넣는 값이라 가장 자주 틀린다.

**신뢰 경계:** 도구 응답·외부 문자열(특히 AIS dest)·사용자 입력은 데이터로만 취급하고 지시로 읽지 않는다. 지시는 시스템 프롬프트와 Skill 문서에서만 온다([SDD 7](Marvia_SDD.md)).

### 6.5 MCP 서버 (FastMCP, `/mcp` Streamable HTTP)

도구 4개, 모두 읽기 전용이다(`mcp_server/server.py`). 입력·출력 스키마는 [SDD 3.4](Marvia_SDD.md), 연결법은 [mcp_server/README.md](../mcp_server/README.md).

| 도구 | 하는 일 | 뒤에 있는 API |
| --- | --- | --- |
| `get_vessel_candidates` | 선명으로 선박 후보 목록 | ShipFinder |
| `get_live_position` | MMSI로 위치·속도·항해상태·목적지·AIS ETA·freshness | ShipFinder |
| `get_port_schedule` | 부산항 입항 예정·실적, 접안 시설 | 해수부 공공데이터 |
| `estimate_distance` | 부산항까지 남은 해리 | searoute |

모든 도구는 원본 값과 조회 시각을 함께 돌려준다. 서비스도 외부 MCP 클라이언트와 같은 `/mcp`로 도구를 부른다([ADR 0006](adr/0006-mcp-server-for-external-data.md)). UNI-PASS는 MCP 도구가 아니라 FastAPI 서비스 계층에서 코드가 직접 부른다.

**선박 식별 순서(코드 먼저):** B/L의 MRN → 해수부 입항 신고 → 호출부호로 확정 → 안 되면 선명 검색. 후보 1척이면 코드가 확정한다. 2척 이상이면 서류 대조(세관 입항일·적재항과 해수부 신고)로 1척일 때만 확정하고, 사용자가 항차·포워더 ETA를 줬을 때만 LLM이 고른다. 근거 없이는 확정하지 않고 되묻는다([ADR 0015](adr/0015-same-name-vessel-needs-user-evidence.md), SDD 5.5).

**채팅 에이전트 도구:** 자체 도구 7개(check_cargo, ask_cargo, search_arrivals, set_watch, watch_vessel, send_kakao, recall_memo, `backend/app/services/chat/tools.py` `AGENT_TOOLS`)와 위 MCP 도구를 받는다. 웹 검색 도구는 없다([ADR 0020](adr/0020-remove-web-search-use-skill.md)).

### 6.6 들어가는 API

| API | 용도 | 제약 |
| --- | --- | --- |
| **ShipFinder** VesselSearch · VesselPositionSingle | 선박 검색, 실시간 위치·ETA | 스타터 키. 영역 조회·입항 예정은 권한 없음(status 21)이라 설계에서 뺐다. 빈도 초과(23·29)·한도 소진(38)은 캐시 값으로 답한다(SDD 5.2) |
| **UNI-PASS** 화물통관진행정보 | B/L → 선명·국적·입항 예정·통관 단계·장치장·MRN | IMO·호출부호가 없어 MRN·선명·국적·입항 예정으로 배를 잇는다 |
| **해수부** 관제정보 · 선박운항정보 | 입항 예정·실적, 접안 시설, 입항 신고(MRN) | 배포 서버는 서울 릴레이를 거친다(SDD 6.7) |
| **searoute** | 남은 해상 거리 | 라이브러리 |
| OpenRouter / Langfuse | LLM 호출 / 트레이스·프롬프트·평가셋 | 키 목록은 `.env.example` |

**이용 조건:** ShipFinder는 데이터를 내부 연구 목적으로만 쓰고 서면 동의 없이 복사·게시를 금지한다(www.shipfinder.com/Home/Treaty). UNI-PASS는 조회 정보의 복제·타인 제공을 금지한다(이용약관 15조③). 해수부 두 API는 이용허락범위 제한이 없다. searoute는 Apache-2.0이고, 내장 항로 데이터 원본은 Eurostat SeaRoute(EUPL-1.2)라 출처를 고지한다([README 데이터 출처와 라이선스](../README.md)). 그래서 실제 API 응답은 DB(내부)에만 두고 레포의 fixture·데모는 가공값으로 만든다. 보안 처리는 [SDD 7.3](Marvia_SDD.md).

## 7. 출력 계약과 실패 경로

**스키마(Pydantic):** 주요 필드는 `status`(ok/partial/insufficient/failed/unsupported) · `verdict`(fine/watch/act/null) · `vessel_match`(confirmed/uncertain/none) · `missing_inputs` · `reasons`(1층 규칙 이름+값) · `conflicts`(상충 쌍과 선택 이유) · `actions` · `days_margin`(코드 계산, LLM 덮어쓰기 금지) · `evidence`(출처·원본·조회 시각) · `answer`. 전체 필드는 [SDD 3.2](Marvia_SDD.md).

**검증 규칙:** LLM 출력을 코드가 검사하고 어기면 다시 묻는다. 처음 계획한 7종(stale이면 "현재 위치" 금지 / act·watch면 reasons 필수 / eta 있으면 evidence 필수 / uncertain이면 verdict 금지 / insufficient면 missing_inputs 필수 / conflicts 출처는 evidence에 있어야 / answer 숫자는 evidence에 있어야)에 등급 검사, 주입 방어, 통관 진행 평가 금지 등이 더해져 V1~V15다([SDD 5.7](Marvia_SDD.md), [ADR 0007](adr/0007-validation-retry-partial-fallback.md)). 모델을 바꾸면 위반율이 달라지므로 모델 비교가 의미를 가진다.

**재시도 3단계:** 오류 붙여 재요청 → 엄격 프롬프트로 재요청 → 폴백(status partial, 판정 표 등급 + 고정 문구). 재시도는 트레이스에 남긴다. failed는 UNI-PASS 조회 자체가 실패했을 때만 쓴다.

| 실패 | 대응 |
| --- | --- |
| 외부 API 시간 초과·5xx | 재시도 2회(총 3번 시도, `backend/app/clients/retry.py`), 최종 실패 시 partial. UNI-PASS 장애면 failed |
| ShipFinder 21 / 23·29 / 38 | 해당 근거 없이 부분 응답 / 캐시 값 + 캐시 시각 표시 / 캐시 값 또는 "내일 다시 조회" 안내 |
| 선박 식별 불확정 | insufficient, 후보와 물을 것 표시, 판정 없음 |
| LLM 스키마·검증 위반 | 3단계 재시도 후 폴백 |
| LLM 429·과부하 | 호출당 1회 재시도. 다른 모델로 바꾸지 않는다 |
| 사용량 남용 | 로그인 필수 + 1명당 하루 토큰 한도(429). 요청당·금액 상한은 없다([ADR 0018](adr/0018-daily-token-quota.md)) |
| 주입·범위 밖 입력 / 없는 B/L / 부산 외 항만 | B/L 형식 검증, 주입 모양이면 LLM 없이 고정 안내, 도구 응답 속 지시 무시 / 재입력 안내 / unsupported |

상황별 전체 표는 [SDD 8](Marvia_SDD.md).

## 8. 평가

결과 숫자는 [EVAL_REPORT](../EVAL_REPORT.md)가 정본이다. 이 절은 무엇을 어떻게 재는지만 적는다.

**데이터:** 수집 워커(`worker/`)가 해수부 입항 신고와 부산 입항 선박의 ShipFinder 위치를 DB에 모은다(추적 대상 최대 12척 `worker/collector.py` `MAX_TARGETS`, 켜면 6시간마다 `worker/run.py`). 배포 worker는 스케줄이 꺼져 있다(`docs/release_manifest.json` `deploy.worker`). 라벨링은 실제 수집 스냅샷을 보고 하고, B/L·통관 단계·판매 예정일은 가상이다. 레포 `evals/dataset.jsonl`과 Langfuse Dataset `marvia-golden-30`에 넣은 fixture는 좌표·시각을 옮긴 가공값이다(6.6 이용 조건).

**정답 기준 둘:** ① 판정 정확도 = 판정 시점 스냅샷을 보고 AIS 판독 경험자가 정한 verdict·insufficient(모델 출력 보기 전에 확정) ② 예측 적중 = 실제 입항이 신뢰 ETA보다 12시간 넘게 늦었는가. ②는 필드(`actual_arrival`)만 있고 30건 모두 비어 있어 재지 않았다(`evals/dataset.jsonl`).

**판정자 배정:** 30건 초안은 팀원 한 명이 쓴다. 경계 14건의 정답은 AIS 판독 경험자가 정하고, 정상 8건·실패 8건은 초안을 그가 검수한다. 문항마다 판정자·사유·날짜를 남기고(`labeler`, `label_reason`, `labeled_at`), 이견은 지우지 않고 기록한다. 필드 설명은 [evals/README.md](../evals/README.md).

**평가셋 30건** (`evals/dataset.jsonl` `category`, 판정형 `edge_verdict` · 보류형 `edge_insufficient`):

| 구분 | 건수 | 내용 |
| --- | --- | --- |
| 정상 | 8 | 실시간 수신, ETA 근거 일치. fine 4, 여유 부족으로 act 4 |
| 경계 | 14 | 판정형 9(B02~B06, B08~B11): 신호 상충 4(B03~B06), 위치 오래됨 1, 정박 대기 1, 목적지 변경 1, 통관 검사 1, MMSI 중복 1 / 보류형 5(B01, B07, B12~B14): 동명 선박 2, 상충 후 식별 재검토 1(B07), 위치 없음 1, 식별 근거 부족 1 |
| 실패 유도 | 8 | 없는 B/L, 시간 초과, 권한 없음, 부산 외 항만, LLM 계약 위반 지속(partial), 주입 3(사용자 입력, AIS dest, MCP 도구 설명) |

verdict 정답이 있는 문항 22건, 그중 act 11건(`evals/dataset.jsonl` `expected_verdict`). 판정형은 상충 해석을, 보류형은 되묻기를 잰다.

**신호 상충 5건** (B03~B07. B07은 식별 재검토로 끝나 보류형에 센다):

| # | 문항 | 상충 구성 | 정답 |
| --- | --- | --- | --- |
| 1 | B05 | AIS ETA와 해수부 예정 12시간+ 차이, 정상 항해 중 | 해수부를 믿고 여유 일수로 watch |
| 2 | B04 | AIS ETA 내일, 20시간 정지(문턱 24시간 미달), 해수부 모레 | 문턱 아래 신호를 합쳐 AIS ETA를 버림. act |
| 3 | B03 | 목적지 깨짐, 해수부엔 부산 예정, 위치·속도 정상 | 깨진 값 무시, fine |
| 4 | B06 | 항해상태 "정박"인데 12노트로 이동 중 | 상태값 버리고 관측값으로 fine |
| 5 | B07 | 위치 신선한데 해수부 실적엔 이미 입항 | 다른 배(MMSI 잔존) 의심 → 식별 재검토, 확정 못 하면 insufficient |

처음에는 이 5건에서 (a)와 (b)가 갈리는 만큼을 LLM 기여로 보려 했다. 등급을 코드 판정 표가 정하게 바꾸면서 (a)도 같은 표를 쓰므로(`evals/baseline_rules.py`) 등급 정확도로는 LLM 기여가 갈리지 않는다. 이 해석은 [EVAL_REPORT 3-1, 4절](../EVAL_REPORT.md)에 있다.

**평가 축:** verdict_accuracy · act_recall · insufficient_precision(정보 부족인데 확정 / 충분한데 보류) · vessel_match_accuracy(오확정 건수) · customs_explanation(LLM-as-judge, 생성 모델과 다른 채점 모델 + 사람 대조 5건, [EVAL_REPORT 3-1](../EVAL_REPORT.md)) · grounded(수치가 근거와 일치) · schema_pass(검증 통과율). EVAL_REPORT는 이 지표에 주입 오작동·지연·비용을 더해 측정 축 6개로 묶는다([EVAL_REPORT 3절](../EVAL_REPORT.md)).

**비교 구성** (`python -m evals.run_eval --config a|b|c`): (a) 규칙만(서비스와 같은 판정 표, 식별은 유사도 최고 후보) / (b) 규칙 + 서비스 모델(`LLM_MODEL`) / (c) 규칙 + 비교 모델(`EVAL_COMPARE_MODEL`). 같은 30건, 같은 프롬프트·파라미터. 개선 실험은 한 번에 하나만 바꾸고 재측정하며, 효과 없던 시도도 기록한다([EVAL_REPORT 4·5절](../EVAL_REPORT.md)).

**출시 게이트(하나라도 걸리면 배포 안 함):** act 누락 1건+ · 식별 오확정 1건+ · 스키마 통과 95% 미만 · 주입 오작동 1건+ · p95 지연·요청당 비용 상한 초과. 앞의 넷은 결과 파일 `summary.gates`가 판정하고, 지연·비용 상한 값과 결과는 [EVAL_REPORT 7절](../EVAL_REPORT.md).

## 9. 일정과 제출물

| 기간 | 끝낼 것 |
| --- | --- |
| 9/22~9/27 | 키 발급, 수집 워커, 골격(FastAPI·Dockerfile·/health), MCP 뼈대, Langfuse 연결, Skill 초안 |
| 9/28~10/2 | 본 구현(UNI-PASS 연동, MCP, Skill, services/llm.py, 출력 계약, Docker, Langfuse). 10/1까지 베이스라인 (a) |
| 9/30 | 중간 점검: 문제 정의·평가셋·아키텍처·뺀 기능·(a) 1차 숫자 |
| 10/6~8 | 평가 (a)(b)(c), 프롬프트 재측정, EVAL_REPORT, Next.js UI, 데모 영상. 10/8 자정 코드 동결 |
| 10/9~11 | 발표 자료. 코드 수정 없음 |
| 10/12 | 발표, 배포 URL 유지 |

팀은 2명이고 둘 다 풀스택이다. 작업 단위는 [개발 작업 리스트](Marvia_개발_작업_리스트.md)에 있다. Skill 판정 기준 검수와 라벨 확정은 AIS 판독 경험자가 맡는다.

**제출물:**

| 항목 | 위치 |
| --- | --- |
| GitHub 레포 (KDT 7기 org) | 레포 루트, 키 목록은 `.env.example` |
| 화면 URL (정상·되묻기·실패 흐름) | Railway `marvia-web`, 주소는 [release_manifest.json](release_manifest.json) |
| API (/health, /api/agent, /api/chat) | Railway `marvia-api`, 주소는 [release_manifest.json](release_manifest.json) |
| README (한 줄 정의, 지표 표, compose up, 10분 재현) | [README.md](../README.md) |
| Skill | [skills/](../skills/README.md) |
| MCP 서버 (연결법·tool 목록·호출 결과·접근 제어) | [mcp_server/README.md](../mcp_server/README.md), `docs/evidence/mcp-02-deployed-tools.txt` |
| EVAL_REPORT (평가셋, 베이스라인, 전후 지표, 실패 사례, 검증 과정) | [EVAL_REPORT.md](../EVAL_REPORT.md) |
| Langfuse 스크린샷 3장 이상 | `docs/evidence/` |
| 데모 영상(정상 1, 실패 1, 되묻기 1) · 발표 PDF | EVAL_REPORT 머리 표 |

## 10. 발표 질문과 약점

| 질문 | 답 |
| --- | --- |
| 누가 막혀 있나 | 2절 |
| 트레드링스와 뭐가 다른가 | 3절 비교표, 되묻기 장면 |
| LLM은 왜 필요한가 | 6.1 역할표. 등급은 코드가 정하고, LLM은 상충 해석 설명·통관 해설·회색 지대·채팅 에이전트를 맡는다([EVAL_REPORT 4절](../EVAL_REPORT.md) 4번) |
| 안 만든 것 | 4절 |
| 모델 선택 근거 | [EVAL_REPORT 5절](../EVAL_REPORT.md), [ADR 0012](adr/0012-service-model-gemini-flash-lite.md) |
| 스키마를 어기면 | 7절 재시도 3단계·폴백 |
| 평가셋·라벨 출처 | 실제 선박 수집 + 하정운과 수입 실무자가 적고 확정 |
| 가장 큰 약점 | 아래 |

**한계:** 사용자 인터뷰를 하지 않았다 · 트레드링스 실제 화면은 확인하지 못했다(3절) · 통관 단계·판매 예정일은 모의 데이터다 · ShipFinder 스타터 키에 기댄다 · 원양 구간 위치 공백이 있다. 측정에서 드러난 약점은 [EVAL_REPORT 8절](../EVAL_REPORT.md).

### 처음 계획과 달라진 점

처음 계획은 `git show 8975578:docs/Marvia_PRD.md`다. 제품 수준의 변경만 적는다. 폴더·파일·환경변수 같은 구현 수준 변경은 [SDD 계획 대비 변경](Marvia_SDD.md) 표에 있다.

| 항목 | 처음 | 지금 | 이유/근거 |
| --- | --- | --- | --- |
| 등급 이름 | 괜찮음 / 지켜볼 것 / 지금 조치 | 순항 / 주의 / 긴급 (코드 값 fine/watch/act는 그대로) | `backend/app/services/judge/verdict.py` `VERDICT_LABEL` |
| 등급 결정 | 2층 LLM이 판정 | 코드 판정 표가 정하고 LLM은 회색 지대에서 올리기만 | [ADR 0001](adr/0001-verdict-by-code-table.md), EVAL_REPORT 4절 1번 |
| 1층 신호 | 6종 | 7종(sales_date_exceeded 추가) | `skills/ais-reliability/rules.md` |
| 입력 창구 | B/L + 판매 예정일 폼, `POST /api/agent` | 채팅 한 줄(`/api/chat`), 판매 예정일 선택. `/api/agent`는 평가·데모·칸 입력용 | [ADR 0016](adr/0016-chat-agent-with-tools-and-guard.md), SDD 4.5 |
| 동명 선박 식별 | 후보 2척 이상이면 LLM이 판단 | MRN·서류 대조를 코드가 먼저, LLM은 사용자가 항차·포워더 ETA를 줬을 때만 | [ADR 0015](adr/0015-same-name-vessel-needs-user-evidence.md) |
| 검증 규칙 | 7종 | V1~V15 | [ADR 0007](adr/0007-validation-retry-partial-fallback.md), SDD 5.7 |
| 재시도 끝 폴백 | status failed | status partial, 판정 표 등급 + 고정 문구 | [ADR 0007](adr/0007-validation-retry-partial-fallback.md) |
| 배포 | Vercel(web) + Cloud Run(api) | Railway `marvia-web` + `marvia-api` | [ADR 0009](adr/0009-deploy-railway-not-vercel.md) |
| 배포 서버 모드 | 처음 PRD에는 없었고 첫 배포는 재생 모드(`REPLAY_MODE=true`) | 실제 모드(`REPLAY_MODE=false`). 재생 모드는 키 없는 재현·평가용 | [ADR 0008](adr/0008-replay-mode-keyless.md), [ADR 0010](adr/0010-deployed-server-real-mode.md) |
| 해수부 호출 | 직접 호출 | 서울 Cloud Run 릴레이 `mof-relay` 경유 | [ADR 0011](adr/0011-mof-seoul-relay.md) |
| 서비스 모델 | OpenRouter 모델 A·B 비교 후 선정 | `google/gemini-3.5-flash-lite` (이전 `openai/gpt-4o-mini`) | [ADR 0012](adr/0012-service-model-gemini-flash-lite.md), EVAL_REPORT 5절 |
| Skill | 3개 | 6개(cargo-verdict, referrals, import-basics 추가) | [ADR 0001](adr/0001-verdict-by-code-table.md), [ADR 0020](adr/0020-remove-web-search-use-skill.md), [specs/referral-guide.md](specs/referral-guide.md) |
| 서류 추출 | P1(가산) | 구현(사진·PDF) | [specs/document-extract.md](specs/document-extract.md) |
| 카카오톡 알림 | P1 "판정 변화 시 알림" | 사용자가 켠 화물 지켜보기 + "나에게 보내기". 자동 재판정은 배포에서 꺼짐 | [ADR 0019](adr/0019-watch-user-opt-in-limit.md), [specs/cargo-watch.md](specs/cargo-watch.md) |
| 로그인·기억·운영자·토큰 한도·현황표 | 계획에 없음 | 만듦(4절 표) | [ADR 0017](adr/0017-memory-feature-decisions.md), [ADR 0018](adr/0018-daily-token-quota.md), `docs/specs/` |
| 품명·컨테이너 번호 | 품명은 LLM에 넘기지 않음 | 품명은 채팅 에이전트에만, 판정 LLM에는 없음. 컨테이너 번호는 `[CNTR1]` 같은 가린 표시로만 | SDD 3.5, [ADR 0005](adr/0005-bl-masking-not-to-llm.md) |
| 비용·레이트 리밋 방어 | 다른 모델 라우팅, 요청·일일 상한 차단 | 로그인 + 1명당 하루 토큰 한도(429). 모델 교체·금액 상한 없음 | [ADR 0018](adr/0018-daily-token-quota.md), SDD 8 |
| 수집 대상 | 20~30척, 3~6시간마다 | 최대 12척, 6시간마다, 배포 worker 스케줄 꺼짐 | `worker/collector.py`, `worker/run.py`, `release_manifest.json` |
| 실패 유도 문항 | 주입 2(사용자 입력, AIS dest), 범위 밖 | 주입 3(+ MCP 도구 설명), 부산 외 항만, LLM 계약 위반 지속 | `evals/dataset.jsonl` |
| 베이스라인 (a) | 1층 결과를 verdict로 | 서비스와 같은 판정 표 | `evals/baseline_rules.py` |
