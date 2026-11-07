# Marvia v2 배포 절차 (done 4.4, 설계 13절, 계획 4b Task 10)

API는 Cloud Run(서울, `asia-northeast3`), 화면은 Vercel, DB는 Supabase, 그래프는 AuraDB 무료판(지금 기본값 `MARVIA_GRAPH=off`라 처음 배포에는 필요 없다)이다. 키는 GCP Secret Manager에만 두고 저장소에는 이름만 둔다. GitHub Actions는 키 파일 없이 WIF(GitHub OIDC 토큰 → 서비스 계정)로 GCP에 들어간다.

계정·프로젝트·키를 만드는 일과 실제 배포는 직접 한다. 아래 "직접 할 일"은 아직 하지 않았고, "로컬 확인"은 계정 없이 이 컴퓨터에서 실제로 돌린 명령과 결과다.

## 로컬 확인 (dry-run, 11-07 실측)

실제로 돌린 것만 적었다. 돌리지 않은 것은 "돌리지 않음"이라 적었다. 모델은 가짜였고 유료 호출은 없다.

| 확인 | 명령 | 결과 |
|---|---|---|
| amd64 이미지 빌드 | `docker buildx build --platform linux/amd64 --target runtime --load .` | 성공, 71초 |
| amd64 이미지 크기 | `docker image inspect` (리드 측정) | 1.18GB (상한 1.2GB, 여유 작음) |
| arm64 이미지 크기 | `docker images` | 1.07GB |
| 실행 사용자 | `docker run --rm <이미지> id -u` | `10001` |
| 형태소 분석기 메모리 (1GB) | `docker run --rm --platform linux/amd64 --memory 1g --memory-swap 1g <이미지> python -c "from marvia.rag.keywords import keywords; print(keywords('수입 신고 시 관세율은 어떻게 정해지나요?')[:5])"` | 종료 코드 0, `['수입', '신고', '관세', '어떻', '정하']` (Cloud Run 배포 명령의 `--memory 1Gi`가 이 값) |
| 형태소 분석기 메모리 (512MB) | 위와 같고 `--memory 512m --memory-swap 512m` | 종료 코드 137 (메모리 초과로 죽음). Cloud Run 기본값 512MiB로는 첫 법령 검색에서 인스턴스가 죽는다는 뜻 |
| 이미지 안 규칙·지시문 | `docker run --rm <이미지> python -c "from marvia.tools.rules import load_rules; from marvia.prompts import render; load_rules('agent'); print(len(render('agent')) > 0)"` | `True` |
| 이미지에 없는 것 | `docker run --rm <이미지> ls -a /app` | `.venv corpus fixtures migrations prompts pyproject.toml rules src uv.lock`만 있다. `.env`·`.local`·`scripts`·`tests`·`e2e` 없음 |
| 서버가 듣는 주소 | `docker run --rm <이미지> sh -c 'echo $MARVIA_HOST'` | `0.0.0.0` (서버 기본은 127.0.0.1이고 이미지가 컨테이너 안에서만 연다) |
| 로그인 설정 없음 | `docker run --rm -e MARVIA_AUTH=supabase <이미지>` | `RuntimeError: MARVIA_SUPABASE_URL이 없어 로그인을 확인할 수 없습니다` |
| Cloud Run에서 개발 로그인 | `docker run --rm -e K_SERVICE=x -e MARVIA_AUTH=dev -e MARVIA_DEV_TOKEN=t <이미지>` | `RuntimeError: Cloud Run에서는 개발 로그인(MARVIA_AUTH=dev)으로 시작하지 않습니다` |
| 키 없음 | `uv run pytest -q tests/graph/test_server.py::test_the_server_refuses_to_start_without_model_and_data_keys` | passed (키가 없으면 `RuntimeError: MARVIA_ANTHROPIC_API_KEY ...`로 시작을 거절) |
| compose 앱(표 준비, API) | 버리는 프로젝트 `marvia-4bcheck`, 포트를 옮기고 버리는 키로 `docker compose -p marvia-4bcheck --profile app up -d --build db neo4j prepare api` | db healthy 뒤 prepare가 `표 준비 끝`, api healthy, 호스트에서 `/health`가 `{"ok":true}`, 토큰 없는 `POST /agui` 401. 끝나고 `down -v`. 개발 compose 프로젝트에는 `up`을 하지 않았다 |
| 표 준비 두 번 | 버리는 프로젝트 `marvia-4bcheck`에서 `docker compose -p marvia-4bcheck --profile app run --rm prepare`를 한 번 더, 그리고 `MARVIA_REQUIRE_DB=1 uv run pytest -q tests/test_docker.py` | 두 번째도 `표 준비 끝`. 시험(prepare를 두 번 부르는 시험 포함 7개 중)이 통과해 표와 이력이 같다 |
| 화면 주요 흐름 4개 | `docker compose -p marvia-4be2e --profile e2e run --rm --build playwright` | 4 passed (6.5초), 접근성(axe) serious·critical 0, 브라우저의 바깥 요청 0. 가짜 모델 화면 |
| 배포 워크플로 문법 | `docker run --rm -v "$PWD":/repo -w /repo rhysd/actionlint@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667 -no-color` | 오류 0 (종료 코드 0) |
| `PORT`로 듣기 (단위 시험) | `uv run pytest -q tests/graph/test_server.py -k main_listens` | passed. `PORT=9999`로 `main()`을 부르면 `uvicorn.run`이 포트 9999를 받는다 (uvicorn은 가짜로 바꾼 시험이라 서버는 뜨지 않는다) |
| `PORT`로 듣기 (컨테이너) | | 돌리지 않음. Cloud Run이 `PORT=8080`을 넣고 배포 명령도 `--port 8080`이다 |
| Cloud Run job과 service 배포 | | 돌리지 않음 (계정 없음). job의 `--command python --args=-m,marvia.prepare_db` 모양도 돌리지 않음 (compose는 이미지 CMD 대신 `command:`로 같은 모듈을 불렀다) |

계정이 필요한 명령(gcloud, Vercel, Supabase)은 돌리지 않았다. 아래 gcloud 명령의 모양은 참조 문서(`run deploy`, `run jobs deploy`, `run jobs execute`, `artifacts repositories create`, `secrets create`, `secrets versions add`)와 google-github-actions/auth v3.0.0 README로 확인했다 [문서 11-07]. `services enable`과 IAM 역할 이름은 확인하지 않았다 [추정].

## 직접 할 일 1: Supabase (DB, 로그인)

1. 프로젝트를 만들고(지역은 서울에 가까운 곳), Authentication에서 Google 제공자를 켠다. 내 계정으로 한 번 로그인한 뒤 새 가입을 막는다(Authentication 설정의 가입 허용 끔). 내 사용자 id(UUID)를 적어 둔다. 이것이 `MARVIA_OWNER_IDS`다.
    - 로그인 확인은 비대칭 서명 키(ES256, 공개키 목록 `<프로젝트 주소>/auth/v1/.well-known/jwks.json`)만 받는다. 프로젝트의 JWT 서명 키를 비대칭(ES256)으로 쓰게 맞춰 둔다. 예전 HS256 비밀값 방식인 프로젝트는 모든 로그인이 401이 된다.
    - 내 사용자 id(토큰의 `sub`)를 `MARVIA_OWNER_IDS`에 넣는다. 목록 밖 사용자는 403이다.
    - 가입은 꺼 둔다(Authentication 설정의 가입 허용 끔).
2. DB 주소는 공유 풀러의 **세션 모드(5432)** 주소를 쓴다. [왜] 무료판 직접 연결은 IPv6뿐이고, 트랜잭션 모드(6543)는 prepared statement를 받지 않는다(계획 4b 사전 부검 3번, Supabase 연결 문서).
3. 표와 코퍼스를 옮긴다. 코퍼스는 다시 임베딩하지 않고 로컬 표를 그대로 옮긴다(Voyage 비용 없음):

    ```bash
    docker compose exec -T db pg_dump -U marvia -d marvia -t corpus_units --no-owner > corpus_units.sql
    # 받은 Supabase 주소로 (주소는 셸에만, 저장소·기록에 남기지 않는다)
    psql "$SUPABASE_SESSION_URL" -c 'CREATE EXTENSION IF NOT EXISTS vector'
    psql "$SUPABASE_SESSION_URL" -f corpus_units.sql
    ```

    나머지 표(감시, 대화 기록, 장기 기억)는 배포 워크플로의 `marvia-prepare` 작업(`python -m marvia.prepare_db`)이 만든다.

## 직접 할 일 2: GCP (Cloud Run, Artifact Registry, Secret Manager, WIF)

`PROJECT_ID`, `REPO`(예: `HJU5022/Marvia`)를 정한 뒤:

```bash
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com iamcredentials.googleapis.com --project "$PROJECT_ID"
gcloud artifacts repositories create marvia --repository-format=docker --location=asia-northeast3 --project "$PROJECT_ID"
# 키는 값 파일을 셸에서 바로 넣는다. 화면·기록에 찍지 않는다
for name in marvia-database-url marvia-data-key marvia-anthropic-key marvia-voyage-key marvia-owner-ids; do
  gcloud secrets create "$name" --replication-policy=automatic --project "$PROJECT_ID"
done
printf %s "$VALUE" | gcloud secrets versions add marvia-data-key --data-file=- --project "$PROJECT_ID"   # 키마다 한 번씩
```

WIF는 google-github-actions/auth v3.0.0 README의 "Workload Identity Federation through a Service Account" 순서를 따른다 [문서 11-07]:

```bash
gcloud iam service-accounts create "marvia-deploy" --project "${PROJECT_ID}"
gcloud iam workload-identity-pools create "github" --project="${PROJECT_ID}" --location="global" --display-name="GitHub Actions Pool"
gcloud iam workload-identity-pools providers create-oidc "marvia" \
  --project="${PROJECT_ID}" --location="global" --workload-identity-pool="github" \
  --display-name="Marvia repo" \
  --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
  --attribute-condition="assertion.repository == '${REPO}'" \
  --issuer-uri="https://token.actions.githubusercontent.com"
POOL=$(gcloud iam workload-identity-pools describe "github" --project="${PROJECT_ID}" --location="global" --format="value(name)")
gcloud iam service-accounts add-iam-policy-binding "marvia-deploy@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project="${PROJECT_ID}" --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${POOL}/attribute.repository/${REPO}"
gcloud iam workload-identity-pools providers describe "marvia" --project="${PROJECT_ID}" --location="global" --workload-identity-pool="github" --format="value(name)"
```

서비스 계정에는 배포에 필요한 역할만 준다: Cloud Run 관리(`roles/run.admin`), 서비스 계정 사용(`roles/iam.serviceAccountUser`), Artifact Registry 쓰기(`roles/artifactregistry.writer`), 비밀 읽기(`roles/secretmanager.secretAccessor`, Cloud Run 실행 계정에도). 역할 이름은 GCP IAM 문서로 다시 확인한다 [추정].

## 직접 할 일 3: GitHub 저장소 변수와 배포

저장소 Settings → Variables(비밀이 아닌 값): `GCP_PROJECT`, `GCP_REGION=asia-northeast3`, `GCP_WIF_PROVIDER`(위 마지막 명령의 값), `GCP_DEPLOY_SA=marvia-deploy@<프로젝트>.iam.gserviceaccount.com`, `MARVIA_SUPABASE_URL`, `MARVIA_WEB_ORIGIN`(Vercel 주소), 마지막에 `MARVIA_DEPLOY_ENABLED=true`.

Actions 탭에서 `deploy` 워크플로를 손으로 돌린다(`workflow_dispatch`만 있다. push로는 돌지 않는다). 순서: amd64 이미지 빌드·올리기 → `marvia-prepare` 작업으로 표 준비 → `marvia-api` 배포(요청 시간 제한 300초, 로그인은 Supabase 토큰, `--max-instances 1`).

인스턴스는 하나로 둔다. 같은 대화를 동시에 돌리지 않게 하는 잠금(409)이 프로세스 안에서만 지켜지기 때문이다(R-073). 하나로 두면 비용 상한도 된다. 여러 개로 늘릴 때는 대화 키에 `pg_try_advisory_lock`을 거는 것으로 올린다.

서버가 듣는 주소는 이미지의 `MARVIA_HOST=0.0.0.0`이 정한다. 배포 명령의 환경 변수에는 넣지 않는다.

배포 뒤 확인: `curl https://<cloud-run 주소>/health` → `{"ok":true}`, 토큰 없는 `POST /agui` → 401.

배포 뒤 직접 할 한 가지: 화면에서 법령 질문을 한 번 한다(유료 호출 1회). 형태소 분석기는 첫 검색에서 처음 올라와 메모리를 가장 많이 쓰므로, 답이 오면 `--memory 1Gi`가 충분하다는 확인이다. `/health`와 401 확인은 검색을 거치지 않아 이것을 잡지 못한다.

## 직접 할 일 4: Vercel (화면)

프로젝트의 Root Directory를 `web`으로, 환경 변수 `NEXT_PUBLIC_API_URL`(Cloud Run 주소), `NEXT_PUBLIC_AUTH=supabase`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`(공개 키)를 넣는다. 브라우저는 Cloud Run을 바로 부르고(Vercel 함수로 SSE를 중계하지 않는다), API는 `MARVIA_WEB_ORIGIN` 하나만 CORS로 연다. Supabase Authentication의 Redirect URL에 Vercel 주소를 넣는다.

## 직접 할 일 5: AuraDB (그래프를 켤 때만)

`MARVIA_GRAPH=on`으로 바꿀 때만 필요하다. 무료판 한도와 쉬는 조건은 확인하지 못했다 [미확인]. 그래프는 단위 7,412개, `REFERS_TO` 18,099개다(계획 3b). 켜면 `MARVIA_NEO4J_URL`·`MARVIA_NEO4J_PASSWORD`를 비밀로 더하고 `scripts/build_graph.py`로 적재한다.

## 열지 않는 것

- 규정 검색 MCP HTTP(`scripts/serve_mcp.py`)는 배포에서 열지 않는다. 에이전트는 같은 프로세스 안의 메모리 통로로 부른다(설계 9절, 14절 "MCP 공개 → 내부 도구로만"). 연다면 배포 주소의 Host 검사를 먼저 본다.
- 바깥 메시지 발송 도구는 만들지 않았다(설계 6.3에서 2차, 보낼 통로가 없음).
