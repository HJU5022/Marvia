# Marvia (마르비아)

**B/L 하나로 내 화물이 제때 오는지 판정하고, 왜 그런지 근거까지 보여준다.**

KDT AI Human 7기 2차 팀 프로젝트 · 5조 · [유형 1] 도메인 특화 LLM 서비스

| | |
|---|---|
| 서비스 | (Vercel URL) |
| Agent API | (Cloud Run URL) · `GET /health` · `POST /api/agent` |
| MCP | (Cloud Run URL) · `/mcp` (Bearer 토큰) |
| 기획 | [docs/Marvia_PRD.md](./docs/Marvia_PRD.md) |
| 설계 | [docs/Marvia_SDD.md](./docs/Marvia_SDD.md) |
| 작업 분담 | [docs/Marvia_개발_작업_리스트.md](./docs/Marvia_개발_작업_리스트.md) |
| 지표 | [EVAL_REPORT.md](./EVAL_REPORT.md) |

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
| 9/24~27 | (추석) 워커 가동 유지, MCP 뼈대, Langfuse 연결, Cloud Run 빈 배포, Skill 초안 |
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

출력   지켜볼 것
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
| 지금 조치 | 정박 24시간+, 목적지가 부산 아님, 통관 검사 지정, 신뢰 ETA가 판매 예정일을 넘김 |
| 지켜볼 것 | 신호 하나 triggered인데 여유 일수 남음 |
| 괜찮음 | 모든 신호 clear, ETA 근거 2개 이상 일치 |
| 판정 보류 | 선박 식별 불확정 또는 위치 없음 → 물을 것 1개 이상 |

유사 서비스(트레드링스)와 다른 점은 **선박 식별 되묻기**와 **신호 상충 해석** 둘입니다. 조회한 배가 내 배라고 전제하지 않고, ETA 확률 범위 대신 왜 못 믿는지 근거를 보여줍니다. 비교 전체는 [PRD 3장](./docs/Marvia_PRD.md)에 있습니다.

**만들지 않는 것:** 항공·육상·부산 외 항만, 창고 수령일 예측, 세액·통관 가부 판단, 알림톡·결제.

### 설계 원칙

- **판정은 2층입니다.** 1층은 코드가 신호 6종(위치 6시간 끊김, AIS ETA와 해수부 예정 12시간 차이, 부산 인근 24시간 정박, 목적지 변경·깨짐, 항해상태·속도 불일치, 통관 검사·보류)을 triggered / clear / unknown으로 판정합니다. 2층은 LLM이 신호가 서로 어긋날 때 어느 출처를 왜 믿는지 정하고 판정합니다.
- **숫자는 코드가 계산합니다.** 여유 일수, 거리, freshness는 코드가 계산하고 LLM은 덮어쓰지 못합니다. 임계값은 `skills/` 문서 프론트매터가 원본입니다.
- **코드가 LLM을 막는 울타리가 있습니다.** 위치가 오래됐으면 "현재 위치" 표현 금지, 식별 불확정이면 판정 금지, 근거에 없는 숫자 거부 등 출력 검증 7규칙을 두고, 위반하면 재시도 3단계 후 폴백합니다.
- **지식은 RAG가 아니라 Skill 문서로, 데이터는 MCP 도구로 가져옵니다.** LangGraph와 RAG는 쓰지 않습니다.
- **B/L은 LLM에 넘기지 않습니다.** UNI-PASS는 코드가 직접 조회하고, 품명·중량 등 판정에 필요 없는 필드는 LLM과 DB에 넣지 않습니다. 트레이스에서도 B/L을 마스킹합니다.

### 처리 흐름

```
브라우저 (B/L + 판매 예정일)
  ▼
web/   Next.js (Vercel) · 키 없음
  ▼
app/   FastAPI (Cloud Run) · POST /api/agent
  │    1 validate    B/L 형식, 판매 예정일 검증          [코드]
  │    2 customs     UNI-PASS 조회 → 선명·국적·통관 단계  [코드]
  │    3 identify    선박 후보 1척이면 확정               [코드]
  │                  여럿이면 판단, 확정 불가면 되묻기     [LLM]
  │    4 collect     위치·입항예정·남은 거리              [MCP 도구]
  │    5 signals     1층 신호 6종                         [코드]
  │    6 margin      판매 예정일까지 여유 일수             [코드]
  │    7 judge       2층 판정·할 일·통관 해설             [LLM]
  │    8 validate    출력 검증 7규칙, 위반 시 재시도 3회   [코드]
  │  모든 단계 → Langfuse 트레이스
  ▼
mcp_server/  FastMCP /mcp → ShipFinder · 해수부 공공데이터 · searoute
  ▼
AgentResponse (ok | partial | insufficient | failed)
  ▼
화면: 판정 · 할 일 · 위치 · 통관 해설 · 하역 장소 · 근거 카드
```

단계별 입출력과 실패 처리는 [docs/Marvia_SDD.md](./docs/Marvia_SDD.md) 4절과 8절에 있습니다.

---

## 3. 디렉토리 구조

SDD 1.1절 기준 목표 구조입니다. 현재 레포는 스캐폴드(`backend/`, `evals/`) 단계이고 이 구조로 옮기는 중입니다.

```
.
├── README.md             프로젝트 소개, 실행법 (이 파일)
├── CLAUDE.md · AGENTS.md AI 코딩 도구 작업 지침
├── EVAL_REPORT.md        베이스라인 대비 지표 (제출물)
├── Dockerfile            멀티스테이지 하나 (app / mcp / worker)
├── docker-compose.yml    app + mcp + worker + postgres
├── .env.example          필요한 키 목록 (값 없음)
│
├── app/                  FastAPI (Cloud Run)
│   ├── main.py           앱 생성, 라우터 등록
│   ├── routers/          /api/agent, /health
│   ├── schemas/          요청·응답·신호·통관 스키마 (계약 C1~C5)
│   ├── services/         customs, signals, identify, llm, validate, evidence
│   ├── clients/          ShipFinder, 해수부, searoute
│   └── observability/    Langfuse 트레이스, 구조화 로그
│
├── mcp_server/           FastMCP. 선박 후보·실시간 위치·입항 일정·남은 거리 도구 4개
├── skills/               AIS 신뢰도, 통관 단계, 부산항 판단 기준
├── worker/               평가셋 라벨용 선박 위치·입항 실적 수집
├── eval/                 평가셋 30건, 베이스라인, 채점
├── web/                  Next.js (Vercel)
└── docs/
    ├── Marvia_PRD.md     기획서
    ├── Marvia_SDD.md     설계 기준 문서
    ├── Marvia_개발_작업_리스트.md  작업 묶음 A~E, 기한
    ├── SCAFFOLD.md       폴더별 채울 내용
    └── specs/            기능 Spec (AGENTS.md 참고)
```

---

## 4. 실행

### 한 줄로 띄우기

```bash
git clone https://github.com/aihuman-7th/proj2-5.git && cd proj2-5
cp .env.example .env     # 키를 채운다 (아래 표 참고)
docker compose up        # api :8000, mcp :8001, worker, postgres
```

뜨면 이렇게 확인한다.

```bash
curl http://localhost:8000/health        # {"status":"ok"}
open http://localhost:8000/docs          # API 문서
```

한글 경로에서는 Docker BuildKit이 죽는다. 그때는 `DOCKER_BUILDKIT=0 docker compose build` 후에 올린다.

### 키

| 키 | 어디서 | 없으면 |
|---|---|---|
| `SHIPFINDER_KEY` | ShipFinder 스타터 키 (팀 보유) | 선박 검색·위치 조회 불가 |
| `DATA_GO_KR_KEY` | 공공데이터포털. 해수부 관제정보·선박운항정보 활용신청 | 입항 예정·실적 조회 불가 |
| `UNIPASS_KEY` | 관세청 UNI-PASS 오픈API | B/L 조회 불가 |
| `OPENROUTER_API_KEY` | openrouter.ai | 판정 불가 |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | Langfuse 프로젝트 설정 | 트레이스 없음 |
| `MCP_TOKEN` | 아무 랜덤 문자열 | /mcp가 인증 없이 열린다 |

`MCP_TOKEN`은 이렇게 만든다.

```bash
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

### 로컬에서 직접 돌리기 (Docker 없이)

```bash
python -m venv .venv && .venv/Scripts/python -m pip install -r backend/requirements.txt
.venv/Scripts/python -m uvicorn backend.app.main:app --port 8000     # API
.venv/Scripts/python -m mcp_server.server --port 8001                # MCP 서버
```

### MCP 서버 확인

```bash
python -m scripts.mcp_check http://localhost:8001/mcp   # 연결과 도구 4종 목록
python -m scripts.mcp_demo                              # 도구 4종 실제 호출
python -m scripts.mcp_auth_check                        # 토큰 없으면 401
```

### 테스트

```bash
pytest          # 179건. 외부 API 키 없이 돈다 (저장된 응답으로 대체)
```

### 아직 안 되는 것

| 항목 | 상태 |
|---|---|
| `POST /api/agent` 판정 | 조회까지만 동작한다. LLM 판정(C-6)과 출력 검증(C-7)이 붙으면 verdict가 나온다 |
| `REPLAY_MODE` | 미구현. 지금은 키가 있어야 실제 조회가 된다 |
| 웹 화면 | `web/` 미착수 |
| 평가 실행기 | `evals/run_eval.py` 미착수 |

### 기술 스택

| 영역 | 사용 |
|---|---|
| Backend | FastAPI, Pydantic v2, Docker, Cloud Run |
| Frontend | Next.js 14, Vercel |
| LLM | OpenRouter (모델 2개 비교, 구조화 출력) |
| 도구 | FastMCP (Streamable HTTP), ShipFinder, 해수부 공공데이터, searoute |
| 데이터 | PostgreSQL 16 |
| 관측·평가 | Langfuse (트레이스, Prompt, Dataset) |

---

## 5. 지표

10/8 측정 결과로 채웁니다. 상세는 [EVAL_REPORT.md](./EVAL_REPORT.md).

평가셋 30건은 실제 부산 입항 선박의 위치를 수집하고, 가상 B/L·모의 통관 단계·가상 판매 예정일을 붙여 만듭니다(선박·위치는 실제, 나머지는 시뮬레이션). 핵심은 **신호 상충 5건**에서 LLM이 규칙만 쓴 버전보다 나은지입니다.

| 항목 | (a) 규칙만 | (b) 모델 A | (c) 모델 B |
|---|---|---|---|
| 판정 정확도 (verdict_accuracy) | | | |
| 지금 조치 재현율 (act_recall) | | | |
| 신호 상충 5건 정답 수 | | | |
| 선박 오확정 건수 | | | |
| 출력 계약 준수율 (schema_pass) | | | |
| p50 / p95 지연 | | | |
| 요청당 비용 | | | |

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
| ShipFinder API | 선박 후보·실시간 위치 | 내부 연구 목적만. 서면 동의 없이 복사·게시 금지 → 실제 응답은 레포에 넣지 않고 DB에만 둔다 |
| 관세청 UNI-PASS OpenAPI | 화물통관진행정보 | 조회 정보의 복제·타인 제공 금지 (이용약관 15조③) → 실제 응답은 레포에 넣지 않는다 |
| 해양수산부 공공데이터 (관제정보·선박운항정보) | 입항 예정·실적, 접안 시설 | 공공데이터포털 이용허락범위 제한 없음 |

레포의 테스트용 응답(`evals/fixtures/`)은 실제 응답과 형식만 같은 가공값이다.
