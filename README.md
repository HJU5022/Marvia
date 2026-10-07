# Marvia (마르비아)

**B/L 하나로 내 화물이 제때 오는지 판정하고, 왜 그런지 근거까지 보여준다.**

KDT AI Human 7기 2차 팀 프로젝트 · 5조 · [유형 1] 도메인 특화 LLM 서비스

| | |
|---|---|
| 서비스 | https://marvia.up.railway.app (Railway `marvia-web`, 재생 모드 데모) |
| Agent API | https://marvia-api-production.up.railway.app (Railway `marvia-api`) · `GET /health` · `POST /api/agent` |
| MCP | 위 API 주소의 `/mcp` (Bearer 토큰) |
| 기획 | [docs/Marvia_PRD.md](./docs/Marvia_PRD.md) |
| 설계 | [docs/Marvia_SDD.md](./docs/Marvia_SDD.md) |
| 작업 분담 | [docs/Marvia_개발_작업_리스트.md](./docs/Marvia_개발_작업_리스트.md) |
| 지표 | [EVAL_REPORT.md](./EVAL_REPORT.md) |

배포 주소는 `docs/release_manifest.json`에 적힌 값이다. 배포는 Railway이고 Vercel과 Cloud Run은 쓰지 않는다(10-05 결정, `Dockerfile.railway`). 배포 서버는 10-07 결정부터 실제 모드(`REPLAY_MODE=false`)로 돈다. 재생 모드(`REPLAY_MODE=true`)는 채점자와 키 없는 로컬 데모, 평가용으로 남긴다. 미해결(원인 미확인): Railway 서버(리전 기록은 Singapore)에서 해수부 API가 ConnectTimeout(15초 x 3회)으로 실패한다. 한국에서는 0.1초에 응답한다.

---

## 1. 팀 (5조)

| 이름 | GitHub | 역할 | 담당 묶음 | 한마디 |
|---|---|---|---|---|
| 하정운 | @HJU5022 | 조장 · 풀스택  | (팀 회의에서 확정) | 눈 감아도 코딩하기. |
| 김승욱 | @seungwook-kim | 풀스택 | (팀 회의에서 확정) | 눈 뜨면 코딩하기. |

- 작업 묶음은 A 백엔드·배포 / B MCP·데이터 소스 / C 판정·LLM·Skill / D 관측·수집·평가 / E 프론트엔드입니다.
- 하정운은 함정 경험을 바탕으로 Skill 판정 기준(`skills/ais-reliability/`)과 평가셋 라벨 검수를 맡습니다.
- 묶음 사이는 계약(C1~C8)으로만 이어집니다. 계약은 [작업 리스트 0장](./docs/Marvia_개발_작업_리스트.md)과 [SDD 3절](./docs/Marvia_SDD.md)을 따릅니다.

### 일정

| 기간 | 작업 |
|---|---|
| 9/22 | 키 발급 4종, 수집 워커 가동, 골격(FastAPI 빈 서버·Dockerfile·/health) |
| 9/23 | 계약(C1~C8) 고정, 평가셋 구성안 |
| 9/24~27 | (추석) 워커 가동 유지, MCP 뼈대, Langfuse 연결, Skill 초안 (Cloud Run 배포는 계획이었고 하지 않았다) |
| 9/28~10/2 | 본 구현, 10/1까지 베이스라인 (a) |
| 9/30 | 중간 점검 |
| 10/6~8 | 라벨 확정, 평가 (a)(b)(c), EVAL_REPORT, UI, 데모 영상. **10/8 자정 코드 동결** |
| 10/9~11 | 발표 자료. 코드 수정 없음 |
| 10/12 | 발표 |

---

## 2. 어떤 프로젝트인가

### 문제

포워더가 일일이 챙겨주지 않는 소량 해상 수입자(스마트스토어 수입 셀러, 구매대행)는 부산항으로 들어오는 화물 몇 건을 직접 관리합니다. 추적 서비스에 ETA가 떠 있어도 **그 값을 믿어도 되는지, 그 배가 내 배가 맞는지, 유니패스 통관 단계가 무슨 뜻인지** 판단하지 못합니다. 그래서 포워더 문의와 직접 확인에 시간을 쓰고, 지연을 늦게 알아 판매 일정이 틀어집니다.

실제 AIS 데이터는 생각보다 자주 깨져 있습니다. ShipFinder 응답에서 직접 확인한 사례입니다.

- 53일 전 위치를 현재 위치처럼 반환
- 같은 선명으로 검색하면 국적이 다른 동명 선박이 섞여 나옴
- IMO 하나에 MMSI 2개 (MMSI 중복)
- 목적지가 "XX QZQZZZZZ"처럼 깨져 있음
- 항해상태는 "항해 중"인데 속도 0

팀원이 해군 함정에서 AIS·항해 상태·입출항 절차를 직접 다뤘고, 이 판독 경험이 판정 기준(Skill)이 됩니다. 군함 데이터는 기밀이라 같은 해운 도메인의 상선 공개 데이터로 대입했습니다.

### 해결

B/L 번호와 판매 예정일을 넣으면, 선박을 식별하고 신호를 판정해 3단계 판정과 할 일, 근거를 돌려줍니다. 확정할 수 없으면 판정하지 않고 되묻습니다. 모든 판정에 출처와 조회 시각이 붙습니다.

```
입력   B/L 번호 + 판매 예정일 10/20

출력   주의
        근거  AIS ETA 10/14 vs 해수부 입항예정 10/15 09:00 → 12시간 넘게 차이
              해수부 관제 정보를 우선해 신뢰 ETA 10/15, 판매 예정일까지 여유 5일
        할 일 10/13에 다시 확인. 입항예정이 10/18 이후로 밀리면 판매 일정 조정
        통관  "입항 전" 단계, 입항 후 수입신고 → 심사 → 수리 순서
        근거 카드  ShipFinder 위치 (조회 시각) · 해수부 입항예정 (조회 시각) · UNI-PASS (조회 시각)

되묻기 선명 "TEST PAN"(가상) 후보 3척, 국적·목적지로도 확정 불가
        → 판정 없이 "항차 번호나 포워더가 알려준 ETA를 알려주세요"
```

(위 출력은 형식 예시입니다. 실제 값은 조회 결과에 따라 달라집니다.)

| 판정 | 대표 상황 |
|---|---|
| 긴급 | 정박 24시간+, 목적지가 부산 아님, 통관 검사 지정, 신뢰 ETA가 판매 예정일을 넘김 |
| 주의 | 신호 하나 triggered인데 여유 일수 남음 |
| 순항 | 모든 신호 clear, ETA 근거 2개 이상 일치 |
| 판정 보류 | 선박 식별 불확정 또는 위치 없음 → 물을 것 1개 이상 |

유사 서비스(트레드링스)와 다른 점은 **선박 식별 되묻기**와 **신호 상충 해석** 둘입니다. 조회한 배가 내 배라고 전제하지 않고, ETA 확률 범위 대신 왜 못 믿는지 근거를 보여줍니다. 비교 전체는 [PRD 3장](./docs/Marvia_PRD.md)에 있습니다.

**만들지 않는 것:** 항공·육상·부산 외 항만, 창고 수령일 예측, 세액·통관 가부 판단, 결제. (10-06 변경: 알림은 카카오톡 "나에게 보내기"로, 서류는 사진에 더해 PDF로도 만들었다. 이메일·푸시 알림과 알림톡은 만들지 않는다.)

### 설계 원칙

- **판정은 2층입니다.** 1층은 코드가 신호 7종(위치 6시간 끊김, AIS ETA와 해수부 예정 12시간 차이, 부산 인근 24시간 정박, 목적지 변경·깨짐, 항해상태·속도 불일치, 통관 검사·보류, 신뢰 ETA가 판매 예정일을 넘김)을 triggered / clear / unknown으로 판정합니다. 2층은 LLM이 신호가 서로 어긋날 때 어느 출처를 왜 믿는지 정하고 판정합니다.
- **숫자는 코드가 계산합니다.** 여유 일수, 거리, freshness는 코드가 계산하고 LLM은 덮어쓰지 못합니다. 임계값은 `skills/` 문서 프론트매터가 원본입니다.
- **코드가 LLM을 막는 울타리가 있습니다.** 위치가 오래됐으면 "현재 위치" 표현 금지, 식별 불확정이면 판정 금지, 근거에 없는 숫자 거부 등 출력 검증 규칙(V1~V15)을 두고, 위반하면 재시도 3단계 후 폴백합니다. 등급(순항·주의·긴급)은 코드의 판정 표가 정하고 LLM은 설명을 씁니다.
- **지식은 RAG가 아니라 Skill 문서로, 데이터는 MCP 도구로 가져옵니다.** LangGraph와 RAG는 쓰지 않습니다.
- **B/L은 LLM에 넘기지 않습니다.** UNI-PASS는 코드가 직접 조회하고, 중량 등 판정에 필요 없는 필드는 LLM과 DB에 넣지 않습니다. 컨테이너 번호는 `[CNTR1]` 같은 가린 표시로만 LLM에 줍니다. 품명(goods_name)은 10-06부터 저장하고 채팅 에이전트 LLM에는 주지만 판정 LLM에는 주지 않습니다. 트레이스에서도 B/L을 마스킹합니다.

### 처리 흐름

```
브라우저 (B/L + 판매 예정일)
  ▼
web/   Next.js 16 (Railway marvia-web) · 서버 비밀 키 없음
  ▼
backend/app/   FastAPI (Railway marvia-api) · POST /api/agent
  │    1 validate    B/L 형식, 판매 예정일(선택) 검증     [코드]
  │    2 customs     UNI-PASS 조회 → 선명·국적·통관 단계  [코드]
  │    3 identify    선박 후보 1척이면 확정               [코드]
  │                  여럿이면 판단, 확정 불가면 되묻기     [LLM]
  │    4 collect     위치·입항예정·남은 거리              [MCP 도구]
  │    5 signals     1층 신호 6종                         [코드]
  │    6 margin      판매 예정일까지 여유 일수             [코드]
  │    7 judge       2층 판정·할 일·통관 해설             [LLM]
  │    8 validate    출력 검증 규칙, 위반 시 재시도 3회    [코드]
  │  모든 단계 → Langfuse 트레이스
  ▼
mcp_server/  FastMCP /mcp → ShipFinder · 해수부 공공데이터 · searoute
  ▼
AgentResponse (ok | partial | insufficient | failed)
  ▼
화면: 판정 · 할 일 · 위치 · 통관 해설 · 하역 장소 · 근거 카드
```

채팅(`POST /api/chat`)은 위 흐름의 앞에 붙은 자연어 창구입니다. B/L이 담긴 문장이면 같은 판정 흐름을 부르고, 대화 목록·기억·지켜보기·카카오톡 알림도 이 창구와 `/api/*` 라우터가 맡습니다.
단계별 입출력과 실패 처리는 [docs/Marvia_SDD.md](./docs/Marvia_SDD.md) 4절과 8절에 있습니다.

---

## 3. 디렉토리 구조

10-06 기준 실제 레포 구조입니다. 처음 계획(SDD 1.1)의 `app/`, `eval/`은 각각 `backend/app/`, `evals/`로 옮겨 만들었습니다.

```
.
├── README.md             프로젝트 소개, 실행법 (이 파일)
├── CLAUDE.md · AGENTS.md AI 코딩 도구 작업 지침
├── EVAL_REPORT.md        베이스라인 대비 지표 (제출물)
├── Dockerfile            멀티스테이지 (base / app / worker). 로컬 compose용
├── Dockerfile.railway    Railway 배포용 API 이미지 (app 단계만)
├── docker-compose.yml    api(/mcp 포함) + worker + postgres 16
├── .env.example          필요한 키 목록 (값 없음)
│
├── backend/
│   ├── requirements.txt · requirements-doc.txt (서류 사진 OCR, app 이미지에만)
│   ├── app/
│   │   ├── main.py        앱 생성, 라우터 등록, /health, 기동 때 마이그레이션 자동 적용
│   │   ├── auth.py · crypto.py   Supabase 로그인 토큰 확인, B/L·개인정보 암호화
│   │   ├── routers/       agent, chat, conversations, document, history, memory, profile,
│   │   │                  account, admin, kakao, watch, cargo_sheet
│   │   ├── schemas/       agent, signals, customs, document, memory (계약 C1~C5)
│   │   ├── services/      customs, identify, signals, verdict, llm, validate, evidence, chat,
│   │   │                  memory, watch, kakao, quota, referrals, operators 등 (파일 목록은 폴더 참고)
│   │   ├── clients/       shipfinder, mof, kakao, supabase_admin, replay, cache, retry
│   │   ├── observability/ Langfuse 트레이스, 구조화 로그
│   │   ├── db/migrations/ 001~022 SQL. 서버가 켜질 때 DATABASE_URL이 있으면 순서대로 자동 적용
│   │   └── prompts/       Langfuse에서 못 가져올 때 쓰는 프롬프트 사본 10개
│   └── tests/             pytest (키 없이 돈다)
│
├── mcp_server/           FastMCP. 선박 후보·실시간 위치·입항 일정·남은 거리 도구 4개 (tools/)
├── skills/               ais-reliability, customs-stages, port-busan, cargo-verdict, referrals
├── worker/               collector.py(위치·입항 실적 수집), watch.py(지켜보는 화물 재판정), run.py
├── evals/                평가셋 30건(dataset.jsonl)·서류 12건, fixtures/(재생 파일), results/, 실행기·채점
├── scripts/              손으로 돌리는 스크립트 (make_demo, demo_live, mcp_check, langfuse_evidence 등)
├── web/                  Next.js 16 (Railway marvia-web)
│   ├── app/              화면 경로 /, /watch, /cargo, /history, /settings(+kakao), /admin, /metrics, /about
│   ├── components/       화면 부품 · lib/ api·auth·basemap · styles는 app/styles/*.css
│   └── public/basemap/   미리 구워 둔 지도 타일 (외부 타일 서버 없이 지도가 뜬다)
└── docs/
    ├── Marvia_PRD.md     기획서
    ├── Marvia_SDD.md     설계 기준 문서
    ├── Marvia_개발_작업_리스트.md  작업 묶음 A~G, 상태
    ├── SCAFFOLD.md       처음 받은 스캐폴드 설명(보존용)
    ├── ERD.md · release_manifest.json · prompt_versions.md
    ├── evidence/         Langfuse 집계, MCP 연결 캡처
    └── specs/            기능 Spec
```

---

## 4. 실행

### 한 줄로 띄우기

```bash
git clone https://github.com/aihuman-7th/proj2-5.git && cd proj2-5
cp .env.example .env     # 키를 채운다 (아래 표 참고)
docker compose up        # api :8000 (/api/agent, /mcp), worker, postgres
```

DB 표(마이그레이션 001~022)는 서버가 켜질 때 `DATABASE_URL`이 있으면 자동으로 만들어진다(`backend/app/main.py` → `db.apply_migrations`). 따로 손으로 돌릴 SQL은 없다. 배포 DB는 Supabase(운영·개발), 로컬 compose는 postgres 16이다.

worker는 `WORKER_SCHEDULE=off`(기본)이면 안내 한 줄을 남기고 바로 끝난다(`Exited (0)`). 고장이 아니다. 주기 수집은 `on`으로 켠다.

뜨면 이렇게 확인한다.

```bash
curl http://localhost:8000/health        # {"status":"ok","db":"ok"}. DB가 끊기면 503
open http://localhost:8000/docs          # API 문서
```

한글 경로에서는 Docker BuildKit이 죽는다. 그때는 `DOCKER_BUILDKIT=0 docker compose build` 후에 올린다.

### 키 없이 데모 13건 (10분 재현)

키를 하나도 넣지 않고 순항·주의·긴급, 되묻기, 반출 완료, 실패를 끝까지 돌려 본다. 외부 API 응답은 가공값 재생 파일(`evals/fixtures/replay/`), 판정 LLM은 녹화 답이다.
라이브 시연용 모의 화물 10건(`DEMO...`)과 평가셋 데모 3건(`TESTBL..`)이다. 모든 B/L·선박·포워더·컨테이너는 가공값이다.

```bash
cp .env.example .env
# .env에서 REPLAY_MODE=false 를 REPLAY_MODE=true 로 바꾼다. 다른 칸은 비워 둔다
docker compose up -d --build
docker compose exec api python -m scripts.make_demo      # 데모 재생 파일을 지금 시각 기준으로 만든다
```

`make_demo`가 B/L 번호와 넣을 판매 예정일을 표로 보여 준다. 판매 예정일은 실행한 날에 따라 달라진다(아래 `<판매일>`). 화면 예시 메뉴는 오늘 기준 날짜를 알아서 채운다.

라이브 데모 10건 (시나리오는 `scripts/demo_live.py`의 `SPECS`, 펼친 문항은 `evals/fixtures/demo_live.jsonl`)

| B/L | 시나리오 | 켜지는 신호 | 기대 결과 |
|---|---|---|---|
| `DEMOQD2610001` | 칭다오에서 황해 항해 중, 여유 9일 | 없음 | `ok` · 순항(`fine`) |
| `DEMOSH2610002` | AIS ETA와 입항 예정 18시간 차이, 여유 6일 | `eta_conflict` | `ok` · 주의(`watch`) |
| `DEMONB2610003` | 도착 예정이 판매 예정일보다 2일 늦음 | `sales_date_exceeded` | `ok` · 긴급(`act`) |
| `DEMOHC2610004` | 입항·반입 뒤 세관 검사 지정 | `customs_hold` | `ok` · 긴급(`act`) |
| `DEMOTJ2610005` | 부산 30해리 안에서 0.2노트로 30시간 대기 | `anchor_wait` | `ok` · 긴급(`act`) |
| `DEMODL2610006` | 마지막 위치 수신이 10시간 전, 여유 7일 | `position_stale` | `ok` · 주의(`watch`) |
| `DEMOKH2610007` | AIS 목적지가 모지(JPMOJ), 여유 8일 | `dest_changed` | `ok` · 주의(`watch`) |
| `DEMOHP2610008` | 같은 이름 배 2척 | 없음 | `insufficient` 되묻기, 배를 고르면(`resolved_mmsi`) 순항 |
| `DEMOSH2610009` | 입항·수입신고 수리, 컨테이너 3개, 포워더 빈 칸, 여유 5일 | 없음 | `ok` · 순항(`fine`) |
| `DEMOQD2610010` | 반출신고까지 끝난 화물 | (판정 안 함) | `ok` · 순항(`fine`) |

평가셋 데모 3건

| B/L | 시나리오 | 기대 결과 |
|---|---|---|
| `TESTBL01` | 정상 | `ok` · 순항(`fine`), 여유 4일 |
| `TESTBL04` | 되묻기 | `insufficient` · 같은 이름 배 2척, 항차나 포워더 입항 예정일을 묻는다 |
| `TESTBL26` | 실패 | `partial` · 위치 조회 권한 없음, 판정 보류 |

```bash
curl -s -X POST localhost:8000/api/agent -H 'content-type: application/json' \
  -d '{"bl_no":"TESTBL01","bl_type":"HOUSE","sale_due_date":"<판매일>","session_id":"demo"}'
```

다른 B/L도 `bl_no`만 바꿔 같은 명령으로 부른다. `/docs` 화면에서 넣어 봐도 된다. 라이브 데모의 판매 예정일은 `make_demo` 표에 나온 날짜다.

알아 둘 것

- 판매 예정일은 선택이다. 비우면 정상 건은 여유 일수 없이 순항과 "판매 예정일을 넣으면 여유까지 볼 수 있다"는 안내가 나온다. 단 `DEMONB2610003`은 판매 예정일이 있어야 긴급이 나온다
- 녹화 답은 평가셋 `TESTBL01` 입력에만 맞다. 판매 예정일을 다른 날짜로 넣거나 라이브 데모 10건을 부르면 녹화 답을 쓰지 않고 `partial`로 끝난다. 등급은 판정 표가 정해서 그대로 나오고, "설명 문장은 만들지 못했습니다" 안내가 붙는다. 틀린 설명을 그럴듯하게 보이지 않게 한 것이다
- `.env`에 `LLM_MODEL`를 넣으면 같은 데모를 진짜 LLM이 판정한다 (녹화 답을 쓰지 않는다)
- 위치 수신 시각이 "만든 시각 30분 전"이라 약 5시간 반 뒤에는 오래된 위치가 된다. 재생 모드 서버는 4시간마다 스스로 다시 만들고, 직접 돌릴 때는 `make_demo`를 다시 돌린다
- 새 시나리오는 `scripts/demo_live.py`의 `SPECS`에 dict 하나를 더하고 `python -m scripts.demo_live`로 jsonl을 다시 쓴다
- Docker 없이: `python -m scripts.make_demo` 후 `REPLAY_MODE=true uvicorn backend.app.main:app --port 8000`

### 키

| 키 | 어디서 | 없으면 |
|---|---|---|
| `SHIPFINDER_KEY` | ShipFinder 스타터 키 (팀 보유) | 선박 검색·위치 조회 불가 |
| `DATA_GO_KR_KEY` | 공공데이터포털. 해수부 관제정보·선박운항정보 활용신청 | 입항 예정·실적 조회 불가 |
| `UNIPASS_KEY` | 관세청 UNI-PASS 오픈API | B/L 조회 불가 |
| `OPENROUTER_API_KEY` | openrouter.ai | 판정 불가 |
| `LLM_MODEL` | 서비스 모델 이름 (예: `openai/gpt-4o-mini`). 전 이름 `MODEL_A` | `partial`: 판정 표 등급만 나오고 설명 문장 없음 (데모는 녹화 답) |
| `MEMORY_MODEL` | 화물 비서 기억 뽑기 모델 | 기억 뽑기를 건너뛴다 |
| `DAILY_TOKENS_PER_USER` | 1명당 하루 LLM 토큰 한도 (예시 기본 100000, 비우거나 0이면 막지 않음) | 한도 없음 |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | Langfuse 프로젝트 설정 | 트레이스 없음 |
| `MCP_TOKEN` | 아무 랜덤 문자열 | /mcp가 인증 없이 열린다 |
| `SUPABASE_URL` | Supabase 프로젝트 주소 (비밀값 아님) | 로그인이 꺼진다. 데모·채점은 비워 둔다 |
| `SUPABASE_SECRET_KEY` | Supabase 대시보드 API Keys | 회원 탈퇴 불가 |
| `BL_ENCRYPTION_KEY` | 아래 명령으로 한 번 만들고, 모든 환경에 같은 값 | B/L 원본을 저장하지 않는다 |
| `PII_ENCRYPTION_KEY` | 회원 정보·운영자 이메일 열쇠 (B/L 열쇠와 별도). 팀이 같은 값을 공유 | 회원 정보를 다시 열 수 없다 |
| `KAKAO_REST_API_KEY` / `KAKAO_CLIENT_SECRET` / `KAKAO_REDIRECT_URI` | 카카오 디벨로퍼스 | 카카오톡 알림 연결 불가 |
| `REPLAY_MODE` | `true`면 외부 API 대신 `evals/fixtures/replay/`를 읽는다 (기본 `false`) | |

**`SUPABASE_URL`을 채우면 로그인이 필수가 된다.** `/api/agent` 요청에 `Authorization: Bearer <Supabase 로그인 토큰>`이 없으면 401 `{"detail":"로그인이 필요합니다"}`이다. 키 없이 돌려 볼 때는 비워 둔다.

`MCP_TOKEN`은 이렇게 만든다.

```bash
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

`BL_ENCRYPTION_KEY`는 이렇게 만든다. 잃어버리면 저장된 B/L을 다시 열 수 없다.

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 로컬에서 직접 돌리기 (Docker 없이)

```bash
python -m venv .venv && .venv/bin/python -m pip install -r backend/requirements.txt -r backend/requirements-doc.txt
.venv/bin/python -m uvicorn backend.app.main:app --port 8000     # API + MCP(/mcp)
```

윈도우는 `.venv/bin/python` 대신 `.venv\Scripts\python`이다.

### 화면(web/) 로컬 실행

```bash
cd web && npm install && npm run dev     # :3000. Node 20.9 이상
```

`web/.env`의 `NEXT_PUBLIC_API_BASE`를 비우면 백엔드 없이 `web/lib/fixtures` 가공 데이터로 뜨고, `http://localhost:8000`을 넣으면 위 API 서버에 붙는다. 키 목록은 `web/.env.example`, 화면 설명은 `web/README.md`다.

### MCP 서버 확인

MCP 서버는 API 서버 안의 `/mcp` 경로다. 서버 하나, 배포 주소 하나로 `/api/agent`(화면용)와 `/mcp`(MCP 클라이언트용)가 같이 열린다.
`MCP_TOKEN`을 채우면 `Authorization: Bearer <MCP_TOKEN>` 없이는 401이다. 배포에서는 반드시 채운다.

```bash
python -m scripts.mcp_check http://localhost:8000/mcp   # 연결과 도구 4종 목록
python -m scripts.mcp_demo                              # 도구 4종 실제 호출
python -m scripts.mcp_auth_check                        # 토큰 없으면 401
```

우리 서비스(`/api/agent`)도 도구를 `/mcp`를 거쳐 MCP 프로토콜로 부른다(`backend/app/services/mcp_client.py`). Docker 이미지는 `MCP_URL=http://127.0.0.1:8000/mcp`로 같은 서버의 `/mcp`에 HTTP로 붙어 외부 클라이언트와 같은 토큰 인증을 거친다. `MCP_URL`이 없으면(테스트·평가 실행기) 같은 프로세스의 MCP 서버에 메모리로 붙는다. 후속 질문에서는 LLM이 `tools/list`로 받은 읽기 전용 도구를 직접 골라 부른다. 호출마다 Langfuse에 `mcp:<도구>` 관측이 남는다.

도구 4종의 정의는 `mcp_server/tools/*.py`의 함수이고, 등록은 `mcp_server/server.py`의 `create_mcp()`가 루프로 한다(`@mcp.tool` 데코레이터를 쓰지 않는다). 읽기 전용 표시와 스레드 실행을 4종에 똑같이 붙이기 위해서다.

### 테스트

```bash
pytest          # 외부 API 키 없이 돈다 (가공 응답으로 대체). 10-06 `pytest --collect-only`로 2063건 수집 확인
```

PR 때는 GitHub Actions(`.github/workflows/tests.yml`)가 `backend/tests`와 `mcp_server/tests`를 돌린다. 실제 API·LLM을 부르는 평가(`python -m evals.run_eval --config a|b|c`)는 돈이 들어 따로 돌린다.

### 아직 안 되는 것

| 항목 | 상태 |
|---|---|
| 실사용 기록 | 배포 서버는 10-07부터 실제 모드지만 실제 사용자 B/L 판정 기록은 이 리포트에 없다. 같은 날 Railway에서 해수부 API 연결 시간 초과가 나는 것도 원인 미확인 상태다 (EVAL_REPORT 8절) |
| 감시 재판정 주기 가동 | 워커 스케줄(`WORKER_SCHEDULE`)과 감시 재판정(`WATCH_ENABLED`)은 기본 꺼짐이다 |
| 부산 외 항만, 이메일·푸시 알림 | 만들지 않았다 |

### 기술 스택

| 영역 | 사용 |
|---|---|
| Backend | FastAPI, Pydantic v2, Docker, Railway (`marvia-api`) |
| Frontend | Next.js 16, React 19, Railway (`marvia-web`), MapLibre 지도 |
| LLM | OpenRouter (모델 2개 비교, 구조화 출력). `llm.py`에 Vertex(`vertex/` 접두) 경로도 있다 |
| 도구 | FastMCP (Streamable HTTP), ShipFinder, 해수부 공공데이터, searoute |
| 데이터 | Supabase(배포 DB·로그인), 로컬은 PostgreSQL 16 |
| 관측·평가 | Langfuse (트레이스, Prompt, Dataset) |

---

## 5. 지표

실제로 돌린 결과만 적었습니다. 상세와 한계는 [EVAL_REPORT.md](./EVAL_REPORT.md), 원본은 `evals/results/`.

평가셋 30건(정상 8 · 경계 14 · 실패 유도 8)은 사람이 정답을 적었고, 입력(B/L, 선박, 위치, 통관 단계, 판매 예정일)은 모두 실제 응답과 형식만 같은 가공값입니다. 외부 API는 재생 파일로 대신해 키 없이 돕니다. 신호 상충 5건은 PRD 상충 사례를 옮긴 B03~B07입니다.

| 항목 | (a) 규칙만 | (b) openai/gpt-4o-mini (서비스) | (c) qwen/qwen3-235b-a22b-2507 |
|---|---|---|---|
| 측정 | 1회, 10-01 16:31 | 5회, 10-02 11:41~11:56 | 1회, 10-02 11:58 |
| 판정 정확도 (verdict_accuracy) | 1.0 | 1.0 (5회 모두) | 1.0 |
| 긴급 재현율 (act_recall) | 1.0 | 1.0 (5회 모두) | 1.0 |
| 신호 상충 5건 정답 수 | 5/5 | 5/5 (5회 모두) | 5/5 |
| 선박 오확정 건수 | 2 (B01·B12, 동명 선박 수정 `6c737eb` 전 측정) | 0 (5회 모두) | 0 |
| 출력 계약 준수율 | 최종 응답 1.0 (LLM 출력 없음) | 최종 응답 1.0, LLM 출력 단위 98.2% (112개 중 110개) | 최종 응답 1.0, LLM 출력 단위 64.7% (34개 중 22개) |
| 통관 해설 (LLM-as-judge, 채점 gemini-2.5-flash) | 해당 없음 | 13/21 ~ 17/21 (회차별. 측정 커밋에서는 관세사 확인 여부를 LLM이 정해 지금 코드보다 불리, EVAL_REPORT 4-1) | 20/21 |
| p50 / p95 지연 | 0.05초 / 0.65초 | 3.5초 / 5.5초 (150건) | 8.4초 / 30.4초 |
| 요청당 비용 | $0 (LLM 없음) | $0.000365 (5회 평균) | $0.003791 |

등급은 코드 판정 표가 정해서 (a)도 등급은 다 맞힙니다. (b)와 (c)는 판정 칸이 같고, (b)를 고른 이유는 출력 계약 준수율과 비용·지연입니다 (EVAL_REPORT 5절). 지연은 재생 파일 기준이라 실제 외부 호출 시간이 빠져 있습니다. Langfuse 도착 기록 집계는 [docs/evidence/langfuse_summary.md](./docs/evidence/langfuse_summary.md).

**10-06 갱신:** 위 표는 EVAL_REPORT 5절의 10-02 측정이다. 10-06에는 판정 프롬프트(judge) 9 → 10으로 바꿔 같은 코드·모델(gpt-4o-mini)로 다시 쟀고, 통관 해설이 4/20(0.20)에서 20/20(1.0)이 됐다(1회씩, EVAL_REPORT 4절 5·6번). 배포 서비스 모델은 `docs/release_manifest.json` 기준 `google/gemini-3.5-flash-lite`이며, 아래는 EVAL_REPORT에 아직 없고 결과 파일에서 그대로 읽은 10-06 값이다.

| 결과 파일 (`evals/results/`) | 구성 | exact | 판정 정확도 | act 재현율 | 선박 오확정 | 통관 해설 | p50 / p95 | 요청당 비용 |
|---|---|---|---|---|---|---|---|---|
| `a_20261006_2158.json` | (a) 규칙만 | 29/30 | 1.0 | 1.0 | 0 | 해당 없음 | 0.03초 / 0.08초 | $0 |
| `b_20261006_1739.json` | (b) openai/gpt-4o-mini | 30/30 | 1.0 | 1.0 | 0 | 0.95 (20건) | 4.0초 / 7.1초 | $0.000696 |
| `b_20261006_2306.json` | (b) google/gemini-3.5-flash-lite | 30/30 | 1.0 | 1.0 | 0 | 1.0 (20건) | 2.0초 / 7.4초 | $0.0022 |

**10-07 Vertex 실행:** `b_20261007_0935.json`, (b) `vertex/google/gemini-3.5-flash-lite`, 프롬프트 judge 10 · judge-eval 3 · follow-up 8. 서비스가 쓰는 OpenRouter가 아니라 Vertex AI로 불러서 쟀으므로 아래 지연과 토큰은 Vertex에서 잰 값이다. 같은 코드(main `2a6fa7a`, `git_commit`의 `-dirty`는 `.env.example` 수정 때문), 1회, 결과 파일에서 그대로 읽은 값이다.

| 결과 파일 | exact | 판정 정확도 | act 재현율 | 선박 오확정 | 통관 해설 | p50 / p95 | LLM 호출 / 입력 토큰 (캐시) / 출력 토큰 | 비용 |
|---|---|---|---|---|---|---|---|---|
| `b_20261007_0935.json` | 30/30 | 1.0 | 1.0 | 0 | 1.0 (20건) | 1.8초 / 4.8초 | 29 / 231,184 (16,146) / 5,380 | 금액 미기록 (Vertex라 토큰만) |

게이트 4개 통과. 한계: F08에서 judge가 `bad_format`을 3번 내고 포기했다. 등급이 코드 판정 표에서 나와 문항은 맞았다 (EVAL_REPORT 5절).

위 10-06 세 파일은 게이트 4개(act 누락, 선박 오확정, 스키마 95%, 주입 오작동) 통과이고 1회씩 쟀습니다. `a_...2158`과 `b_...2306`의 `git_commit`에는 `-dirty`가 붙어 커밋 전 작업 트리에서 돌렸고, `b_...1739`는 `git_commit`이 비어 있습니다.

**배포 게이트:** act 누락 1건 이상 · 선박 오확정 1건 이상 · 스키마 통과 95% 미만 · 주입 오작동 1건 이상 중 하나라도 걸리면 배포하지 않습니다.

---

## 6. 협업 규칙

1. **`main`에 직접 push 금지.** 모든 변경은 브랜치 → PR로만 합칩니다.
2. 브랜치명은 `feat/{작업내용}`, 버그 수정은 `fix/{내용}`.
3. PR은 **조원 1명 이상의 approve를 받은 뒤** merge합니다.
4. **제출물은 마감 시점의 `main`입니다.** 마감 시각에 강사가 태그를 일괄 생성하며, 태그 이후 커밋은 평가 대상이 아닙니다.
5. **커밋은 본인 계정으로.** 함께 작업했다면 커밋 메시지에 `Co-authored-by:`를 추가합니다.
6. 다른 사람 담당 묶음을 고칠 때는 PR로 하고 먼저 알립니다. 계약(스키마)을 바꿀 때는 SDD 3절을 먼저 고친 뒤 전원에게 알립니다.
7. 다른 조 저장소는 참고만 하고 복사 제출은 하지 않습니다.

### 작업 흐름

```bash
git switch main && git pull
git switch -c feat/mcp-live-position

git add .
git commit -m "feat: 실시간 위치 MCP 도구"
git push -u origin feat/mcp-live-position
# GitHub에서 PR 생성 → 조원 리뷰 → approve 후 merge
```

### 충돌이 났을 때

```bash
git switch main && git pull
git switch feat/내브랜치
git merge main          # 충돌 지점이 파일에 표시됨
# <<<<<<< ======= >>>>>>> 사이에서 남길 내용 선택 후 저장
git add . && git commit
git push                # PR이 자동 갱신됨
```

## 7. 시크릿 규칙

- API 키·비밀번호는 **`.env` 파일에만** 둡니다. `.env`는 `.gitignore`에 등록되어 있습니다.
- 코드에 키를 직접 적지 않습니다. 이 org는 상호 공개라 **커밋된 키는 7기 전원이 볼 수 있습니다.**
- 모든 push는 **Secret Scan**(GitHub Actions)이 검사합니다. 실패하면 키가 커밋된 것이니 즉시 강사에게 알리고 **해당 키를 재발급**합니다. 히스토리에서 지워도 유출로 간주합니다.
- 실제 B/L 번호와 UNI-PASS 응답 원본도 커밋하지 않습니다. 평가셋에는 가상 B/L만 씁니다.
- 필요한 키 목록은 `.env.example`에 값 없이 적어 공유합니다.


## 8. 데이터 출처와 라이선스

| 출처 | 쓰는 곳 | 라이선스·이용 조건 |
|---|---|---|
| [searoute-py](https://github.com/genthalili/searoute-py) (Gent Halili) | 부산항까지 남은 해상 거리 (`estimate_distance`) | Apache-2.0 |
| [Eurostat SeaRoute](https://github.com/eurostat/searoute) | searoute-py에 들어 있는 항로 네트워크 데이터의 원본 | EUPL-1.2 |
| [pycountry](https://github.com/pycountry/pycountry) | 세관 국적 코드(KR)와 ShipFinder 국적 이름(Korea, Republic of) 대조 (선박 식별) | LGPL-2.1. 수정 없이 import만 한다 |
| ShipFinder API | 선박 후보·실시간 위치 | 내부 연구 목적만. 서면 동의 없이 복사·게시 금지 → 실제 응답은 레포에 넣지 않고 DB에만 둔다 |
| 관세청 UNI-PASS OpenAPI | 화물통관진행정보 | 조회 정보의 복제·타인 제공 금지 (이용약관 15조③) → 실제 응답은 레포에 넣지 않는다 |
| 해양수산부 공공데이터 (관제정보·선박운항정보) | 입항 예정·실적, 접안 시설 | 공공데이터포털 이용허락범위 제한 없음 |

레포의 테스트용 응답(`evals/fixtures/`)은 실제 응답과 형식만 같은 가공값이다.
