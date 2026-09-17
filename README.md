# AI Human 7기 — 조별 프로젝트 저장소

이 저장소는 **조별 프로젝트 공간**입니다. 조원 전원이 write 권한을 갖습니다.

## 팀 정보 (프로젝트 시작 시 조장이 작성)

| 항목 | 내용 |
|---|---|
| 프로젝트 | proj2 — Converge |
| 조 | 5조 |

## 조원 소개 — 🏁 첫 과제

**조원 각자가 자기 행을 브랜치 → PR → 리뷰 → merge로 직접 추가하세요.** (전원 필수)
이 첫 PR이 협업 흐름 연습입니다. 같은 표를 여러 명이 수정하면 충돌이 날 수 있는데, 그것까지가 연습입니다 (아래 "충돌이 났을 때" 참고).

| 이름 | GitHub | 역할 | 한마디 |
|---|---|---|---|
| 김승욱 | @seungwook-kim | 조장 · 풀스택 · SI 배포 도메인 | 눈 뜨면 코딩하기. |
| 하정운 | @HJU5022 | 풀스택 · 함정 정비 도메인 | 눈 감아도 코딩하기. |

## 협업 규칙 (필독)

1. **`main`에 직접 push 금지** — 모든 변경은 브랜치 → PR로만 합칩니다.
2. 브랜치명: `feat/{작업내용}` (예: `feat/login-api`, 버그 수정은 `fix/{내용}`)
3. PR은 **조원 1명 이상의 approve를 받은 뒤** merge합니다. 리뷰 없는 merge는 감사 리포트에 잡힙니다.
4. **제출물 = 마감 시점의 `main`** — 마감 시각에 강사가 전체 조 repo에 태그를 일괄 생성합니다. 태그 이후 커밋은 평가 대상이 아닙니다.
5. **커밋은 본인 계정으로**: 자기가 한 작업은 자기 계정으로 커밋해야 이 repo가 본인 포트폴리오 증빙이 됩니다. 함께 작업했다면 커밋 메시지에 `Co-authored-by:`를 추가하세요.
6. 다른 조 저장소도 읽을 수 있습니다 — 보고 배우는 것은 권장, 복사 제출은 금지.

## 📁 폴더 구조 (2차 프로젝트)

필수 조건과 제출물에 맞춰 자리를 미리 잡아 두었습니다. 쓰지 않는 것은 지우고, 필요한 것은 더하세요.

```
backend/          FastAPI (필수 2) — services/llm.py 한곳에 LLM 호출을 모읍니다
skills/           도메인 지식·판단 기준 (필수 5)
mcp_server/       MCP 서버 (필수 5)
evals/            평가셋 30건 (필수 4)
EVAL_REPORT.md    개선 전후 지표 (제출물)
docker-compose.yml  `docker compose up` 한 줄 실행 (필수 2)
```

**착수 후 9/23(수)까지 문제 정의와 `evals/`를 채우세요.** 추석 연휴 전에 이 둘이 있어야 연휴 동안 각자 진행할 수 있습니다.

각 폴더가 무엇이고 무엇을 채워야 하는지는 **[docs/SCAFFOLD.md](./docs/SCAFFOLD.md)**에 정리돼 있습니다.
자세한 요구사항은 2차 프로젝트 가이드를 참고하세요.

## 🔑 시크릿 규칙 (위반 시 전원에게 노출됩니다)

- API 키·비밀번호는 **`.env` 파일에만** 두세요. `.env`는 `.gitignore`에 이미 등록되어 커밋되지 않습니다.
- 코드에 키를 직접 적으면 안 됩니다. 이 org는 상호 공개라 **커밋된 키는 7기 전원이 볼 수 있습니다.**
- 모든 push는 **Secret Scan**(GitHub Actions)이 자동 검사합니다. 검사가 ❌ 실패하면 = 키가 커밋된 것입니다. 즉시 강사에게 알리고 **해당 키를 재발급**하세요. (히스토리에서 지워도 유출된 것으로 간주합니다)
- 필요한 키 목록은 `.env.example`에 값 없이 적어 공유하세요.

## 작업 흐름

```bash
# 1. 최신 main에서 작업 브랜치 생성
git switch main && git pull
git switch -c feat/login-api

# 2. 작업 후 커밋·push
git add .
git commit -m "feat: 로그인 API 구현"
git push -u origin feat/login-api

# 3. GitHub에서 PR 생성 → 조원 리뷰 → approve 후 merge
```

## 충돌(conflict)이 났을 때

PR 화면에 "This branch has conflicts" 가 뜨면:

```bash
git switch main && git pull          # 최신 main 받기
git switch feat/내브랜치
git merge main                       # 충돌 발생 지점이 파일에 표시됨
# 파일 열어 <<<<<<< ======= >>>>>>> 사이에서 남길 내용 선택 후 저장
git add . && git commit              # 충돌 해결 커밋
git push                             # PR이 자동 갱신됨
```

당황하지 말 것 — 충돌은 사고가 아니라 협업의 일상입니다. 막히면 조원 또는 강사를 부르세요.

## 폴더 구조

- `docs/` — 기획서·회의록·발표자료 (PRD·SDD·테이블정의서)
- `docs/planning/` — 계획서 보완 제출본 (도메인 경험·평가 질문 10개)
- `docs/specs/` — 기능별 Spec 문서 (`_example.md` 형식 참고, AI 에이전트에게 구현을 시키기 전 여기에 먼저 작성)
- `AGENTS.md` / `CLAUDE.md` — AI 에이전트(Claude Code·Codex 등) 공통 작업 지침
- 소스 코드 구조는 조에서 자율 결정 (README에 실행 방법 필수 기재)

## 질문

강사 확인이 필요한 질문은 이 저장소의 **Issues**에 남기고 강사를 멘션하세요.

---

## 프로젝트 소개 — Converge

**현장이 움직이는 유지보수·배포 작업에서, 담당자가 업체·고객사와 "어디서 몇 시에 만날지" 정하는 일을 문장 하나로 끝내는 에이전트**

함정 정비 미팅과 SI 야간 배포 집결. 두 현장 모두 출입조치·인솔 같은 절차가 집결지와 시각을 가르는데, 기존 지도 앱은 그 절차를 모릅니다. 전화와 카톡으로 30분에서 한 시간을 쓰던 조율을, 절차와 경로를 함께 계산해 지도 위에 답으로 내놓습니다.

| | |
|---|---|
| 서비스 | (Vercel URL) |
| Agent API | (Cloud Run URL) · `GET /health` · `POST /api/agent` |
| 기획 | [docs/PRD_Converge_v2.0.md](./docs/PRD_Converge_v2.0.md) |
| 설계 | [docs/SDD_Converge_v2.0.md](./docs/SDD_Converge_v2.0.md) · [docs/테이블정의서_Converge_v2.0.md](./docs/테이블정의서_Converge_v2.0.md) |
| 지표 | [EVAL_REPORT.md](./EVAL_REPORT.md) |

### 무엇을 하나

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

LLM은 입구(문장 → 슬롯)와 출구(집결지 판정·근거)에만 있습니다. 소요시간, 출발 시각, 절차 소요 반영은 전부 코드가 계산합니다.

### 지표

10/8 측정 결과로 채웁니다.

| 항목 | 개선 전 | 개선 후 |
|---|---|---|
| 슬롯 추출 정확도 | | |
| 집결지 판정 정확도 | | |
| 출력 계약 준수율 | | |
| p50 / p95 지연 | | |
| 요청당 비용 | | |

### 실행

```bash
git clone <repo> && cd <repo>
cp .env.example .env     # 키만 채우고
docker compose up        # backend:8080 (/api/agent, /health, /mcp)

cd frontend && npm install && npm run dev   # :3000
```

필요한 키는 `.env.example` 참고. Kakao Local·Kakao Mobility·TMAP·OpenRouter·Langfuse·Supabase.

**스택** FastAPI · Docker · Cloud Run · Next.js · Vercel · Supabase · Langfuse · OpenRouter · Kakao Local/Mobility · TMAP
