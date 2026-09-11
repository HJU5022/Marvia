# 이 저장소에 미리 들어 있는 것

처음 열면 낯선 폴더가 여럿 보일 겁니다. **전부 비어 있는 뼈대**이고, 여러분이 채우는 자리입니다.
"어디에 둬야 하나"를 고민하는 데 시간을 쓰지 말라고 미리 잡아 두었습니다.

쓰지 않는 것은 **지워도 됩니다.** 폴더를 남겨두는 것 자체로 점수를 받지는 않습니다.

---

## 한눈에

```
backend/              FastAPI 서버              ← 필수 2
  main.py               진입점 (/health 있음)
  services/llm.py       LLM 호출을 모으는 자리   ← 중요
  requirements.txt
skills/SKILL.md       도메인 지식·판단 기준      ← 필수 5
mcp_server/server.py  MCP 서버                  ← 필수 5
evals/                평가셋 30건               ← 필수 4
  dataset.jsonl         형식 예시 3건
  README.md             만드는 법
EVAL_REPORT.md        개선 전후 지표            ← 제출물
Dockerfile            컨테이너 이미지            ← 필수 2
docker-compose.yml    `docker compose up` 한 줄  ← 필수 2
.env.example          필요한 키 목록
```

---

## 파일별로 무엇을 하나

### `backend/main.py`

FastAPI 진입점입니다. `/health` 하나만 들어 있습니다.

```python
@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
```

채점자와 배포 환경이 서비스가 살아 있는지 확인하는 곳이라 **지우지 마세요.** 도메인 엔드포인트는 여기에 추가하면 됩니다.

요청·응답은 Pydantic 모델로 정의하세요(필수 3). 그리고 로그에 **요청 ID·사용 모델·토큰 수·지연 시간**을 남기면 축 ③에서 봅니다.

### `backend/services/llm.py` ← 가장 중요합니다

**LLM 호출은 전부 이 파일 하나로 모으세요.** 라우터나 UI 코드가 `openai`를 직접 import하지 않게만 해도 충분합니다.

```
✗ 흩어진 구조                    ✓ 모인 구조
routers/summary.py               services/llm.py   ← 여기만
  → openai.chat.completions        routers/*.py    ← 이 함수만 부른다
routers/extract.py
  → openai.chat.completions
```

이유가 있습니다. **3차 프로젝트에서 이 자리에 RAG 그래프가 들어옵니다.** 호출부를 한곳에 모아두면 그때 이 파일 내부만 갈아끼우면 되고, 흩뿌려두면 전부 뜯어야 합니다. 지금 5분 들이면 그때 며칠을 법니다.

이 파일이 책임지는 것: 출력 계약 검증(Pydantic) · 실패 시 재시도와 폴백 · Langfuse 트레이스.

### `skills/SKILL.md`

필수 조건 5의 절반입니다. **도메인 지식과 판단 기준을 적어 모델에 넘기는 문서**예요.

빈 양식에 네 칸이 있습니다.

| 칸 | 무엇을 적나 |
|---|---|
| 이 도메인은 무엇을 다루나 | 한두 문단 |
| 용어 | 이 바닥에서만 쓰는 말과 주의점 |
| 판단 기준 | "이 도메인에서는 이렇게 판단한다"를 규칙으로 |
| 예외와 함정 | 규칙만으로는 안 되는 경우 |
| 하지 말아야 할 것 | 사람에게 넘겨야 하는 경계 |

검색해서 그때그때 넣는 방식(RAG)은 3차에서 다룹니다. 2차에서는 **적어 넣습니다.**

### `mcp_server/server.py`

필수 조건 5의 나머지 절반. 2주차 17강에서 만든 `FastMCP` 그대로입니다.

```python
@mcp.tool()
def example_tool(query: str) -> str:
    """이 도구가 언제 쓰이는지 한 문장으로. 모델이 이 설명만 보고 고릅니다."""
```

**도구를 무엇으로 가를지가 설계입니다.** `tool_description`만 읽고도 언제 쓰는 도구인지 알 수 있어야 해요(2주차 6·7강).

확인 방법은 자유입니다 — Claude Desktop이나 Cursor에 연결해도 되고, 18강처럼 `langchain-mcp-adapters`로 붙여도 됩니다. **연결해서 도구가 불린다는 것만 화면으로 보이면 됩니다.**

### `evals/`

필수 조건 4. **최소 30건**이고 정상·경계·실패 유도를 섞습니다.

`dataset.jsonl`에 형식 예시 3건이 들어 있습니다.

```json
{"id": 1, "input": "...", "expected": "...", "note": "정상 케이스", "why": "이 답이 맞다고 본 이유"}
```

`why` 칸이 있는 이유: **정답을 정한 기준을 적어야** 나중에 팀원끼리 판단이 갈릴 때 돌아볼 수 있습니다.

**착수 후 9/23(수)까지 채우세요.** 9/24~27이 추석 연휴라, 이게 없으면 연휴가 통째로 빕니다. 반대로 문제 정의와 평가셋만 있으면 각자 비동기로 진행할 수 있습니다.

### `EVAL_REPORT.md`

제출물이자 축 ④(25점)의 근거 문서입니다. 표 다섯 개가 비어 있습니다.

평가셋 구성 · **개선 전후 지표** · 무엇을 바꿨나(KEEP/DISCARD) · 실패 사례 분석 · 출시 게이트.

> 숫자가 나빠도 괜찮습니다. **재고, 원인을 알고, 무엇을 시도했는지**가 평가 대상입니다.
> 버린 시도도 적으세요 — "이걸 해봤는데 효과가 없었다"가 가장 값진 내용입니다.

### `Dockerfile` · `docker-compose.yml`

필수 조건 2. 채점자가 이 한 줄로 띄울 수 있어야 합니다.

```bash
cp .env.example .env   # 키만 채우고
docker compose up      # 한 줄
```

기본으로 `api`(FastAPI)와 `db`(Postgres) 두 서비스가 들어 있습니다. Postgres가 필요 없으면 지우고, Redis 같은 게 필요하면 추가하세요.

> Apple Silicon(M1~M4)에서 이미지가 안 뜨면 `docker-compose.yml`의 `platform: linux/amd64` 주석을 해제해 보세요.

### `.env.example`

**필요한 키 목록만** 공유하는 파일입니다. 실제 값은 `.env`에 적고, 그건 `.gitignore`에 있어 커밋되지 않습니다.

OpenRouter를 권장하는 이유는 키 하나로 여러 회사 모델을 같은 코드로 부를 수 있어서예요. 축 ②가 요구하는 "2개 이상 모델 비교"가 훨씬 쉬워집니다.

---

## 이미 있던 것 (1차와 동일)

| 파일 | 역할 |
|---|---|
| `.github/PULL_REQUEST_TEMPLATE.md` | PR 열 때 자동으로 뜨는 양식 |
| `.github/workflows/secret-scan.yml` | 키가 커밋되면 CI가 잡습니다 |
| `AGENTS.md` · `CLAUDE.md` | AI 에이전트 공통 지침 |
| `docs/specs/_example.md` | 기능을 에이전트에게 시키기 전 Spec을 쓰는 자리 |

**협업 규칙은 1차와 같습니다** — `main` 직접 push 금지, `feat/` 브랜치, 조원 1명 이상 approve 후 merge, 본인 계정으로 커밋.

---

## 처음 할 일

1. **README의 조원 소개 표에 자기 행을 추가** — 브랜치 → PR → 리뷰 → merge로. 첫 PR이 협업 흐름 연습입니다.
2. `cp .env.example .env` 후 키 채우기
3. `docker compose up`으로 `/health`가 뜨는지 확인
4. **문제 정의와 `evals/` 채우기** (9/23까지)

막히면 검색하기 전에 강의 실습 자료를 먼저 여세요. FastAPI 워크숍 `docs/`에만 가이드 13종이 있습니다.
