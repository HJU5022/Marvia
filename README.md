# Converge (컨버지)

**현장이 움직이는 유지보수·배포 작업에서, 담당자가 업체·고객사와 "어디서 몇 시에 만날지" 정하는 일을 문장 하나로 끝내는 에이전트**

KDT AI Human 7기 2차 팀 프로젝트 · 5조

| | |
|---|---|
| 서비스 | (Vercel URL) |
| Agent API | (Cloud Run URL) · `GET /health` · `POST /api/agent` |
| 기획 | [docs/PRD.md](./docs/PRD.md) |
| 설계 | [docs/SDD.md](./docs/SDD.md) · [docs/테이블정의서.md](./docs/테이블정의서.md) |
| 구조 지도 | [CONVERGE.md](./CONVERGE.md) |
| 지표 | [EVAL_REPORT.md](./EVAL_REPORT.md) |

---

## 1. 어떤 프로젝트인가

### 문제

함정 정비 미팅과 SI 야간 배포 집결은 현장이 고정되어 있지 않습니다. 입항 일정에 따라 부두가 바뀌고, 고객사 야간 작업은 출입증·보안서류·인솔 절차를 거쳐야 들어갈 수 있습니다. 집결지와 시각을 가르는 것은 이런 **현장 절차**인데, 기존 지도 앱은 그 절차를 모릅니다. 그래서 담당자는 전화와 카톡으로 30분에서 한 시간을 조율에 씁니다.

두 조원이 각각 함정 정비 담당(6년 2개월), SI 파견 개발자(4년 7개월)로 이 조율을 직접 해왔고, 각자 자기 도메인의 정답을 판정합니다.

### 해결

사용자가 상황을 문장(또는 카톡 캡처)으로 넣으면, 절차와 경로를 함께 계산해 집결 장소·시각·참석자별 출발 시각을 지도 위에 답으로 내놓습니다.

```
입력   "저녁 10시 여의도 고객사 야간 배포. 부장님 강서구, 나 송파구, 둘 다 지하철.
        담당자가 1층에서 보안서류 받고 인솔함. 부장님이 여의도역에서 먼저 만나자는데?"

출력   합류 지점은 여의도역이 아니라 인솔이 시작되는 고객사 1층입니다.
        부장님  21:05 출발 · 지하철 45분 · 1층 도착 21:50
        나      21:15 출발 · 지하철 35분 · 1층 도착 21:50
        인솔 22:00 시작, 10분 전 도착 기준. 작업 종료 후 첫차 05:30
        → 지도에 집결지 핀과 두 사람 경로선
```

| 프리셋 | 현장 | 다루는 절차 |
|---|---|---|
| `ship_maintenance` | 함정 정비 미팅 | 입항 일정, 접안 부두, 출입조치와 위병소 집결, 도착 지연 시 부두 밖 전환, 업체 당일 순회 |
| `si_deploy` | SI 야간 배포·고객사 미팅 | 배포 창, 출입증·보안서류·인솔 지점, 작업 후 첫차 귀가, 고객사 방문 관례 |

### 설계 원칙

- **LLM은 입구와 출구에만 있습니다.** 문장 → 슬롯 JSON 추출(소형 모델), 집결지 순위·근거 판정(대형 모델, 필요할 때만). 소요시간·출발 시각·절차 소요 반영은 전부 코드가 계산합니다.
- **파이프라인은 순차 실행이고 루프가 없습니다.** 단계마다 Langfuse span을 남기고, 모든 외부 호출에 실패 경로가 있습니다.
- **지식은 RAG가 아니라 Skill 문서로, 데이터는 MCP 도구로 가져옵니다.** 규칙값은 `skills/converge/rules/`가 원본입니다.
- **개인정보는 평문으로 저장하지 않습니다.** 참석자 이름·출발지·좌표·경로는 암호화해 저장합니다.

### 처리 흐름

```
브라우저 (지도 + 채팅)
  │  문장 또는 카톡 캡처
  ▼
frontend/  Next.js · app/api/agent 프록시 (키는 여기서 멈춤)
  ▼
backend/   FastAPI · POST /api/agent
  │  services/pipeline.py
  │    0 vision      캡처 → 텍스트              [LLM]
  │    1 extract     텍스트 → 슬롯              [소형 LLM]
  │    2 geocode     지명 → 좌표
  │    3 candidates  집결 후보 (위병소·로비·랜드마크)
  │    4 routes      참석자 × 후보 소요시간
  │    5 rules       절차 소요·전환 조건         [계산]
  │    6 judge       순위·이유                  [대형 LLM, 필요 시]
  │    7 departure   출발 시각 역산              [계산]
  │    8 store       암호화 저장
  │  2·3·4단계는 같은 프로세스의 /mcp 도구를 사용
  ▼
AgentResponse (need_confirm | need_info | done | out_of_scope | failed)
  ▼
지도에 핀·경로선·표
```

자세한 단계별 입출력과 실패 처리는 [docs/SDD.md](./docs/SDD.md) 5절에 있습니다.

---

## 2. 디렉토리 구조

```
.
├── README.md             프로젝트 소개, 실행법 (이 파일)
├── CONVERGE.md           구조 지도. 폴더별 책임과 SDD 절 안내
├── CLAUDE.md · AGENTS.md AI 코딩 도구 작업 지침
├── EVAL_REPORT.md        개선 전후 지표 (제출물)
├── Dockerfile            루트 빌드 (skills/, mcp_server/ 포함)
├── docker-compose.yml    api + db(postgres:16)
├── .env.example          필요한 키 목록 (값 없음)
│
├── backend/              FastAPI (Cloud Run)
│   ├── app/
│   │   ├── main.py       앱 생성, 라우터 등록, /mcp 마운트
│   │   ├── routers/      /api/agent, /health, /api/session
│   │   ├── schemas/      요청·슬롯·결과 스키마 (출력 계약 원본)
│   │   ├── services/     외부와 통신 (LLM, 지도·경로 API, DB)
│   │   ├── domain/       계산만 (규칙 적용, 출발 시각 역산, 모델 라우팅)
│   │   ├── observability/ Langfuse 트레이스
│   │   └── models/       소형 모델(GGUF) 자리, 빌드 시 채워짐
│   ├── db/               테이블 생성 SQL
│   └── tests/            API 키 없이 도는 테스트, fixtures
│
├── mcp_server/           FastMCP. 지도·경로·시각표 API를 MCP 도구 7개로 제공
├── frontend/             Next.js (Vercel). 지도·채팅, 소개 페이지, 공유 링크
├── skills/converge/      현장 규칙(rules/)과 프리셋 2개(presets/)
├── evals/                평가셋 30건, 실행 스크립트
├── finetune/             슬롯 추출용 소형 모델 학습 (배포 이미지에 포함 안 됨)
├── scripts/              타입 생성 등 수동 실행 스크립트
└── docs/
    ├── PRD.md            기획서
    ├── SDD.md            설계 기준 문서
    ├── 테이블정의서.md    DB 테이블·암호화 정의
    ├── planning/         계획서 보완 제출본
    └── evidence/         제출 증거물 (Langfuse, MCP 스크린샷)
```

각 폴더의 책임과 먼저 읽을 가이드(`*_GUIDE.md`)는 [CONVERGE.md](./CONVERGE.md)에 정리돼 있습니다.

---

## 3. 실행

```bash
git clone <repo> && cd <repo>
cp .env.example .env     # 키 채우기
docker compose up        # backend :8000 (/api/agent, /health, /mcp) + db

cd frontend && npm install && npm run dev   # :3000
```

필요한 키는 `.env.example`을 참고하세요. Kakao Local·Kakao Mobility·TMAP·OpenRouter·Langfuse·Supabase.

### 테스트

```bash
pytest backend/tests                                     # API 키 없이 실행
python evals/run_eval.py --dataset evals/dataset.jsonl   # 평가셋
```

### 기술 스택

| 영역 | 사용 |
|---|---|
| Backend | FastAPI, Docker, Cloud Run |
| Frontend | Next.js, Vercel, Kakao Map SDK |
| LLM | OpenRouter (대형), 파인튜닝 소형 모델 (GGUF) |
| 도구 | FastMCP, Kakao Local/Mobility, TMAP |
| 데이터 | PostgreSQL (Supabase), Supabase Auth |
| 관측·평가 | Langfuse (트레이스, Prompt, Dataset) |

---

## 4. 지표

10/8 측정 결과로 채웁니다. 상세는 [EVAL_REPORT.md](./EVAL_REPORT.md).

| 항목 | 개선 전 | 개선 후 |
|---|---|---|
| 슬롯 추출 정확도 | | |
| 집결지 판정 정확도 | | |
| 출력 계약 준수율 | | |
| p50 / p95 지연 | | |
| 요청당 비용 | | |

---

## 5. 팀 (5조)

| 이름 | GitHub | 역할 | 담당 영역 | 한마디 |
|---|---|---|---|---|
| 김승욱 | @seungwook-kim | 조장 · 풀스택 · SI 배포 도메인 | backend/, mcp_server/, skills/ (si_deploy) | 눈 뜨면 코딩하기. |
| 하정운 | @HJU5022 | 풀스택 · 함정 정비 도메인 | frontend/, finetune/, skills/ (ship_maintenance), DB·인증 | 눈 감아도 코딩하기. |

- `evals/`, `docs/`는 공동 담당입니다. 평가셋은 함정 문항을 하정운, SI 문항을 김승욱이 판정하고 상대 문항은 검토만 합니다.
- 두 영역이 만나는 지점은 `AgentRequest` / `AgentResponse` 스키마 하나입니다. 역할 경계는 [docs/SDD.md](./docs/SDD.md) 12절을 따릅니다.

### 일정

| 기간 | 작업 |
|---|---|
| 9/18 | 팀 합의, 레포·키 준비 |
| 9/21~23 | 문제 정의 확정, 평가셋 30건, 출력 계약, Skill 규칙 초안 |
| 9/24~27 | (연휴) 파인튜닝 데이터 검수, 소형 모델 1차 학습, 지도 UI 뼈대 |
| 9/28~10/2 | 핵심 구현, MCP 도구, Langfuse, 배포 |
| 9/30 | 중간 점검 |
| 10/6~8 | 측정 → 개선 → 재측정, EVAL_REPORT, 코드 동결 |
| 10/9~11 | 발표 자료, 데모 영상 |
| 10/12 | 발표 |

---

## 6. 협업 규칙

1. **`main`에 직접 push 금지.** 모든 변경은 브랜치 → PR로만 합칩니다.
2. 브랜치명은 `feat/{작업내용}`, 버그 수정은 `fix/{내용}`.
3. PR은 **조원 1명 이상의 approve를 받은 뒤** merge합니다.
4. **제출물은 마감 시점의 `main`입니다.** 마감 시각에 강사가 태그를 일괄 생성하며, 태그 이후 커밋은 평가 대상이 아닙니다.
5. **커밋은 본인 계정으로.** 함께 작업했다면 커밋 메시지에 `Co-authored-by:`를 추가합니다.
6. 다른 사람 담당 폴더를 고칠 때는 PR로 하고 먼저 알립니다. 스키마를 바꿀 때는 SDD 3·4절을 먼저 고친 뒤 양쪽에 알립니다.
7. 다른 조 저장소는 참고만 하고 복사 제출은 하지 않습니다.

### 작업 흐름

```bash
git switch main && git pull
git switch -c feat/login-api

git add .
git commit -m "feat: 로그인 API 구현"
git push -u origin feat/login-api
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
- 카톡 캡처 원본도 커밋하지 않습니다.
- 필요한 키 목록은 `.env.example`에 값 없이 적어 공유합니다.

## 질문

강사 확인이 필요한 질문은 이 저장소의 **Issues**에 남기고 강사를 멘션하세요.
