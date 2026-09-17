# SDD · Converge 구현 명세

버전 2.0 · 2026.09.17 · 5조 김승욱, 하정운 · 도메인: 현장이 움직이는 유지보수·배포 작업의 집결 조율 (함정 정비 / SI 배포)

이 문서는 코드를 쓰는 사람과 Claude Code가 따르는 기준이다. 여기 없는 결정은 만들지 말고 물어본다. 스키마·엔드포인트·규칙값을 바꾸려면 이 문서를 먼저 고친다.

---

## 1. 폴더 구조

```
converge/
  CLAUDE.md
  README.md
  docker-compose.yml
  .env.example
  docs/
    PRD.md  SDD.md  TABLES.md  EVAL_REPORT.md
  backend/                      FastAPI (Cloud Run)
    app/
      main.py                   앱 생성, 라우터 등록, 미들웨어(request_id)
      routers/
        agent.py                POST /api/agent
        health.py               GET /health
        session.py              GET /api/session/{id}  (공유 링크용 읽기)
        internal.py             POST /internal/cleanup (Cloud Scheduler 전용, 토큰)
      schemas/
        slots.py                슬롯 추출 결과 (LLM 출력 계약 1)
        result.py               최종 결과 (LLM 출력 계약 2, API 응답)
        request.py              API 요청
      services/
        llm.py                  모든 LLM 호출은 여기만. OpenRouter + 로컬 GGUF
        vision.py               캡처 → 텍스트
        router.py               소형/대형 선택 규칙
        geo.py                  지오코딩·장소 검색 (MCP 클라이언트 경유)
        routes.py               경로·소요시간 (MCP 클라이언트 경유), 캐시
        rules.py                Skill 규칙 로드, 계산식 (절차 소요·여유·역산·전환 조건)
        judge.py                후보 판정 프롬프트 조립, 대형 모델 호출
        pipeline.py             단계 오케스트레이션 (루프 없음, 순차)
        store.py                Supabase 접근, 암호화
      observability/
        langfuse.py             트레이스·span·프롬프트 조회
      models/
        slot_extractor.gguf     파인튜닝 소형 모델 (git LFS 또는 빌드 시 다운로드)
    tests/
    Dockerfile
    requirements.txt
  mcp_server/                   FastMCP. backend/app/main.py에 ASGI로 마운트해 같은 프로세스에서 /mcp 제공
    server.py                   FastMCP 인스턴스, Bearer 토큰
    tools/
      geocode.py  search_places.py  route_car.py  route_transit.py  first_last_train.py  vessel_schedule.py  departure_calc.py
  frontend/                     Next.js (Vercel)
    app/
      page.tsx                  지도 + 채팅
      s/[id]/page.tsx           공유 링크 읽기 전용
      api/agent/route.ts        Cloud Run 프록시 (키 숨김)
    components/
      MapView.tsx  ChatPanel.tsx  ParticipantPins.tsx  ResultTable.tsx  Progress.tsx
  skills/converge/
    SKILL.md
    rules/  access.md  schedule.md  convention.md  transport.md  vendor.md
    presets/  ship_maintenance.md  si_deploy.md
    failures.md
    output-contract.md
  evals/
    dataset.jsonl               30건
    run_eval.py                 Langfuse Dataset 실행·score 기록
  finetune/                     학습 파이프라인 (별도 README)
```

---

## 2. 엔드포인트

### POST /api/agent

요청 (backend/app/schemas/request.py)

```python
class AgentRequest(BaseModel):
    session_id: str | None          # 재질문이면 기존 세션
    text: str | None                # 문장 입력
    image_base64: str | None        # 카톡 캡처 (jpeg/png)
    preset: Literal["ship_maintenance", "si_deploy"] | None   # 사용자가 고른 경우
    confirmed_participants: list[ParticipantInput] | None  # 핀 확인 단계에서 수정한 좌표
    user_key: str                   # 브라우저 익명 ID (Langfuse user_id)
```

text와 image_base64 중 하나는 필수. confirmed_participants가 오면 슬롯 추출을 건너뛰고 계산부터 시작한다.

응답 (backend/app/schemas/result.py)

```python
class AgentResponse(BaseModel):
    session_id: str
    stage: Literal["need_confirm", "need_info", "done", "out_of_scope", "failed"]
    slots: Slots                    # 추출·확정된 슬롯 (항상 포함)
    result: Result | None           # stage == done 일 때
    questions: list[str]            # need_info 일 때 되물을 것
    message: str                    # 화면에 보여줄 한 줄
    trace_id: str
```

- need_confirm: 참석자 핀을 지도에 찍고 사용자 확인 대기 (확신도 < 0.8 또는 되묻기 없음)
- need_info: 필수 슬롯 누락 (출발지·이동수단·시각 중 하나). questions에 무엇을 물을지
- done: 후보와 참석자별 결과
- out_of_scope: 실시간 상황 등 범위 밖
- failed: 재시도 후에도 실패. result 없이 후보 핀만 있으면 result.candidates에 rank 없이 담는다

### GET /health

`{"status":"ok","model_loaded":true,"version":"..."}`

### GET /api/session/{id}

공유 링크용. 세션이 있고 만료 전이면 마지막 result를 복호화해 반환. 없으면 404.

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
    unfamiliar: bool = False        # 그 일대 지리를 모르는 참석자
    role: Literal["site", "vendor", "client", "colleague"]   # 현장 담당 / 업체 / 고객사 / 동료

class Rendezvous(BaseModel):
    name: str                       # 집결지 ("문정동 본사", "여의도역", "위병소")
    transport_after: Literal["car", "transit", "walk"] | None

class Access(BaseModel):
    required: bool                  # 출입조치·인솔이 필요한 현장인가
    applied: bool | None            # 출입조치 신청 여부. 모르면 None
    lead_min: int | None            # 절차 소요(분). 규칙 파일 기본값으로 채움

class Slots(BaseModel):
    preset: Literal["ship_maintenance", "si_deploy"]
    datetime: str | None            # "목요일 08:00", "오늘 22:00"
    purpose: str | None             # "레이더 정기점검", "야간 배포", "고객사 미팅"
    destination: str | None         # "진해 기지", "여의도 고객사". 없으면 None
    participants: list[Participant]
    rendezvous: Rendezvous | None
    access: Access | None
    schedule_confirmed: bool | None # 입항·배포 시각 확정 여부. 모르면 None
    constraints: list[str]          # "arrival_delayed", "port_changed", "vendor_route_same_day", "mutual_deference"
    missing: list[str]              # "participants[0].origin", "access.applied", "datetime"
    out_of_scope: bool = False      # 출발 후 실시간 상황
```

검증 규칙 (schemas/slots.py의 validator)
- participants 1명 이상
- name·origin·purpose·destination에 한글·영문·숫자·공백·일부 기호 외 문자(한자·가나 포함) 있으면 ValidationError
- transport가 None인 참석자가 있으면 missing에 해당 경로가 있어야 함

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
| 2 | geo.geocode_all | 참석자·집결지·목적지 지명 → 좌표, confidence | 한 명이라도 confidence < 0.8 → need_confirm |
| 2-1 | 핀 확인 | 사용자가 confirmed_participants 반환 | |
| 3 | geo.candidates | 집결 후보 생성: 절차 시작점(위병소·고객사 1층·본사) + 도착 어긋남 시 랜드마크(항만 입구·역) | 후보 0곳이면 목적지 좌표 자체를 후보로 |
| 4 | routes.compute_all | 참석자 × 후보, 집결지 있으면 2구간. 캐시 확인 후 API | 타임아웃·5xx 백오프 2회 → 실패 참석자만 "조회 실패", 나머지로 진행 |
| 5 | rules.apply | 절차 소요 반영, 출입조치 상태별 후보 가능 여부(access_ok), 도착 어긋남 전환 조건, 을 관례, 업체 순회 | 코드라 실패 없음 |
| 6 | judge.rank | 후보 표 + 프리셋 규칙 문서 → rank·reason·switched_from | 스키마 위반 재시도 1회 → 실패면 rules.apply 순으로 rank, reason은 규칙 문구 그대로 |
| 7 | rules.departure | (도착 기한 − 절차 소요) − 소요시간 − 여유 = 출발 시각, 집결지면 2단 역산, 야간이면 첫차 조회, 시각 미확정이면 provisional | |
| 8 | store.save + 응답 | | |

### 라우팅 (services/router.py)

```
small: 참석자 <= 2 and destination 있음 and constraints 비어 있음 and rendezvous 없음 and (access 없음 or access.applied == True)
       → 6단계 judge를 건너뛴다. rank는 rules.apply 점수 순, reason은 해당 규칙 문구를 그대로 붙인다. 대형 모델 호출 없음
large: 그 외 전부 → 6단계에서 대형 모델이 rank·reason 생성
소형 모델은 어느 경우든 1단계 슬롯 추출만 담당한다
```

라우팅 전후 비용은 request_logs에서 집계한다.

### 재질문

session_id가 있으면 이전 Slots를 1단계 프롬프트에 넣고 "바뀐 것만 갱신"을 지시. 결과는 새 results 행.

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
| departure_calc | arrive_by: "HH:MM", duration_sec, buffer_min, access_lead_min | {depart_at: "HH:MM", arrive_by_adjusted: "HH:MM"} | 계산 |

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

## 8. 프롬프트

Langfuse Prompt 이름과 역할. 코드에 문자열로 두지 않는다.

| 이름 | 모델 | 역할 |
|---|---|---|
| converge/slot-extract | 소형 (GGUF) 또는 대형 폴백 | 텍스트 → Slots JSON. GBNF 문법 강제. 출입조치·인솔·집결지·업체 역할 추출 |
| converge/vision-transcribe | Gemini Flash | 캡처 → 대화 텍스트 (이름·시각·말풍선 유지) |
| converge/judge-ship, converge/judge-si | Sonnet 5 | 후보 표 + 프리셋 규칙 → rankings JSON (rank·reason·switched_from) |
| converge/eval-judge | GPT-5.6 Luna | reason이 규칙과 계산값에 부합하는지 0~2점 |

---

## 9. 환경변수 (.env.example)

```
OPENROUTER_API_KEY=<...>
KAKAO_REST_KEY=<...>
KAKAO_JS_KEY=<...>            # frontend
TMAP_APP_KEY=<...>
DATA_GO_KR_KEY=<...>          # 첫차·막차, 선박 입출항
SUPABASE_URL=<...>
SUPABASE_SERVICE_KEY=<...>
ENCRYPTION_KEY=<...>          # 32바이트 base64, AES-256-GCM
LANGFUSE_PUBLIC_KEY=<...>
LANGFUSE_SECRET_KEY=<...>
LANGFUSE_HOST=<...>
MCP_TOKEN=<...>
INTERNAL_TOKEN=<...>          # /internal/cleanup
MODEL_SMALL_PATH=backend/app/models/slot_extractor.gguf
MODEL_LARGE=anthropic/claude-sonnet-5
MODEL_VISION=google/gemini-3.8-flash
MODEL_EVAL_JUDGE=openai/gpt-5.6-luna
COST_LIMIT_USD_PER_REQUEST=0.05
```

---

## 10. 실행

```
cp .env.example .env
docker compose up          # backend:8080 (/api/agent, /health, /mcp 모두 여기)
cd frontend && npm run dev # :3000, NEXT_PUBLIC_API_BASE=http://localhost:8080
```

Cloud Run 서비스는 하나다 (backend에 MCP 마운트). 프론트는 Vercel. 카카오 콘솔에 Vercel 도메인과 localhost:3000을 등록한다.

---

## 11. 미확정 (착수일에 확인)

| 항목 | 상태 | 확인 방법 |
|---|---|---|
| 지하철 첫차·막차 | 확인됨 | 서울교통공사 첫차·막차 API(1~9호선만, 민자 노선 제외), 부산교통공사 열차시각표 API. 공공데이터포털 키 하나. 부산 역외부코드 CSV를 레포에 둠 |
| TMAP 대중교통 도착 시각 지정 | 미확인 | 문서의 요청 파라미터 확인. 없으면 현재 기준 소요시간으로 역산 |
| OpenRouter 슬롯 추출 통과율 | 미측정 | 크레딧 충전 후 spike 04 실행 |
| 소형 모델 최종 선택 | 미정 | 새 도메인 데이터로 재학습 후 compare.md로 결정 |
| 선박 입출항 데이터에 군함 포함 여부 | 미확인 | 공공데이터포털 파일 열어 확인 (하정운). 없으면 vessel_schedule 도구 제외 |
| 규칙값 "(확인)" 항목 | 미확정 | 착수일 조원 확정 |

---

## 12. 역할 경계

| 영역 | 담당 | 만나는 지점 |
|---|---|---|
| backend/, mcp_server/, skills/ (si_deploy 규칙) | 김승욱 | AgentRequest / AgentResponse 스키마 |
| frontend/, finetune/, skills/ (ship_maintenance 규칙) | 하정운 | 같은 스키마, GGUF 파일 경로 |
| evals/, docs/ | 공동 | 함정 문항은 하정운, SI 문항은 김승욱이 판정. 상대 문항은 검토만 |

서로의 폴더를 고칠 때는 PR로 하고, 스키마 변경은 이 문서 3·4절을 먼저 고친 뒤 양쪽에 알린다.
