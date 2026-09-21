# SDD · Converge 구현 명세

버전 2.2 · 2026.09.17 · 5조 김승욱, 하정운 · 도메인: 현장이 움직이는 유지보수·배포 작업의 집결 조율 (함정 정비 / SI 배포)

이 문서는 코드를 쓰는 사람과 Claude Code가 따르는 기준이다. 여기 없는 결정은 만들지 말고 물어본다. 스키마·엔드포인트·규칙값을 바꾸려면 이 문서를 먼저 고친다.

---

## 1. 폴더 구조

2026-09-17 갱신. 하정운·김승욱 합의분 반영 (domain 분리, GGUF 빌드 시 다운로드, 소개 페이지, 증거물 폴더).

```
proj2-5/
  CLAUDE.md                   AI 진입점. 언제 무엇을 열지
  CONVERGE.md                 구조 지도. 폴더별 책임과 SDD 절 안내
  AGENTS.md                   CLAUDE.md를 따른다 (Codex·Cursor용)
  README.md                   채점자용. 소개, 실행법, 배포 URL
  EVAL_REPORT.md              제출물. 스캐폴딩 자리(루트) 유지
  Dockerfile                  루트. 빌드 컨텍스트가 skills/, mcp_server/를 포함해야 하므로
                              빌드 시 HF에서 GGUF를 받아 이미지에 넣는다 (git, LFS 미사용).
                              받는 파일: kimseunguk/converge-slot-extractor 의 kanana_2.1b-Q4_K_M.gguf
                              (1.30 GiB, 검증 40건 Exact Match 85.0%. 공개 저장소라 토큰 없이 받는다)
  docker-compose.yml          api + db(postgres:16). backend/db/를 initdb에 마운트, db healthcheck 후 api 기동
  .env.example                backend용 (9절)
  docs/
    PRD.md  SDD.md  테이블정의서.md
    evidence/                 제출 증거물
      langfuse/               대시보드 스크린샷 3장 이상, 트레이스 상세 1장
      mcp/                    연결 스크린샷, tool 목록, 호출 결과
    planning/                 계획서 보완 제출본 (proj2-5_계획보완.md)
    SCAFFOLD.md  specs/       강사 스캐폴딩. specs/는 쓰지 않는다 (SDD가 그 역할)
  backend/                    FastAPI (Cloud Run)
    BACKEND_GUIDE.md          이 폴더의 경계와 지킬 것
    app/
      main.py                 앱 생성, 라우터 등록, 미들웨어(request_id), /mcp 마운트
      routers/
        agent.py              POST /api/agent
        health.py             GET /health
        session.py            GET /api/session/{id}  (공유 링크용 읽기, 로그인 필수)
                              DELETE /api/session/{id}  (주선자 본인만, 즉시 삭제)
                              PATCH /api/session/{id}/participants  (핀 claim·위치 수정. 2절, 7절 핀 소유권)
        internal.py           POST /internal/cleanup (Cloud Scheduler 전용, 토큰)
      schemas/
        slots.py              슬롯 추출 결과 (LLM 출력 계약 1)
        result.py             최종 결과 (LLM 출력 계약 2, API 응답)
        request.py            API 요청
      services/               바깥과 통신하는 것만 둔다
        llm.py                모든 LLM 호출은 여기만. OpenRouter + 로컬 GGUF
        vision.py             캡처 → 텍스트
        geo.py                지오코딩·장소 검색 (MCP 클라이언트 경유)
        routes.py             경로·소요시간 (MCP 클라이언트 경유), 캐시
        transit_schedule.py   첫차·막차 (서울 열린데이터광장, 역명→역코드→시각표. 부산은 승인 뒤)
        judge.py              후보 판정 프롬프트 조립, 대형 모델 호출
        pipeline.py           단계 오케스트레이션 (루프 없음, 순차)
        store.py              Postgres 접근(asyncpg, DATABASE_URL), 암호화, expires_at 계산
        auth.py               Supabase 공개키(JWKS)로 JWT 검증 → user_id. 로그인 필수 엔드포인트의 의존성
      domain/                 계산만. 네트워크·LLM 호출 없음. API 키 없이 테스트된다
        CLAUDE.md             난간. 이 폴더 파일을 열면 자동 로드
        rules.py              Skill 규칙 로드, 계산식 (절차 소요·여유·역산·전환 조건)
        router.py             소형/대형 선택 규칙
      observability/
        langfuse.py           트레이스·span·프롬프트 조회
      models/                 kanana_2.1b-Q4_K_M.gguf 자리. 빌드 시 채워짐. git에 없음
    db/
      001_init.sql          테이블정의서.md의 표 5개. 로컬(compose initdb)과 Supabase(SQL Editor)에 같은 파일을 실행
    tests/
      TEST_GUIDE.md
      fixtures/               spike 샘플 응답 (실제 API 응답 원문)
    requirements.txt
  mcp_server/                 FastMCP. backend/app/main.py에 ASGI로 마운트해 같은 프로세스에서 /mcp 제공
    MCP_GUIDE.md
    server.py                 FastMCP 인스턴스, Bearer 토큰
    tools/
      geocode.py  search_places.py  route_car.py  route_transit.py  first_last_train.py  vessel_schedule.py  departure_calc.py
  frontend/                   Next.js (Vercel)
    FRONTEND_GUIDE.md
    .env.example              frontend용 (9절). 브라우저에 노출되는 값만
    package.json  tsconfig.json       Next 16, React 19, TypeScript. 지도 외 UI 라이브러리 없음
    next.config.ts            agentRules: false (next dev 가 이 폴더에 AGENTS.md·CLAUDE.md 를 만들지 않게)
    app/
      layout.tsx              html/body, 전역 CSS 로드
      globals.css             전역 스타일. 핀 커서 규칙(핀 소유권)도 여기
      page.tsx                지도 + 채팅
      about/page.tsx          소개 페이지 (필수 조건 6, 서비스 화면과 별도)
      s/[id]/page.tsx         공유 링크 페이지. 링크는 이 주소 그대로(별도 토큰·단축 없음), 로그인 필요
      api/agent/route.ts      Cloud Run 프록시 (키 숨김)
      api/session/[id]/route.ts               GET 프록시 (공유 링크)
      api/session/[id]/participants/route.ts  PATCH 프록시 (핀 claim·위치 수정)
    components/
      MapView.tsx  ChatPanel.tsx  ParticipantPins.tsx  RouteLines.tsx  ResultTable.tsx  AuthGate.tsx  Progress.tsx
    lib/
      kakao.ts                지도 SDK 로더
      auth.ts                 구글 로그인(Supabase Auth), 토큰 헤더
      proxy.ts                app/api/ 라우트 공용 백엔드 전달
      dev-user.ts             로컬 모드 사용자 id
      mock.ts                 NEXT_PUBLIC_API_BASE 가 없을 때 프록시가 돌려주는 고정 응답
      mock-data.json          mock 시나리오(함정·SI)와 실제 경로 좌표
      api-types.ts            backend/app/schemas/에서 생성. 손으로 고치지 않는다
    types/
      agent.ts                2·3·4절 타입을 손으로 옮긴 것. api-types.ts 가 생기면 대체한다
  skills/converge/
    SKILL.md
    rules/  access.md  schedule.md  convention.md  transport.md  vendor.md
    presets/  ship_maintenance.md  si_deploy.md
    failures.md
    output-contract.md
  evals/
    EVAL_GUIDE.md
    dataset.jsonl             30건
    run_eval.py               Langfuse Dataset 실행·score 기록
  finetune/                   학습 파이프라인
    FINETUNE_GUIDE.md
    data/                     finetune_dataset.jsonl
    gen_dataset.py
  scripts/
    gen_types.sh              schemas/ → frontend/lib/api-types.ts. CI가 어긋남을 검사
    fetch_mock_routes.py      프론트 mock 경로를 카카오모빌리티·TMAP 에서 한 번 받아 저장
    mcp_check.py              /mcp 에 MCP 클라이언트로 붙어 도구 목록·호출 결과를 찍는다. 컨테이너 안에서 stdin 으로 실행
```

---

## 2. 엔드포인트

서비스 전체가 구글 로그인 뒤에 있다. 공유 링크로 결과를 보는 사람도 로그인해야 하고, 익명 열람 경로는 없다.

| 엔드포인트 | 인증 |
|---|---|
| POST /api/agent | 로그인 필수 |
| GET /api/session/{id} | 로그인 필수. 링크만으로는 열람 불가 |
| DELETE /api/session/{id} | 로그인 필수 |
| PATCH /api/session/{id}/participants | 로그인 필수 |
| GET /health | 인증 없음 |
| /mcp | Bearer 토큰 (MCP_TOKEN, 로그인과 별개) |

로그인 필수 엔드포인트는 토큰이 없거나 검증에 실패하면 401. AUTH_REQUIRED=false(9절, 로컬 채점용)일 때만 검증을 건너뛴다.

### POST /api/agent

**로그인 필수.** 헤더 `Authorization: Bearer {Supabase access token}`. services/auth.py가 Supabase 공개키(ES256, jwks.json)로 서명을 검증해 user_id를 꺼낸다. 비밀값을 우리 쪽에 두지 않는다. 없거나 틀리면 401. LLM을 호출하지 않는다 (비용 방어).

요청 (backend/app/schemas/request.py)

```python
class AgentRequest(BaseModel):
    session_id: str | None          # 재질문이면 기존 세션
    text: str | None                # 문장 입력
    image_base64: str | None        # 카톡 캡처 (jpeg/png)
    preset: Literal["ship_maintenance", "si_deploy"] | None   # 사용자가 고른 경우
    confirmed_participants: list[ParticipantInput] | None  # 핀 확인 단계에서 수정한 좌표
```

user_id는 본문이 아니라 토큰에서 나온다. Langfuse user_id도 같은 값.

text와 image_base64 중 하나는 필수. confirmed_participants가 오면 슬롯 추출을 건너뛰고 계산부터 시작한다.

응답 (backend/app/schemas/result.py)

```python
class AgentResponse(BaseModel):
    session_id: str
    stage: Literal["need_confirm", "need_info", "done", "out_of_scope", "failed"]
    slots: Slots | None             # 추출·확정된 슬롯. 추출 전에 끊기면 None (failed, need_info 만)
    result: Result | None           # stage == done 일 때
    questions: list[str]            # need_info 일 때 되물을 것
    message: str                    # 화면에 보여줄 한 줄
    trace_id: str
    geocoded: list[GeocodedPin] | None   # need_confirm, done 일 때 지도에 찍을 좌표

class GeocodedPin(BaseModel):
    name: str
    lng: float
    lat: float
    confidence: float
    kind: Literal["participant", "rendezvous", "destination", "pickup"]

class ParticipantInput(BaseModel):   # PATCH 요청에서 claim 만 뺀 모양
    name: str
    lng: float
    lat: float
```

좌표는 Slots 에 넣지 않는다 (슬롯 계약과 파인튜닝 데이터를 지키기 위해). 지오코딩 결과는 geocoded 로만 나간다. need_confirm 과 done 양쪽에 담는다. done 에서도 집결 후보 외에 참석자 출발 핀을 찍어야 하기 때문이다.

- need_confirm: 참석자 핀을 지도에 찍고 사용자 확인 대기 (확신도 < 0.8 또는 되묻기 없음)
- need_info: 필수 슬롯 누락 (출발지·이동수단·시각 중 하나). questions에 무엇을 물을지
- done: 후보와 참석자별 결과
- out_of_scope: 실시간 상황 등 범위 밖
- failed: 재시도 후에도 실패. result 없이 후보 핀만 있으면 result.candidates에 rank 없이 담는다. 지오코딩까지 갔으면 geocoded 도 함께 보낸다 (화면이 어디까지 됐는지 보여준다)

### GET /health

로그인 없음. `{"status":"ok","model_loaded":true,"version":"..."}`

### PATCH /api/session/{id}/participants

**로그인 필수.** 참석자가 자기 핀을 고르거나(claim) 위치를 고칠 때 쓴다.

요청: `{ "name": "민수", "lng": 128.98, "lat": 35.16, "claim": false }`
- `claim` 이 true 면 "내가 이 사람이다"를 등록하는 요청이다. owner_user_id 가 비어 있을 때만 성공한다
- `claim` 이 false 면 위치만 고친다. 토큰의 user_id 와 owner_user_id 가 같아야 한다

응답: 갱신된 Slots 와, 재계산이 끝났으면 새 Result

실패: 남의 핀이면 403, 이미 소유자가 있는 핀에 claim 하면 409

### GET /api/session/{id}

**로그인 필수.** 공유 링크용. 링크는 프론트 `/s/{id}` 주소 그대로이고 매직링크·임시 토큰으로 바꾸지 않는다. 링크만으로는 열람할 수 없고 주선자·참석자 누구든 구글 계정으로 로그인해야 한다. 응답은 AgentResponse 와 같은 모양이다. 세션이 있고 만료 전이면 마지막 result를 복호화해 반환. 없으면 404. 로그인한 사람이 그 세션의 참석자인지는 확인하지 않는다. 참석자 ↔ 계정 연결은 7절 핀 소유권을 따른다.

### DELETE /api/session/{id}

**로그인 필수.** 세션의 user_id와 토큰의 user_id가 다르면 403. 즉시 삭제, results는 cascade. 204.

### /mcp

FastMCP Streamable HTTP. 헤더 `Authorization: Bearer {MCP_TOKEN}`. 브라우저에서 직접 호출하지 않는다.

---

## 3. 슬롯 스키마 (LLM 출력 계약 1)

backend/app/schemas/slots.py. 파인튜닝 데이터의 output과 완전히 같아야 한다.

```python
class Participant(BaseModel):
    name: str
    origin: str | None              # 지명 텍스트. 없으면 None
    transport: Literal["car", "transit", "walk"] | None   # 없으면 None, 추측 금지
    pickup: str | None              # 이 사람을 태워 주는 참석자 이름
    pickup_at: str | None           # 태워지는 지점 ("송파구 집 앞", "금천구 역 앞"). 집결지(rendezvous)와 다름
    unfamiliar: bool = False        # 그 일대 지리를 모르는 참석자
    role: Literal["site", "vendor", "client", "colleague"]   # 현장 담당 / 업체 / 고객사 / 동료
    owner_user_id: str | None = None  # 이 핀을 소유한 사용자. None 이면 주선자 소유 (LLM 출력에는 없고 서버가 채운다)

class Rendezvous(BaseModel):
    name: str                       # 전원이 모이는 집결지 ("문정동 본사", "위병소"). 개인 픽업 지점은 participants[].pickup_at 에 둔다
    transport_after: Literal["car", "transit", "walk"] | None

class Access(BaseModel):
    required: bool                  # 출입조치·인솔이 필요한 현장인가
    applied: bool | None            # 출입조치 신청 여부. 모르면 None
    lead_min: int | None            # 절차 소요(분). 규칙 파일 기본값으로 채움

class Slots(BaseModel):
    preset: Literal["ship_maintenance", "si_deploy"] | None   # out_of_scope 가 True 일 때만 None
    datetime: str | None            # "목요일 08:00", "오늘 22:00"
    purpose: str | None             # "레이더 정기점검", "야간 배포", "고객사 미팅"
    destination: str | None         # "진해 기지", "여의도 고객사". 없으면 None
    participants: list[Participant]
    rendezvous: Rendezvous | None
    access: Access | None
    schedule_confirmed: bool | None # 입항·배포 시각 확정 여부. 모르면 None
    constraints: list[str]          # "arrival_delayed", "port_changed", "vendor_route_same_day", "mutual_deference", "luggage"
    missing: list[str]              # "participants[0].origin", "access.applied", "datetime"
    out_of_scope: bool = False      # 출발 후 실시간 상황
```

검증 규칙 (schemas/slots.py의 validator)
- out_of_scope 가 False 면 participants 1명 이상, preset 은 None 이 아니어야 함
- out_of_scope 가 True 면 preset 은 None, participants 는 빈 목록
- name·origin·purpose·destination에 한글·영문·숫자·공백·일부 기호 외 문자(한자·가나 포함) 있으면 ValidationError
- transport가 None인 참석자가 있으면 missing에 해당 경로가 있어야 함
- pickup 과 pickup_at 은 짝이다. 하나만 있으면 ValidationError
- owner_user_id 는 LLM 출력에 없다. 서버가 핀 확인 단계에서 채운다

---

## 4. 결과 스키마 (LLM 출력 계약 2)

```python
class Candidate(BaseModel):
    name: str                       # "진해 기지 위병소", "여의도 고객사 1층 로비", "인천항 입구"
    kind: Literal["gate", "lobby", "landmark", "pier", "hq"]   # 절차 시작점 / 랜드마크 / 부두 안 / 본사
    address: str
    lng: float
    lat: float
    rank: int | None                # failed 폴백이면 None
    access_ok: bool                 # 이 지점이 현재 출입조치 상태로 가능한가
    switched_from: str | None       # 전환 판정이면 원래 집결지
    reason: str                     # 한 줄, 규칙 파일 항목 인용
    rejected_reason: str | None

class ParticipantResult(BaseModel):
    name: str
    candidate_rank: int
    transport: Literal["car", "transit", "walk"]
    duration_min: int               # 여유 포함
    raw_duration_min: int           # API 값
    buffer_min: int
    departure_time: str             # "18:15"
    arrive_by: str                  # 절차 소요를 뺀 도착 기한
    transfer_count: int | None
    first_train: str | None
    last_train: str | None
    polyline: list[list[float]]     # [[lng, lat], ...]
    via_rendezvous: bool
    via_pickup: bool                # 운전자 경로가 이 사람을 태우러 경유하는가

class Result(BaseModel):
    candidates: list[Candidate]     # 최대 3. 집결지 판정 결과
    provisional: bool               # 입항·배포 시각 미확정이면 True
    per_participant: list[ParticipantResult]
    rendezvous_departure: str | None   # 집결지에서 출발할 시각
    confidence: float
    model_small: str
    model_large: str | None
    prompt_version: str
    routed_to: Literal["small", "large"]
```

LLM(대형)이 만드는 건 candidates의 rank·reason·rejected_reason과 전환 판정(switched_from)뿐이다. 숫자와 access_ok는 코드가 넣는다. 대형 모델 응답은 `{"rankings":[{"candidate_idx":0,"rank":1,"reason":"...","rejected_reason":null}, ...]}` 형태로 받아 Candidate에 합친다.

---

## 5. 파이프라인 (services/pipeline.py)

순차 실행, 루프 없음. 각 단계는 Langfuse span으로 남긴다.

| 단계 | 함수 | 입력 → 출력 | 실패 시 |
|---|---|---|---|
| 0 | vision.extract_text | 이미지 → 텍스트 | 대형 비전 모델 1회 재시도 → 실패면 need_info("캡처를 읽지 못했습니다, 문장으로 입력") |
| 1 | llm.extract_slots | 텍스트(+이전 슬롯) → Slots | 스키마 위반 시 재시도 1회 → 대형 모델 승격 → 실패면 failed |
| 1-1 | 범위 판정 | slots.out_of_scope → out_of_scope 응답 | |
| 1-2 | 누락 판정 | slots.missing 비어 있지 않으면 need_info | |
| 1-3 | 기간 판정 | slots.datetime을 시각으로 바꿔 오늘+30일을 넘으면 need_info("30일 안의 약속만 잡을 수 있습니다"). 30은 skills/converge/rules/의 값 | 코드라 실패 없음 |
| 2 | geo.geocode_all | 참석자·집결지·목적지 지명 → 좌표, confidence | 한 명이라도 confidence < 0.8 → need_confirm |
| 2-1 | 핀 확인 | 사용자가 confirmed_participants 반환. 각 핀의 owner_user_id 를 검사해 본인 핀만 수정을 허용한다 (7절 핀 소유권) | 남의 핀을 수정하면 403 |
| 3 | geo.candidates | 집결 후보 생성: 절차 시작점(위병소·고객사 1층·본사) + 도착 어긋남 시 랜드마크(항만 입구·역) | 후보 0곳이면 목적지 좌표 자체를 후보로 |
| 4 | routes.compute_all | 참석자 × 후보, 집결지 있으면 2구간, pickup_at 있으면 운전자 경로에 경유지로 추가하고 태워지는 사람은 탑승 이후 구간만 계산. 캐시 확인 후 API | 타임아웃·5xx 백오프 2회 → 실패 참석자만 "조회 실패", 나머지로 진행 |
| 5 | rules.apply | 절차 소요 반영, 출입조치 상태별 후보 가능 여부(access_ok), 도착 어긋남 전환 조건, 을 관례, 업체 순회 | 코드라 실패 없음 |
| 6 | judge.rank | 후보 표 + 프리셋 규칙 문서 → rank·reason·switched_from | 스키마 위반 재시도 1회 → 실패면 rules.apply 순으로 rank, reason은 규칙 문구 그대로 |
| 7 | rules.departure | (도착 기한 − 절차 소요) − 소요시간 − 여유 = 출발 시각, 집결지면 2단 역산, 야간이면 첫차 조회, 시각 미확정이면 provisional | |
| 8 | store.save + 응답 | expires_at을 여기서 계산해 넣는다: meet_at 있으면 meet_at+30일, 없으면(임시 세션) created_at+7일. DB 기본값 없음 | |

2026-09-18 기준 구현 상태: 0~2단계와 갈림길(1-1 범위 밖, 1-2 누락, 2-1 핀 확인·핀 소유권)까지 services/pipeline.py 에 있다.
1-3(기간 판정)은 규칙 파일이 생기면 붙인다. 3~8단계는 MCP 도구 7개가 준비되면 채운다. 그때까지 그 자리는 failed 로 끝난다.
pipeline.run 은 바깥 함수를 Deps 로 받는다. 테스트가 키 없이 단계 순서만 검사하기 위해서다 (backend/tests/test_pipeline.py).

### 라우팅 (services/router.py)

```
small: 참석자 <= 2 and destination 있음 and constraints 비어 있음 and rendezvous 없음 and (access 없음 or access.applied == True)
       → 6단계 judge를 건너뛴다. rank는 rules.apply 점수 순, reason은 해당 규칙 문구를 그대로 붙인다. 대형 모델 호출 없음
large: 그 외 전부 → 6단계에서 대형 모델이 rank·reason 생성
소형 모델은 어느 경우든 1단계 슬롯 추출만 담당한다
```

라우팅 전후 비용은 request_logs에서 집계한다.

### 재질문

session_id가 있으면 먼저 잠금 검사: 세션의 user_id가 토큰과 다르면 403, meet_at 다음날 0시가 지났으면 409 (LLM 호출 전). meet_at이 없는 임시 세션은 잠기지 않고, 이번 재질문으로 시각이 들어오면 8단계에서 expires_at을 meet_at+30일로 다시 계산한다. 통과하면 이전 Slots를 1단계 프롬프트에 넣고 "바뀐 것만 갱신"을 지시. 결과는 새 results 행.

---

## 6. MCP 도구 시그니처

| tool | 입력 | 출력 | 호출 API |
|---|---|---|---|
| geocode | query: str, bias_lng: float, bias_lat: float, radius_m: int = 20000 | {lng, lat, name, address, confidence, alternatives[]} | 카카오 로컬 키워드 검색 (x, y, radius). 지하철역 우선 규칙 |
| search_places | lng, lat, radius_m, kind: "gate" or "landmark" or "lobby" or "cafe", limit: int | [{name, address, lng, lat, kind}] | 카카오 로컬 키워드 검색 (위병소·정문·항만 입구·역·로비·카페) |
| route_car | origin: [lng, lat], destination: [lng, lat], departure_time: "yyyyMMddHHmm" or None, waypoint: [lng, lat] or None | {duration_sec, distance_m, polyline[], toll, fare_taxi} | 카카오모빌리티 미래 운행(시각 있음) / 자동차 길찾기(없음) |
| route_transit | origin, destination | {duration_sec, transfer_count, walk_m, fare, polyline[], legs[]} | TMAP 대중교통 |
| first_last_train | station_name: str, city: "seoul" or "busan", weekday: "weekday" or "sat" or "holiday", direction | {first: "05:30", last: "23:40", line} | 서울: 서울교통공사 첫차·막차 API (1~9호선, 역명→역코드 API 선행). 부산: 부산교통공사 열차시각표 API에서 첫차(0400부터 1건)·막차(2300부터 마지막) 계산, 역외부코드는 레포 CSV |
| vessel_schedule | port: str, date: str | [{vessel, arrival, departure, pier}] | 해양수산부 선박 입출항 기록(PORT-MIS, 공공데이터포털). 군함 포함 여부 확인 필요, 없으면 사용자 입력으로 |
| departure_calc | arrive_by: "HH:MM", duration_sec, buffer_min, access_lead_min | {depart_at: "HH:MM", arrive_by_adjusted: "HH:MM", day_offset: int} | 계산. day_offset은 출발이 전날이면 -1 (야간 배포에서 생김, 09-18 추가) |

route_transit 이 부르는 TMAP 대중교통은 초당 호출 제한이 있어 연속 호출 시 429 THROTTLED 가 온다 (scripts/fetch_mock_routes.py 에서 확인). 간격을 두거나 재시도로 처리한다.

description은 "언제 쓰는 도구인지"가 한 문장에 드러나게 쓴다. 예: vessel_schedule은 "함정 프리셋에서 입항·출항 시각이 확정됐는지 확인할 때 쓴다. 기록에 없으면 미확정으로 본다".

---

## 7. 규칙값 (skills/converge/rules/)

코드(rules.py)와 문서가 같은 값을 가져야 한다. 값은 문서가 기준이고 코드는 문서를 읽어 로드한다(yaml 프론트매터). 상식 수준 규칙(공평성, 막차 등)은 두지 않는다. 각 파일 첫 줄에 근거 사례를 적는다.

| 파일 | 키 | 값 | 근거 사례 |
|---|---|---|---|
| access.md | gate_lead_min (함정) | 20 (하정운 확인) | 진해 정기점검: 점검 시각이 아니라 위병소 도착 기한으로 역산 |
| access.md | lobby_lead_min (SI) | 15 (김승욱 확인) | 여의도 야간 배포: 1층 보안서류 작성·인솔 |
| access.md | rendezvous_is_procedure_start | true | 합류 지점은 역이 아니라 인솔·출입 절차가 시작되는 곳 |
| access.md | switch_if_delay_min | 30 | 인천 레이더: 도착 30분 이상 어긋나면 출입조치 포기, 부두 밖 |
| access.md | outside_landmark_kinds | 항만 입구, 역, 부대 정문 앞 | 현장·업체 모두 지리 모름 |
| access.md | no_procedure_all_transit_no_rendezvous | true | 절차 없고 전원 대중교통이면 합류 불필요 |
| schedule.md | unconfirmed_is_provisional | true | 입항지 변경 건: 시각 미확정이면 잠정 표시 |
| schedule.md | port_change_recompute | vendor_route, access | 입항지 바뀌면 업체 동선과 출입조치 재계산 |
| schedule.md | night_end_first_train | true | 야간 배포 종료 후 첫차 귀가 |
| schedule.md | deploy_window | 22:00~06:00 (김승욱 확인) | 야간 배포 창 |
| convention.md | client_visit_side | client | 을은 고객사 쪽으로 |
| convention.md | mutual_deference_resolve | counterpart (고객·타지) | 강남 프론트: 서로 배려 시 상대 쪽 확정 |
| convention.md | joint_docs_requires_hq_gather | true | 마곡: 출입증·보안서류 공동 작성이면 본사 집결 후 법인차 |
| transport.md | buffer_client_min | 20 | 고객사 미팅 지각은 신뢰 문제 |
| transport.md | buffer_deploy_min | 15 | 인솔 시각 10~20분 전 |
| transport.md | car_traffic_pct | 15 (최소 10분, 출퇴근 25) | |
| transport.md | transit_transfer_extra_min | 10 | 마곡: 앱 55분에 환승 가산 |
| transport.md | luggage_requires_car | true | 장비 있는 날 |
| transport.md | pickup_wait_min | 5 | 태우는 지점에서 대기 |
| transport.md | pickup_counts_from_board | true | 태워지는 사람의 소요시간은 탑승 이후 구간만 |
| transport.md | max_pickup_per_car | 1 | 차 1대당 1명. 다중 픽업 순서 최적화는 범위 밖 |
| transport.md | route_cache_ttl_hours | 24 | 경로 응답 캐시 보관 시간 (테이블정의서 4절) |
| transport.md | geocode_cache_ttl_hours | 720 | 지오코딩 응답 캐시 보관 시간 |
| vendor.md | same_day_route_first | true | 업체 당일 다른 방문지 먼저 반영 |
| vendor.md | night_solo_requires_car_parking | true | 야간 단독 출동은 차량, 주차 확인 |
| vendor.md | unfamiliar_prefer | 환승 0, 역·정문 300m 이내 | 타지 담당자 |

프리셋 (presets/)

| 키 | ship_maintenance | si_deploy |
|---|---|---|
| access.required 기본 | true (위병소·출입조치) | true (인솔·보안서류), 미팅은 false |
| candidate_kinds | gate, pier, landmark | lobby, hq, cafe |
| time_source | vessel_schedule 또는 사용자 입력 | 사용자 입력 |
| buffer | buffer_client_min | buffer_deploy_min / buffer_client_min |
| night_rule | night_solo_requires_car_parking | night_end_first_train |

"(확인)" 표시 값은 착수 후 해당 조원이 확정한다.

### 핀 소유권

참석자가 각자 들어와 자기 위치를 찍을 수 있다. 다 모일 때까지 기다리지 않고, 들어온 사람 위치로 바로 계산한다.

| 상황 | owner_user_id | 수정 권한 |
|---|---|---|
| 주선자가 문장으로 입력해 만든 핀 | None | 주선자만 |
| 참석자가 공유 링크로 들어와 자기라고 고른 핀 | 그 사람의 user_id | 그 사람만 |

- 전원이 로그인하지만, 참석자가 직접 들어와 자기 핀을 찍지 않는 경우도 있다. 그때는 주선자가 입력한 핀이 owner_user_id = null 로 남고 주선자가 수정한다. 참석자가 들어와 claim 하면 그 시점부터 그 사람 소유가 된다
- 참석자는 공유 링크를 열고 구글 로그인한 뒤 참석자 목록에서 자기를 한 번 고른다. 그 시점에 owner_user_id 가 채워진다
- 한 번 소유자가 정해진 핀은 주선자도 수정하지 못한다
- 수정 요청은 PATCH /api/session/{id}/participants 로 받고, 서버가 토큰의 user_id 와 owner_user_id 를 대조한다. 다르면 403
- 새 위치가 들어오면 그 세션의 결과를 다시 계산해 새 results 행을 만든다

---

## 8. 프롬프트

Langfuse Prompt 이름과 역할. 코드에 문자열로 두지 않는다.

| 이름 | 모델 | 역할 |
|---|---|---|
| converge/slot-extract | 소형 (GGUF) 또는 대형 폴백 | 텍스트 → Slots JSON. GBNF 문법 강제. 출입조치·인솔·집결지·픽업·업체 역할 추출. 범위 밖이면 out_of_scope true 에 preset null |
| converge/vision-transcribe | Gemini Flash | 캡처 → 대화 텍스트 (이름·시각·말풍선 유지) |
| converge/judge-ship, converge/judge-si | Sonnet 5 | 후보 표 + 프리셋 규칙 → rankings JSON (rank·reason·switched_from) |
| converge/eval-judge | GPT-5.6 Luna | reason이 규칙과 계산값에 부합하는지 0~2점 |

---

## 9. 환경변수

루트 `.env.example` (backend, compose)

```
OPENROUTER_API_KEY=      # OpenRouter 대시보드
KAKAO_REST_KEY=          # 카카오 개발자 콘솔
TMAP_APP_KEY=            # SK오픈API
DATA_GO_KR_KEY=          # 첫차·막차, 선박 입출항
DATABASE_URL=postgresql://app:app@db:5432/app   # 로컬 compose 기본값. 운영은 Supabase 연결 문자열
SUPABASE_URL=            # 프로젝트 주소. 토큰 서명을 공개키(/auth/v1/.well-known/jwks.json)로 검증. 비밀값 없음
AUTH_REQUIRED=true       # 로컬 채점용으로만 false. 배포 환경에서는 항상 true
ENCRYPTION_KEY=          # 32바이트 base64, AES-256-GCM
LANGFUSE_PUBLIC_KEY=     # Langfuse Cloud
LANGFUSE_SECRET_KEY=     # Langfuse Cloud
LANGFUSE_HOST=           # https://cloud.langfuse.com
MCP_TOKEN=               # /mcp Bearer 토큰
INTERNAL_TOKEN=          # /internal/cleanup
MODEL_SMALL_PATH=backend/app/models/kanana_2.1b-Q4_K_M.gguf   # HF kimseunguk/converge-slot-extractor (공개). 빌드 시 받는다
MODEL_SMALL=            # 비우면 처음부터 대형으로 추출한다. 로컬 GGUF 서빙이 붙기 전 임시로 OpenRouter 소형 모델을 넣어 볼 때 쓴다
MODEL_LARGE=anthropic/claude-sonnet-5
MODEL_VISION=google/gemini-3.8-flash
MODEL_EVAL_JUDGE=openai/gpt-5.6-luna
COST_LIMIT_USD_PER_REQUEST=0.05
```

`frontend/.env.example` (브라우저에 노출되는 값만)

```
NEXT_PUBLIC_SUPABASE_URL=       # Supabase 프로젝트 URL
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=  # sb_publishable_... (공개 가능, RLS 전제). 옛 anon 키는 2026년 말까지만
NEXT_PUBLIC_API_BASE=http://localhost:8000
NEXT_PUBLIC_KAKAO_JS_KEY=       # 카카오 지도 SDK (NEXT_PUBLIC_ 없으면 브라우저에 안 넘어감)
```

supabase-py는 쓰지 않는다. 백엔드는 DATABASE_URL로 Postgres에 직접 붙고, Supabase는 운영 DB와 로그인(Auth)으로만 쓴다.

---

## 10. 실행

```
cp .env.example .env
docker compose up          # backend:8000 (/api/agent, /health, /mcp 모두 여기) + db:5432 (postgres:16, backend/db/ 자동 실행)
cd frontend && npm run dev # :3000, NEXT_PUBLIC_API_BASE=http://localhost:8000
```

Cloud Run 서비스는 하나다 (backend에 MCP 마운트). 프론트는 Vercel. 카카오 콘솔에 Vercel 도메인과 localhost:3000을 등록한다.

---

## 11. 미확정 (착수일에 확인)

| 항목 | 상태 | 확인 방법 |
|---|---|---|
| 지하철 첫차·막차 | 확인됨 | 서울교통공사 첫차·막차 API(1~9호선만, 민자 노선 제외), 부산교통공사 열차시각표 API. 공공데이터포털 키 하나. 부산 역외부코드 CSV를 레포에 둠 |
| TMAP 대중교통 도착 시각 지정 | 미확인 | 문서의 요청 파라미터 확인. 없으면 현재 기준 소요시간으로 역산 |
| OpenRouter 슬롯 추출 통과율 | 일부 확인 (09-18) | 크레딧 충전 완료. openai/gpt-4o-mini 로 converge/slot-extract v2 실호출, 참석자·픽업·누락 추출 통과 (11초, 재시도 없음). 평가셋 30건 기준 통과율은 미측정 |
| 소형 모델 최종 선택 | 결정 (09-18) | kanana_2.1b-Q4_K_M.gguf (HF kimseunguk/converge-slot-extractor, 공개). 검증 40건 Exact Match 85.0%. 대안은 qwen3_1.7b 45.0%, qwen3_0.6b 47.5% |
| 선박 입출항 데이터에 군함 포함 여부 | 미확인 | 공공데이터포털 파일 열어 확인 (하정운). 없으면 vessel_schedule 도구 제외 |
| 규칙값 "(확인)" 항목 | 미확정 | 착수일 조원 확정 |
| compose db healthcheck | 적용됨 (09-17) | pg_isready healthcheck + depends_on condition: service_healthy. backend/db/를 initdb에 마운트 |
| requirements.txt asyncpg | 적용됨 (09-17) | 주석 해제. SQLAlchemy 안 씀, asyncpg 직접. DATABASE_URL은 postgresql:// |
| 채점자 로컬 재현 시 LLM·카카오·TMAP 키 | 미확인 | .env.example만으로는 못 돈다. 1차 때 어떻게 전달했는지 확인 후 README에 방식 명시 |
| Supabase 새 프로젝트 | 해결 (09-18) | 팀 구글 계정으로 새 조직 Converge2-5에 `converge_agent` 생성. 표 5개·RLS 마이그레이션 완료 |
| 구글 OAuth 동의 화면 | 설정됨, 테스트 모드 (09-18) | 테스트 사용자 조원 2명 등록, 리디렉트 localhost:3000/**. 브라우저 로그인→토큰→백엔드 검증 실측. **남음:** 채점자 계정 처리(테스트 사용자 추가 또는 프로덕션 전환), Vercel 주소 추가 — 배포 때 |
| Langfuse 트레이스의 참석자 이름·출발지 | 미검토 | 평문으로 들어간다. 마스킹 여부 (김승욱, observability) |
| 로컬 확인용 서버 | 임시 (09-18) | backend/app/main.py 는 DATABASE_URL 과 Supabase 공개키가 있어야 뜬다. 그 전까지 POST /api/agent 만 띄우는 임시 서버로 화면을 확인했다. DB 설정이 들어오면 임시 서버를 버린다 |

---

## 12. 역할 경계

| 영역 | 담당 | 만나는 지점 |
|---|---|---|
| backend/, mcp_server/, frontend/, skills/ (si_deploy 규칙) | 김승욱 | AgentRequest / AgentResponse 스키마 |
| finetune/, skills/ (ship_maintenance 규칙) | 하정운 | 같은 스키마, GGUF 파일 경로 |
| evals/, docs/ | 공동 | 함정 문항은 하정운, SI 문항은 김승욱이 판정. 상대 문항은 검토만 |
| backend/db/, services/store.py, services/auth.py (DB·인증) | 하정운 | 테이블정의서.md, 9절 환경변수 |

서로의 폴더를 고칠 때는 PR로 하고, 스키마 변경은 이 문서 3·4절을 먼저 고친 뒤 양쪽에 알린다.
