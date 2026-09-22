# Marvia

> B/L 번호와 판매 예정일을 넣으면 "내 화물, 지금 신경 써야 하나?"에 **괜찮음 / 지켜볼 것 / 지금 조치**로 답하는 에이전트.
> 그 배가 내 화물 배가 맞는지 확정하고, 서로 안 맞는 신호 중 무엇을 믿을지 근거로 가르고, 확정 못 하면 판정 대신 되묻는다. 모든 판정에 출처와 조회 시각이 붙는다.

AI Human 7기 2차 팀 프로젝트 · [유형 1] 도메인 특화 LLM 서비스

## 팀 정보

| 항목 | 내용 |
|---|---|
| 프로젝트 | proj2-5 — Marvia |
| 조 | {A~G} |

## 조원 소개

**조원 각자가 자기 행을 브랜치 → PR → 리뷰 → merge로 직접 추가하세요.**

| 이름 | GitHub | 역할 | 한마디 |
|---|---|---|---|
| 홍길동(예시) | @octocat | 백엔드 | 잘 부탁드립니다 |

작업 묶음(A 백엔드·배포 / B MCP·데이터 소스 / C 판정·LLM·Skill / D 관측·수집·평가 / E 프론트엔드) 담당은 팀 회의에서 확정합니다. 묶음별 작업은 [docs/Marvia_개발_작업_리스트.md](./docs/Marvia_개발_작업_리스트.md) 참고.

## 무엇을 푸는가

**사용자:** 포워더가 일일이 챙겨주지 않는 소량 해상 수입자(스마트스토어 수입 셀러, 구매대행). 부산항으로 들어오는 화물 몇 건을 관리한다.

**문제:** 추적 서비스의 ETA를 믿어도 되는지, 그 배가 내 배가 맞는지, 유니패스 통관 단계가 무슨 뜻인지 판단하지 못해 지연을 늦게 알고 판매 일정이 틀어진다.

| 유사 서비스(트레드링스) | 이 서비스 |
|---|---|
| 조회한 배가 내 배라고 전제 | 후보가 여럿이면 확정하지 않고 되묻는다 |
| ETA 확률 범위 | 왜 못 믿는지 근거 (53일 전 위치, 깨진 목적지, 속도 0인데 항해 중) |
| 일반 지연 알림 | 판매 예정일 대비 여유 일수로 3단계 판정 + 할 일 |
| 통관 단계명 그대로 | 뜻·다음 단계·할 일 |

**만들지 않는 것:** 항공·육상·부산 외 항만, 창고 수령일 예측, 세액·통관 가부 판단, 알림톡·결제.

## 어떻게 동작하나

```
B/L + 판매 예정일 → UNI-PASS 조회(코드) → 선박 후보 → 식별(1척이면 코드, 여럿이면 LLM, 불확정이면 되묻기)
  → 위치·입항예정·남은 거리 (MCP 도구) → 1층 신호 판정(코드) → 2층 종합 판정(LLM) → 출력 검증 7규칙
  → 화면: 판정 · 할 일 · 위치 · 통관 해설 · 하역 장소 · 근거 카드
```

- **1층 (코드):** 위치 6시간 끊김, AIS ETA와 해수부 입항예정 12시간 차이, 부산 인근 24시간 정박, 목적지 변경·깨짐, 항해상태·속도 불일치, 통관 검사·보류. 임계값은 `skills/` 문서 프론트매터에 둔다.
- **2층 (LLM):** 신호가 서로 어긋날 때 어느 출처를 왜 믿는지 정하고 판정한다. 우선순위는 해수부 관제 실적 > 해수부 입항 예정 > AIS ETA > AIS 목적지.
- **울타리:** 위치가 오래됐으면 "현재 위치" 표현 금지, 식별 불확정이면 판정 금지, 근거에 없는 숫자 거부. 위반 시 재시도 3단계 후 폴백.

### 아키텍처

```
사용자 → Next.js (Vercel) → FastAPI (Cloud Run)  POST /api/agent · GET /health
   FastAPI ─ UNI-PASS 직접 조회 (B/L은 LLM에 넘기지 않음)
          └ services/llm.py (LLM 호출 단일 지점, Skill 통째 주입) ─ OpenRouter 모델 A/B
                 └ tool call → FastMCP /mcp (토큰 인증) → ShipFinder · 해수부 공공데이터 · searoute
   모든 호출 → Langfuse 트레이스 · 프롬프트 버전 · 평가셋
   수집 워커 → Postgres: 평가셋 라벨용 선박 위치·입항 실적
```

| 영역 | 기술 |
|---|---|
| 백엔드 | FastAPI, Pydantic v2 |
| MCP | FastMCP (Streamable HTTP) |
| LLM | OpenRouter (모델 2개 비교) |
| 관측·평가 | Langfuse |
| DB | Postgres 16 |
| 프론트 | Next.js, Vercel |
| 배포 | Docker, docker compose, GCP Cloud Run |

LangGraph와 RAG는 쓰지 않는다. 도메인 지식은 Skill 문서를 시스템 프롬프트에 통째로 넣고, 실시간 데이터는 MCP 도구로 받는다.

## 실행 방법

> 구현 진행 중입니다. 아래는 목표 절차이며, 완성되면 실제 동작 기준으로 갱신합니다.

```bash
git clone https://github.com/aihuman-7th/proj2-5.git
cd proj2-5
cp .env.example .env        # 키 입력. REPLAY_MODE=true면 키 없이 데모 동작
docker compose up
# http://localhost:8000/health · http://localhost:8000/docs
```

필요한 키: UNI-PASS, 공공데이터포털(해수부), ShipFinder, OpenRouter, Langfuse. 목록은 [.env.example](./.env.example) 참고.

## 폴더 구조

```
backend/            FastAPI — services/llm.py 한곳에 LLM 호출을 모읍니다
mcp_server/         FastMCP 서버 (선박 후보·실시간 위치·입항 일정·남은 거리)
skills/             도메인 판단 기준 (AIS 신뢰도, 통관 단계, 부산항)
evals/              평가셋 30건
EVAL_REPORT.md      베이스라인 대비 지표
docker-compose.yml  `docker compose up` 한 줄 실행
docs/               PRD · SDD · 작업 리스트 · 스캐폴딩 안내
AGENTS.md / CLAUDE.md  AI 에이전트 공통 작업 지침
```

## 평가

- 평가셋 30건: 실제 부산 입항 선박의 위치를 수집하고, 가상 B/L·모의 통관 단계·가상 판매 예정일을 붙인다 (선박·위치는 실제, 나머지는 시뮬레이션).
- 비교: (a) 규칙만 / (b) 규칙 + LLM 모델 A / (c) 모델 B. 핵심은 신호 상충 5건에서 LLM이 규칙보다 나은지.
- 배포 게이트: act 누락 1건 이상 · 선박 오확정 1건 이상 · 스키마 통과 95% 미만 · 주입 오작동 1건 이상 중 하나라도 걸리면 배포하지 않는다.

결과는 [EVAL_REPORT.md](./EVAL_REPORT.md)에 기록합니다.

## 문서

| 문서 | 내용 |
|---|---|
| [PRD](./docs/Marvia_PRD.md) | 문제·사용자·범위·판정·평가 설계 |
| [SDD](./docs/Marvia_SDD.md) | 구현 명세: 스키마 계약, 처리 흐름, 컴포넌트별 완료 기준 |
| [개발 작업 리스트](./docs/Marvia_개발_작업_리스트.md) | 묶음 A~F 작업, 기한, 의존 관계 |
| [SCAFFOLD](./docs/SCAFFOLD.md) | 폴더별 채울 내용 |

## 일정

| 기간 | 끝낼 것 |
|---|---|
| 9/22~23 | 키 발급, 수집 워커 가동, 계약(스키마) 고정 |
| 9/24~27 | MCP 뼈대, Langfuse 연결, Cloud Run 빈 배포, Skill 초안 |
| 9/28~10/2 | 본 구현, 베이스라인 (a) |
| 10/6~8 | 라벨·평가·UI·데모 영상. **10/8 자정 코드 동결** |
| 10/12 | 발표 |

## 협업 규칙 (필독)

1. **`main`에 직접 push 금지** — 모든 변경은 브랜치 → PR로만 합칩니다.
2. 브랜치명: `feat/{작업내용}` (예: `feat/mcp-live-position`, 버그 수정은 `fix/{내용}`)
3. PR은 **조원 1명 이상의 approve를 받은 뒤** merge합니다. 리뷰 없는 merge는 감사 리포트에 잡힙니다.
4. **제출물 = 마감 시점의 `main`** — 마감 시각에 강사가 전체 조 repo에 태그를 일괄 생성합니다. 태그 이후 커밋은 평가 대상이 아닙니다.
5. **커밋은 본인 계정으로**: 함께 작업했다면 커밋 메시지에 `Co-authored-by:`를 추가하세요.
6. 다른 조 저장소도 읽을 수 있습니다 — 보고 배우는 것은 권장, 복사 제출은 금지.

## 🔑 시크릿 규칙 (위반 시 전원에게 노출됩니다)

- API 키·비밀번호는 **`.env` 파일에만** 두세요. `.env`는 `.gitignore`에 등록되어 커밋되지 않습니다.
- 코드에 키를 직접 적으면 안 됩니다. 이 org는 상호 공개라 **커밋된 키는 7기 전원이 볼 수 있습니다.**
- 모든 push는 **Secret Scan**(GitHub Actions)이 자동 검사합니다. 검사가 ❌ 실패하면 = 키가 커밋된 것입니다. 즉시 강사에게 알리고 **해당 키를 재발급**하세요.
- 필요한 키 목록은 `.env.example`에 값 없이 적어 공유하세요.

## 작업 흐름

```bash
# 1. 최신 main에서 작업 브랜치 생성
git switch main && git pull
git switch -c feat/작업내용

# 2. 작업 후 커밋·push
git add .
git commit -m "feat: 작업 내용"
git push -u origin feat/작업내용

# 3. GitHub에서 PR 생성 → 조원 리뷰 → approve 후 merge
```

### 충돌(conflict)이 났을 때

```bash
git switch main && git pull
git switch feat/내브랜치
git merge main                       # 충돌 지점이 파일에 표시됨
# <<<<<<< ======= >>>>>>> 사이에서 남길 내용 선택 후 저장
git add . && git commit
git push                             # PR이 자동 갱신됨
```

## 질문

강사 확인이 필요한 질문은 이 저장소의 **Issues**에 남기고 강사를 멘션하세요.
