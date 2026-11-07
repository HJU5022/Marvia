# Marvia v2 계획 6c: 지난 검토에서 넘긴 고침 묶음 (계정 삭제·409·식별·트레이스·화면)

> 진행 방법: 태스크를 T0부터 차례로 하고, 단계마다 체크박스(`- [ ]`)로 표시한다. 커밋 하나는 동작 하나다. 태스크 순서는 자를 순서의 반대라서, 시간이 모자라면 뒤에서부터 잘라도 앞의 커밋은 그대로 남는다.

**Goal:** 계획 4b·6a·6b의 전체 검토와 마무리에서 "다음에 고친다"로 넘긴 것을 한 계획으로 닫는다. 계정을 지우는 동안 그 사용자의 새 차례를 막고(A), 화면이 409마다 서버가 정한 까닭을 보이며 지난 카드일 때만 카드를 치우고(B), 컨테이너 선택지 뒤 같은 글의 B/L을 다시 조회하지 않고(F), 같은 번호를 두 번 조회하지 않고(G), 역슬래시·공백이 든 Langfuse 주소를 거절한다(J). 여기에 로컬 화면 서버의 듣는 주소와 e2e 이미지의 실행 사용자(D), 트레이스 ② 겹이 JSON 값을 깨지 않게 가리기(I), 계정 삭제 화면 다듬기(E), 대화 id 상한을 규칙으로(C), 식별 질문 글을 규칙으로(H), 컨테이너 카드가 떠 있는 동안의 어긋난 화물 카드(K)를 더한다. 새 의존성, 유료 호출, 실제 UNI-PASS 호출은 없다.

**Architecture:** 고치는 곳은 다섯 덩어리다. 서로 기대지 않는다.

```
서버(src/marvia/server.py)       A deleting 집합(guard 안) → /agui·DELETE 409 / B 409 본문의 code(stale_card)
                                 / C 대화 id 상한 ← rules/server.yaml request.max_thread_id
화면(web/)                       B·E HttpError가 409 본문의 글·code를 받음, 카드는 stale_card일 때만 치움
                                 E 계정 삭제: 확인에 초점, 401이면 로그아웃, 204 뒤 대화·패널·카드 비움
                                 D package.json dev·start -H 127.0.0.1, e2e.Dockerfile USER pwuser
식별(src/marvia/graph/identify.py, main.py)
   read ── 물으면 cargos를 비움(F) / 질문 글 ← rules/identify.yaml(H)
   lookup 서브그래프 ── assign이 번호 중복을 뺌(G) / reuse=True(메인 ask 뒤만)면 사실 있는 번호는 다시 쓰기(F)
   choose ── 질문 글 ← rules/identify.yaml(H) / 그 컨테이너의 후보 줄을 cargos에서 뺌(K)
트레이스(src/marvia/trace.py, langfuse_trace.py)
   J _safe_host: 역슬래시·공백이면 거짓 / I ② _clean: JSON 값은 읽어서 가리고 다시 적음, ISO 시각은 둠
```

**Tech Stack:** 새 의존성 없음. 파이썬 쪽은 Starlette 서버, LangGraph 식별 서브그래프, Langfuse 5.0.4의 `mask_otel_spans` 겹을 고친다. 화면은 Next.js 16.4.3, Playwright 1.64.1 공식 이미지(compose e2e, 바깥 막힌 망)에서 흐름을 본다.

**Spec:** `docs/specs/2026-10-28-marvia-v2-design.md` (4.1, 4.2, 6.3, 8, 10, 11, 13절). 항목의 출처는 저장소 밖 검토 기록이다: 4b 전체 검토 S-5(A)·S-14(B)·S-12(C)·S-16(D), 4b 진행 기록의 "삭제 버튼 다듬기"(E), 6a 전체 검토 C-3(F)·C-6(H), 6a 마지막 검토 minor 3(G)·minor 4(K), 6b 전체 검토 L-4(I), 6b 진행 기록의 주소 검사(J). 각 항목은 HEAD(`7f715dc`)의 코드에서 다시 확인했고, 이미 고친 부분은 "결정과 근거"에 적고 뺐다.

## 계획 나눔

| 계획 | 범위 | 상태 |
|---|---|---|
| 3a~6b | 답, 도구 루프, 기억·조사·감시, 평가, GraphRAG·MCP, 화면·배포 준비, 컨테이너 번호, Langfuse 트레이스 | 완료 (11-02~11-08) |
| **6c (이 문서)** | 지난 검토에서 넘긴 고침 열한 가지(A~K, C는 서버 쪽만) | 11-08 시작, 11-09 정오 끝 |
| 6c 뒤 | 배포(R-038 뒤), 실제 Langfuse·UNI-PASS로 보내 보기 | 직접 할 일 |

## 결정과 근거 (11-08)

| 결정 | 이유 | 틀렸을 때 비용 |
|---|---|---|
| 항목 C의 화면 쪽(승인 카드의 깊이 선택지와 도구 한국어 이름)은 뺀다. 대화 id 상한 64만 `rules/server.yaml`로 옮긴다 | 4b 마무리 커밋 `aef50e7`에서 이미 고쳤다: `view.interrupt_card`가 `approval.labels`와 `memory.depths`를 카드의 `label`·`choices`로 싣고, `ApprovalCardView.tsx`는 `action.label`·`action.choices`만 쓴다 [실측: HEAD 코드 읽기] | 없음 |
| 태스크 순서는 자를 순서의 반대다: A, B, F, G, J, 그다음 D, I, E, C, H, K | 자를 순서가 K, H, C, E, I, D다. 뒤에서부터 자르면 남은 커밋이 그대로 쓸 수 있다 | 없음 |
| A: 지우는 중인 사용자를 `deleting` 집합에 넣고(`guard` 안), 그동안 그 사용자의 `/agui`와 두 번째 `DELETE /account`를 409로 막고, `finally`에서 뺀다 | 409 확인과 지우기 사이에 시작한 차례가 지운 대화 기록·기억을 다시 쓸 수 있었다(코드 주석이 적어 둔 빈틈). 두 번째 삭제를 막지 않으면 먼저 끝난 쪽이 집합에서 빼 첫 지우기가 도는 동안 막힘이 풀린다 | 지우기가 아주 오래 걸리면 그동안 그 사용자는 새 질문을 못 한다(409 "계정을 지우는 중이에요"). 다른 사용자는 막지 않는다 |
| A의 새 거절 글은 `server.py`의 다른 거절 글 옆에 둔다(규칙 파일로 옮기지 않는다) | 서버의 거절 글 여섯이 모두 `server.py`에 있다. 이 묶음이 규칙으로 옮기는 것은 대화 id 상한(C)과 식별 질문 글(H)이다 | 서버 거절 글을 바꿀 때 코드를 고친다 |
| B: 서버는 지난 카드 409에만 `code: "stale_card"`를 싣고(`Refused`에 `code` 칸), 화면은 409의 글을 서버 본문 `error`에서 받아 그대로 보이며 카드는 `code`가 `stale_card`일 때만 치운다 | 409 까닭이 셋(답하는 중, 지난 카드, 계정 삭제 중)이고 셋 다 서버가 정한 고정 글이다. 재개 요청도 "답하는 중" 409를 받을 수 있어(앞 차례가 잠금을 풀기 전) 요청 종류만으로는 카드를 치울지 정할 수 없다. 글을 맞춰 보는 대신 칸 하나를 둔다 | 프록시가 JSON이 아닌 409를 주면 화면은 정해 둔 글("앞 차례가 아직 끝나지 않았거나 지난 카드예요")을 보이고 카드를 둔다 |
| B·E의 화면 시험은 409·401 응답을 Playwright `page.route`로 흉내 낸다 | 가짜 API로는 "잠금이 아직 안 풀린 틈"과 "만료된 토큰"을 만들 수 없다. 교차 출처 응답이라 `access-control-allow-origin`을 함께 준다(Playwright가 사전 요청을 받는다) [실측 11-08] | 실제 서버의 409·401과 본문 모양이 어긋나면 화면 시험은 통과한다. 서버 본문은 파이썬 시험이 따로 본다 |
| F: 조회 서브그래프에 `reuse` 칸을 두고 메인 그래프의 ask 뒤 조회만 켠다. 켜면 공책 `cargos`에 사실이 있는 B/L·화물관리번호는 다시 조회하지 않는다(도구 `lookup_cargo`의 `have`와 같은 규칙). `read`가 질문으로 끝나면 `cargos`를 비운다 | 식별 안의 조회는 지난 차례 화물(컨테이너 맞추기용)을 보므로 거기서 다시 쓰면 지난 차례 사실을 이번 것으로 쓴다. ask 앞의 `cargos`는 컨테이너 질문이면 이번 차례 식별 결과이고, 애매한 덩어리·오타 질문이면 `read`가 비운 빈 칸이다. 비우지 않으면 지난 차례에 본 B/L이 애매한 질문 차례에 다시 조회되지 않는다 [실측 11-08: 비우는 줄을 뺀 사본에서 `assert 1 == 2`] | 애매한 덩어리·오타 카드가 떠 있는 동안 화면에서 지난 차례 화물 카드가 사라진다(번호 없는 차례가 화물 칸을 비우는 것과 같다) |
| F는 같은 글의 B/L만 다시 쓰고, 고른 후보 B/L의 두 번째 조회는 남긴다 | 후보는 식별 안 `known_cargo`가 조회하지만 결과가 화물 칸에 남지 않는다(후보 줄만 남는다). 후보 사실을 들고 다니려면 공책 칸을 더해야 한다. 지금 후보는 재생 모드에서만 생긴다(`facts_carry_containers`) | 실제 응답에 컨테이너 칸이 생겨 실제 모드에서 후보가 나오면 고른 후보마다 UNI-PASS 호출이 한 번 더 든다. 그때 고친다 |
| G: 번호 중복은 조회 서브그래프의 첫 노드 `assign` 한 곳에서 뺀다(처음 순서 유지) | 식별 안 조회, ask 뒤 조회, 도구 `lookup_cargo`가 부르는 조회가 모두 이 노드를 지난다 | 같은 오타를 두 번 적으면 오타 카드의 이름표가 `[BL1] + [BL1]`로 보인다(`read`의 오타 목록, 조회 전). 조회와 답 줄은 하나다 |
| J: `_safe_host`는 역슬래시나 공백 글자가 하나라도 있으면 거짓이다(https 주소도) | `http://evil.test\@localhost`는 `urlsplit`이 localhost로 읽지만 urllib3 2.8.0은 evil.test로 읽는다 [실측 11-08: `parse_url(...).host == 'evil.test'`]. 탭은 `urlsplit`이 지우고 requests 2.34.2는 `%09`로 남긴다 [실측]. 읽는 쪽마다 다른 글자는 받지 않는다 | 주소에 끝 공백이 섞인 설정은 서버 시작에서 거절된다(지금은 그대로 뜬다) |
| I: ② 겹(`scrub_spans`)의 `_clean`이 JSON으로 읽히는 글은 읽어서 가린 뒤 `ensure_ascii=False`로 다시 적는다. 수는 읽기 전 글자로 보고(`parse_int`·`parse_float`) 번호처럼 생기면 `[가림]` 글로 바꾼다. 엄격한 ISO 시각 꼴(`YYYY-MM-DDTHH:MM:SS[.f][Z|±HH:MM]`, ASCII 숫자)인 글은 그대로 둔다. 가릴 것이 없으면 SDK가 적은 글 그대로다 | SDK는 `langfuse.trace.metadata.*` 값과 `completion_start_time`을 JSON 글로 적는다(`langfuse/_client/attributes.py`). 글로 가리면 `\n` 뒤 덩어리가 `\[가림]`이 되어 JSON이 깨지고(`JSONDecodeError: Invalid \escape`) [실측 11-08], 시각은 `[가림]:34:56`이 된다. 12자리 수는 JSON에서 수로 읽혀 글 가림을 지나므로 읽기 전 글자로 본다 | 가린 뒤 겹치는 키는 뒤 값만 남는다(값을 잃을 뿐 번호는 나가지 않는다). ①(`mask=scrub`)은 바꾸지 않는다 |
| D: `next dev`·`next start`에 `-H 127.0.0.1`을 붙이고, e2e 이미지는 `RUN chown pwuser /work` 뒤 `USER pwuser`로 돈다. `npm ci`는 root로 한다 | `-H` 없는 `next start`는 모든 주소(`::`)에서 듣는다 [실측 11-08: node:22 컨테이너의 `/proc/net/tcp6`]. `-H 127.0.0.1`이면 `npm start`·`npm run dev` 모두 127.0.0.1에서만 듣는다 [실측]. `chown` 줄이 없으면 Playwright가 `EACCES: permission denied, mkdir '/work/test-results'`로 바로 끝난다 [실측]. 스크린샷은 compose가 붙이는 폴더에 쓴다(`e2e` 폴더 주인은 바꾸지 않아도 된다) [실측] | 이미지와 Dockerfile `runtime`·`web` 이미지는 바뀌지 않는다(그쪽은 `node server.js`, `MARVIA_HOST`). Linux의 바인드 마운트에서 pwuser가 스크린샷 폴더에 쓸 수 있는지는 보지 못했다(확인하지 못한 것) |
| E: 계정 삭제의 409도 서버 글을 보인다. 그래서 서버의 "답하는 중" 삭제 거절 글을 화면이 쓰던 글("답하는 중인 대화가 있어요. 끝난 뒤 다시 눌러 주세요")로 바꾼다 | A가 더한 "계정을 지우는 중이에요" 409를 화면이 "답하는 중"으로 잘못 보이지 않게 한다. 화면에 보이는 글은 지금과 같다 | 없음 |
| E: 확인이 뜨면 초점을 확인 묶음(`role=group`, `tabIndex=-1`)으로 옮긴다(선택지·승인 카드와 같은 방식). 204 뒤 대화 줄·패널·카드를 비운다. 401이면 차례 보내기처럼 로그아웃한다 | 4b 마무리에서 미룬 네 가지(브라우저 시험, 401 로그아웃, 확인에 초점, 지운 뒤 대화 남음) | 로그아웃 버튼으로 나갔다 다시 들어오면 대화가 남는 것은 그대로다(같은 계정이다) |
| H: 식별 질문 글을 새 규칙 파일 `rules/identify.yaml`에 둔다. 글은 한 글자도 바꾸지 않는다 | `rules/unipass.yaml`은 UNI-PASS 호출 설정이다. 기존 글자 시험(`test_identify.py`의 오타 질문 두 곳, `test_main.py`의 "조회하지 않음" 두 곳)이 고치지 않은 채 통과해 글이 같음을 본다. 지시문(`prompts/`)과 평가셋은 바꾸지 않는다 | 없음 |
| K: `choose`가 그 컨테이너의 후보 줄을 공책 `cargos`에서 뺀다. 기존 식별 시험 하나(`test_a_container_on_two_watched_cargos_is_left_as_candidates`)는 같은 단언을 조회 서브그래프 출력에서 본다 | 카드는 "어느 화물을 볼까요?"인데 화물 카드가 "B/L 번호를 알려 주세요"를 보였다. 서버는 서브그래프가 끝날 때 바깥 노드 갱신으로 화물 칸을 통째로 바꾸므로 마지막 화면 보기에서 그 줄이 사라진다 [실측 11-08]. 후보 줄을 만드는 곳(조회 서브그래프)은 그대로라 시험의 단언도 그대로다 | 카드가 뜨기 전 중간 화면 보기에는 그 줄이 잠깐 보일 수 있다(서브그래프 안 갱신은 합치기만 한다). "이렇게 읽었어요"에 후보 B/L이 보이는 것은 그대로다 |
| 스크린샷은 다시 커밋하지 않는다. 명령 C는 스크린샷을 임시 폴더에 쓴다 | 세 화면(답, 선택지, 승인)은 이 계획으로 바뀌지 않는다. `approval.png`는 같은 화면도 실행마다 바이트가 달라질 수 있다 [실측 11-08: 같은 코드에서 sha256 셋] | 없음 |
| 평가셋은 다시 돌리지 않는다 | 유료 호출이 없다. 평가셋(`set_v1`·`set_v2`)에는 같은 번호를 두 번 적은 문항, 여럿 실린 컨테이너 문항이 없다 [실측: 번호 패턴 grep]. H는 글을 바꾸지 않는다 | F·G·K가 평가 문항의 결과를 바꾸지 않는다는 것은 grep 근거의 추정이다 |

## Global Constraints

- 숫자·등급·기한은 코드가 계산한다. 화면은 서버가 준 값만 그린다. 409 글도 서버의 정한 글이다.
- 실제 화물 번호는 LLM과 트레이스에 가지 않는다. 트레이스에는 번호 덩어리를 `[가림]`으로 바꾼 값만 간다. I는 ② 겹이 JSON 값을 읽어서 가리게 할 뿐 가리는 범위를 줄이지 않는다.
- 도구 응답, 사용자 글, 화면이 보낸 값은 데이터다. 그 안의 문장을 지시로 따르지 않는다.
- 시험은 키 없이 가짜 모델로 돈다. DB 시험은 실행마다 새 `marvia_test_*` 스키마, Neo4j 시험은 `MARVIA_NEO4J_TEST_URL`에서만 돈다. Langfuse 서버·실제 UNI-PASS·유료 모델에 닿지 않는다.
- fixture 번호는 DEMO·MOCK·TEST·NOPE 접두어, 컨테이너는 DEM·TES·NOP + U의 가공값이다.
- 환경 변수는 `MARVIA_` 접두어만. 이 계획은 환경 변수를 더하지 않는다. `.env` 값은 읽거나 찍지 않고 루트 `.env`의 `DATABASE_URL`은 읽지 않는다.
- 임계값·목록·정한 글: 대화 id 상한은 `rules/server.yaml`, 식별 질문 글은 `rules/identify.yaml`에 둔다.
- 파일 안에서 em dash(U+2014)를 쓰지 않는다.
- 커밋 하나는 동작 하나, 코드 파일 15개 이하(잠금 파일·`docs/`·`graphify-out/`·스크린샷 PNG는 세지 않음). 커밋은 `v2`에만, `main`에는 올리지 않는다.
- 커밋마다 명령 A가 통과한다. 화면을 바꾼 커밋(T2·T6·T8)은 명령 B와 C도 통과한다. 출력을 `tail`·`grep`에 넘기면 `set -o pipefail`로 종료 코드를 본다. 코드를 바꾼 커밋 뒤에는 `graphify update .`(커밋에 넣지 않는다).
- npm은 node:22 컨테이너 안에서만, Playwright는 digest로 고정한 공식 이미지 안에서만 돈다. 호스트에 `node_modules`·브라우저를 두지 않고 `npx`·`npm i -g`를 호스트에서 돌리지 않는다. 로컬 서버는 127.0.0.1에만, 8000이 아닌 포트로 연다.
- compose는 버린 이름(`-p marvia-6c`)으로만 띄우고 끝나면 `down --rmi local`로 지운다. 기본 이름(`marvia-v2`)의 컨테이너는 올리거나 내리지 않는다. 개발 Neo4j(7688)에는 붙지 않는다.

명령 A (파이썬 검사, 저장소 뿌리에서):

```bash
set -o pipefail
uv run pytest -q 2>&1 | tail -2 && uv run ruff check . && uv run ruff format --check . && uv run pyright | tail -1
```

명령 B (화면 타입 검사·빌드, 계획 4b와 같다):

```bash
# web/을 읽기 전용으로 붙이고 컨테이너 안 복사본에서 돈다(호스트에 node_modules·.next를 남기지 않는다)
docker run --rm -v "$PWD/web":/src:ro -v marvia-npm-cache:/root/.npm -e NEXT_TELEMETRY_DISABLED=1 \
  node:22-bookworm-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d \
  sh -c "mkdir /app && tar -C /src --exclude=./node_modules --exclude=./.next -cf - . | tar -C /app -xf - && cd /app \
         && npm ci --no-audit --no-fund >/dev/null && npx tsc --noEmit && npx next build >/dev/null && echo web-ok"
```

명령 C (화면 흐름: 공식 Playwright 이미지, 바깥 막힌 compose 망, 버린 이름 `marvia-6c`):

```bash
# [왜] 스크린샷은 임시 폴더에 쓴다. 저장소의 그림을 바꾸지 않는다(이 계획은 세 화면을 바꾸지 않는다)
set -o pipefail
shots=$(mktemp -d /tmp/marvia-6c-shots.XXXX)
printf 'services:\n  playwright:\n    volumes:\n      - %s:/work/e2e/screenshots\n' "$shots" > "$shots.yml"
dc() { docker compose -p marvia-6c -f docker-compose.yml -f "$shots.yml" --profile e2e "$@"; }
dc build api-e2e web-e2e playwright >/dev/null && docker run --rm --entrypoint id marvia-6c-playwright -un
dc run --rm playwright 2>&1 | grep -E "✓|✘|passed|failed|Expected|Received"
dc down --rmi local
ls "$shots"
```

첫 줄은 시험 이미지의 실행 사용자, 그다음은 흐름별 결과, 마지막은 스크린샷 셋(`answer.png approval.png choice.png`)이다. `down --rmi local`이 이 이름으로 만든 이미지 셋을 지운다 [실측 11-08: 지운 뒤 `marvia-6c-*` 이미지 0개].

- 코드 블록 검증: v2 HEAD(`7f715dc`)를 내보낸 깨끗한 사본에 이 문서의 diff를 커밋 순서대로 넣고, 커밋마다 Docker(`ghcr.io/astral-sh/uv@sha256:e5b65587…`, 망 `marvia-v2_default`, compose의 Postgres `marvia_verify`, 버린 시험용 Neo4j)에서 `MARVIA_REQUIRE_DB=1`, `MARVIA_REQUIRE_NEO4J=1`로 시험 전체와 `ruff check`·`ruff format --check`·`pyright`를 돌렸다: HEAD 818 → 커밋 1 819 → 커밋 2 820 → 커밋 3 822 → 커밋 4 824 → 커밋 5 827 → 커밋 6 828 → 커밋 7 829 → 커밋 8 829 → 커밋 9 830 → 커밋 10 831 → 커밋 11 832 통과(문서 커밋 뒤에도 832) (건너뜀 0), 커밋마다 ruff·형식·pyright 오류 0 [실측 11-08]. 각 커밋의 "먼저 실패" 줄은 앞 커밋의 코드에 그 커밋의 시험만 얹어 돌려 얻었다. 화면 커밋(T2·T6·T8)은 명령 B(`web-ok`)와 명령 C(버린 compose 이름)를 돌렸다. 아래 Expected의 수는 818에서 시작해 커밋마다 더한 시험 수다.

---
## 사전 등록: 검사 C1~C12 (구현 전에 고정)

이 절은 첫 구현 커밋 전에 이 문서와 함께 커밋하고, 결과를 본 뒤 기준을 고치지 않는다. 고칠 일이 생기면 이유와 시각을 따로 적고 원래 기준의 판정도 함께 적는다. 검사 번호는 태스크 순서다(항목 글자와 다르다). "지금 HEAD"는 HEAD 코드에 이 계획의 시험을 모두 얹어 돌린 값이다 [실측 11-08: 새 시험 13개 실패, 화면 흐름 7개 중 새 셋 실패].

| # | 항목 | 통과 기준 | 시험·명령 | 지금 HEAD |
|---|---|---|---|---|
| C1 | A 계정 삭제 중 막기 | 지우기(`forget`)를 붙잡은 동안 같은 사용자의 `/agui`가 409 "계정을 지우는 중이에요", 두 번째 `DELETE /account`가 409, 다른 사용자의 `/agui`는 200, 첫 삭제는 204, 끝난 뒤 같은 사용자의 `/agui`는 200. `running`·`deleting`의 추가·삭제·순회가 모두 `guard` 안이다 | `tests/graph/test_server.py::test_a_turn_that_starts_while_the_account_is_being_deleted_is_409`, `::test_running_is_only_touched_while_the_guard_is_held`(그대로) | 지우는 동안의 `/agui`가 200(`assert (200 == 409)`) |
| C2 | B 409 안내와 카드 | 지난 카드 409 본문이 `{"error": "답할 질문이 없거나 이미 지난 카드예요", "code": "stale_card"}`, 답하는 중 409 본문은 `{"error": "이 대화는 아직 답하는 중이에요"}`. 화면은 답하는 중 409에 그 글을 보이고 카드를 두며, `stale_card` 409에 그 글을 보이고 카드를 치운다 | `::test_only_a_409_for_a_card_that_is_gone_carries_the_stale_card_code`, 명령 C의 흐름 "409에는 서버가 보낸 까닭을 보이고, 지난 카드일 때만 카드를 치운다" | 서버 본문에 `code` 없음. 화면은 `Received: "앞 차례가 아직 끝나지 않았거나 지난 카드예요"` |
| C3 | F 같은 글의 B/L 다시 조회 안 함 | "DEMO0002 TESU0000013 어디야?"(감시 DEMO0003)에서 `[BL2]`를 고르면 DEMO0002 조회가 1번이고 답에 두 화물 줄이 있다. 애매한 덩어리 질문 차례는 지난 차례에 본 번호를 다시 조회한다(DEMO0001이 두 차례에 2번) | `tests/graph/test_main.py::test_after_a_container_card_a_bl_already_looked_up_this_turn_is_not_looked_up_again`, `::test_after_an_ambiguous_card_a_number_from_the_last_turn_is_looked_up_afresh` | DEMO0002 2번(`['DEMO0002', 'DEMO0003', 'DEMO0002', 'DEMO0003']`). 둘째 시험은 지금도 통과하는 지킴 시험이다(`read`가 비우는 줄을 빼면 `assert 1 == 2`로 실패 [실측]) |
| C4 | G 중복 빼기 | "DEMO0001 그리고 DEMO0001"은 조회 1번, 화물 줄 하나, "건으로 읽었어요" 없음. 컨테이너 카드에서 "모두"를 고르면 "2건으로 읽었어요."이고 DEMO0002 줄이 하나 | `::test_a_number_typed_twice_is_looked_up_and_shown_once`, `::test_choosing_all_cargo_on_a_container_with_its_bl_in_the_message_reads_each_cargo_once` | 줄 둘과 "2건으로 읽었어요.", "3건으로 읽었어요." |
| C5 | J 주소 거절 | `http://evil.test\@localhost`, `https://x.test\@localhost`, `http://evil.test<탭>@localhost`이 `ValueError`이고 키 글이 오류 글에 없으며 클라이언트를 만들지 않는다. 받던 주소 넷(`https://x.test`, `http://localhost`, `http://127.0.0.1:3000`, `http://[::1]:3000`)은 그대로 받는다 | `tests/graph/test_trace.py::test_a_remote_plain_http_host_is_refused_without_naming_the_keys`(6), `::test_https_or_loopback_http_host_is_accepted`(4, 그대로) | 새 셋이 `Failed: building must not start` |
| C6 | D 듣는 주소와 실행 사용자 | `web/package.json`의 `dev`·`start`에 `-H 127.0.0.1`, `web/e2e.Dockerfile`의 마지막 `USER`가 `pwuser`. 명령 C의 첫 줄이 `pwuser`이고 흐름이 모두 통과하며 스크린샷 셋이 생긴다 | `tests/test_docker.py::test_local_web_servers_listen_on_loopback_and_the_e2e_image_does_not_run_as_root`, 명령 C | `assert ('-H 127.0.0.1' in 'next dev --port 3000')`, 시험 이미지 사용자 `root` |
| C7 | I ② 겹의 JSON 가림 | SDK 꼴 JSON 글 `"gate\nDEMO0011"`을 가린 값이 JSON으로 읽히고 번호가 없다. ISO 시각 JSON 글은 그대로다. `{"bl": 123456789012, ...}`의 수와 글 속 번호가 `[가림]`이다. JSON이 아닌 글은 전처럼 가린다. 6b 문 시험(내보낸 span 전체 번호 0, 겹 빼기 넷)이 그대로 통과한다 | `::test_layer_two_reads_sdk_json_values_so_they_stay_json_and_times_stay_times`, `::test_every_exported_span_field_is_free_of_numbers`, `::test_removing_any_one_layer_leaves_its_numbers`(4) | `JSONDecodeError: Invalid \escape: line 1 column 6 (char 5)` |
| C8 | E 계정 삭제 화면 | "계정 삭제"를 누르면 확인 묶음에 초점이 가고 axe serious·critical 0. "지우기" 뒤 로그인 화면과 "계정을 지웠어요…" 글, 다시 들어오면 대화 줄 0·카드 0. 삭제가 401이면 로그인 화면과 "다시 로그인해 주세요" | 명령 C의 흐름 "계정 삭제는 확인에 초점을 옮기고, 지운 뒤 다시 들어오면 대화가 비어 있다", "계정 삭제가 401이면 로그아웃한다" | 초점 `Received: inactive`, 401 뒤 로그인 칸 없음(`element(s) not found`). 초점 줄을 뺀 사본에서는 대화 줄 `Received: 1` [실측] |
| C9 | C 대화 id 상한 | `rules/server.yaml`의 `request.max_thread_id`(64). 그 길이는 200, 하나 더 길면 422 | `tests/graph/test_server.py::test_the_thread_id_length_limit_comes_from_the_rules` | `KeyError: 'max_thread_id'` |
| C10 | H 질문 글 규칙 | 애매한 덩어리·오타·컨테이너 질문과 선택지 설명이 `rules/identify.yaml`의 글을 채운 값과 같다. 질문 글을 박은 기존 시험이 고치지 않은 채 통과한다 | `tests/graph/test_identify.py::test_question_and_choice_texts_come_from_the_rules`, 기존 `test_identify.py`·`test_main.py`·`test_agent.py` | `FileNotFoundError: ... rules/identify.yaml` |
| C11 | K 컨테이너 카드 화면 | 서버 한 차례("DEMO0001 TESU0000013 어디야?", 감시 DEMO0002·DEMO0003)가 카드로 끝나고, 마지막 화면 보기의 화물 카드가 `[("DEMO0001", None)]`이다. 후보 줄은 조회 서브그래프 출력에 그대로 있다 | `::test_the_screen_under_a_container_card_shows_no_container_many_line`, `tests/graph/test_identify.py::test_a_container_on_two_watched_cargos_is_left_as_candidates`(관찰 지점만 옮김) | 화물 카드에 `('TESU0000013', '이 컨테이너에 실린 화물이 여럿이에요. B/L 번호나 화물관리번호를 알려 주세요')` |
| C12 | 회귀·크기 | 시험 수가 818에서 줄지 않고(마지막 832), 건너뜀 0, 커밋마다 ruff·형식·pyright 오류 0. 커밋마다 코드 파일 15개 이하. `git diff 7f715dc -- eval prompts`가 비어 있다(평가셋·지시문 그대로, `set_v2` sha 시험 통과). 바뀐 파일에 em dash 0 | 명령 A, `git show --stat`, `git diff` | 818 통과, 건너뜀 0 [실측 11-08, Docker] |

## 비용

이 계획에는 유료 모델 호출, Langfuse 호출, 실제 UNI-PASS 호출이 없다($0). 시험은 가짜 모델·재생 데이터·메모리 내보내기로 돈다. 화면 흐름은 가짜 API와 바깥 막힌 망에서 돈다.

## 시간 상한, 확인점, 자를 순서

시간 상한은 하루다(11-09 정오까지). 확인점에서 늦으면 자를 순서대로 자르고 끝낸다. 자른 항목은 "남은 한계"로 적는다.

| 태스크 | 닫는 것 | 어림 | 끝났다는 증거 |
|---|---|---|---|
| T0 사전 등록 | C1~C12 고정 | 0.2시간 | 이 문서 커밋 |
| T1 A 계정 삭제 중 409 | C1 | 0.5시간 | 819 통과 |
| T2 B 409 안내 | C2 | 1시간 | 820 통과, 명령 B·C |
| T3 F 다시 조회 안 함 | C3 | 0.7시간 | 822 통과 |
| T4 G 중복 빼기 | C4 | 0.3시간 | 824 통과 |
| T5 J 주소 거절 | C5 | 0.3시간 | 827 통과 |
| **CP1 (11-08 18:00)** | T1~T5 끝났나. 아니면 D·I·E·C·H·K를 모두 자른다 | | |
| T6 D 듣는 주소·pwuser | C6 | 0.7시간 | 828 통과, 명령 B·C(`pwuser`) |
| T7 I ② JSON 가림 | C7 | 0.7시간 | 829 통과 |
| T8 E 계정 삭제 화면 | C8 | 1시간 | 829 통과, 명령 B·C 7개 |
| **CP2 (11-09 09:00)** | T6~T8 끝났나. 아니면 남은 것을 자를 순서대로 자른다 | | |
| T9 C 대화 id 상한 | C9 | 0.3시간 | 830 통과 |
| T10 H 질문 글 규칙 | C10 | 0.5시간 | 831 통과 |
| T11 K 컨테이너 카드 화면 | C11 | 0.4시간 | 832 통과 |
| T12 문서 | 설계 4.1·4.2·6.3·8·10·11·13절, 결과 표 | 0.5시간 | |
| 합 | | 약 7.1시간 | |

자르는 순서 (먼저 자르는 것부터): K → H → C → E → I → D. 태스크가 그 반대 순서라 자른 태스크 뒤에 남는 태스크가 없다.

자르지 않는 것: A, B, F, G, J와 각 태스크의 시험, T12의 결과 표.

## 파일 구조

| 파일 | 책임 | 태스크 |
|---|---|---|
| `src/marvia/server.py` | `deleting` 집합(A), `Refused.code`와 409 본문 `code`(B), 삭제 거절 글(E), 대화 id 상한(C) | T1, T2, T8, T9 |
| `rules/server.yaml` | `request.max_thread_id` | T9 |
| `web/lib/agui.ts`, `web/app/page.tsx` | 409 본문의 글·`code`(B), 계정 삭제 다듬기(E) | T2, T8 |
| `web/package.json`, `web/e2e.Dockerfile` | `-H 127.0.0.1`, `USER pwuser` | T6 |
| `web/e2e/flows.spec.ts` | 409 흐름(B), 계정 삭제 흐름 둘(E) | T2, T8 |
| `src/marvia/graph/identify.py`, `src/marvia/graph/main.py` | `read`가 물을 때 비움·`reuse`(F), `assign` 중복 빼기(G), 질문 글(H), `choose`가 후보 줄 뺌(K) | T3, T4, T10, T11 |
| `rules/identify.yaml` (새 파일) | 식별 질문·선택지 글 | T10 |
| `src/marvia/trace.py` | `_safe_host` 역슬래시·공백 거절 | T5 |
| `src/marvia/langfuse_trace.py` | ② `_clean`의 JSON 가림 | T7 |
| `docs/specs/2026-10-28-marvia-v2-design.md` | 4.1·4.2·6.3·8·10·11·13절과 변경 기록 | T12 |
| `tests/graph/test_server.py`, `test_main.py`, `test_identify.py`, `test_trace.py`, `tests/test_docker.py` | 시험 | 모두 |

---
### Task 0: 사전 등록

- [ ] **Step 1: 이 문서를 첫 구현 커밋 전에 커밋한다.** 결과를 본 뒤 C1~C12의 기준을 고치지 않는다.

```bash
git add docs/plans/2026-11-08-marvia-v2-plan-6c-fixes.md
git commit -m "docs: 계획 6c 지난 검토에서 넘긴 고침과 사전 등록 검사 C1~C12"
```

### Task 1: 계정을 지우는 동안 그 사용자의 새 차례를 막는다 (항목 A, C1)

**배울 것:** 계정 삭제는 세 저장소(감시, 장기 기억, 대화 기록)를 차례로 지우는 긴 일이다. 지금은 "그 사용자의 차례가 도는 중인가"를 시작할 때 한 번만 본다. 그 확인을 지난 뒤 지우는 동안 새 차례가 시작되면 지운 대화 기록을 다시 쓴다. 확인과 표시를 같은 잠금(`guard`) 안에서 하고, 표시(`deleting`)는 지우기가 끝나거나 실패해도 `finally`에서 뺀다. `running`과 같은 잠금을 쓰므로 기존 결정적 잠금 시험이 새 집합의 추가·삭제도 본다.

#### 커밋 1: fix(server): 계정을 지우는 동안 그 사용자의 새 차례와 두 번째 삭제를 409로 막음

**Files:**
- Modify: `src/marvia/server.py`
- Test: `tests/graph/test_server.py`

**Interfaces:**
- Produces: `/agui`와 `DELETE /account`의 새 409 본문 `{"error": "계정을 지우는 중이에요"}`

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/graph/test_server.py
+++ b/tests/graph/test_server.py
@@ -649,6 +649,32 @@ def test_account_deletion_is_409_while_a_turn_of_that_user_runs():
     assert forgotten == ["user-b"]
 
 
+def test_a_turn_that_starts_while_the_account_is_being_deleted_is_409():
+    # [왜] 409 확인 뒤 지우는 동안 시작한 차례는 지운 대화 기록·기억을 다시 쓸 수 있다 (계획 6c)
+    entered, gate, codes = threading.Event(), threading.Event(), []
+
+    def slow_forget(user: str) -> None:
+        entered.set()
+        gate.wait(10)  # [왜] 지우기를 붙잡아 둔 채 같은 사용자의 새 차례와 두 번째 삭제를 보낸다
+
+    client = TestClient(build_app(Stub(), verify, web_origin="http://x.test", forget=slow_forget))
+    mine, other = {"Authorization": "Bearer tok-a"}, {"Authorization": "Bearer tok-b"}
+    worker = threading.Thread(
+        target=lambda: codes.append(client.delete("/account", headers=mine).status_code)
+    )
+    worker.start()
+    assert entered.wait(10)
+    during = client.post("/agui", json=body("t24", "질문"), headers=mine)
+    again = client.delete("/account", headers=mine)
+    someone = client.post("/agui", json=body("t24", "질문"), headers=other)
+    gate.set()
+    worker.join(10)
+    assert during.status_code == 409 and during.json()["error"] == "계정을 지우는 중이에요"
+    assert again.status_code == 409 and someone.status_code == 200  # 다른 사용자는 막지 않는다
+    assert codes == [204]
+    assert client.post("/agui", json=body("t24", "질문"), headers=mine).status_code == 200  # 끝나면 푼다
+
+
 def test_running_is_only_touched_while_the_guard_is_held(monkeypatch):
     # [왜] 잠금 밖의 변경은 시간이 맞아야만 드러나서(GIL) 아래의 스레드 시험은 못 잡는다. 여기서는 running의
     #      추가·삭제·순회가 일어날 때마다 잠금이 잡혀 있는지를 직접 본다 (한 번에 한 요청씩이라 결정적이다)
```

- [ ] **Step 2: 실패를 본다**

```bash
uv run pytest -q tests/graph/test_server.py -k being_deleted
```

Expected: `1 failed`. `assert (200 == 409)` (지우는 동안의 `/agui`가 200이다). 두 번째 삭제가 붙잡힌 지우기를 기다리므로 약 10초 걸린다 [실측 11-08].

- [ ] **Step 3: 코드**

```diff
--- a/src/marvia/server.py
+++ b/src/marvia/server.py
@@ -270,6 +270,7 @@ def build_app(
     # [왜] 이 앱이 부르는 그래프는 user_id 없이 사용자 데이터에 닿으면 멈춘다 (tools.user_of, R-048)
     graph = graph.with_config(configurable={"surface": SERVER_SURFACE}, callbacks=list(callbacks))
     running: set[str] = set()
+    deleting: set[str] = set()  # 계정을 지우는 중인 사용자. 그동안 그 사용자의 새 차례와 삭제를 409로 막는다
     guard = threading.Lock()
     cfg = load_rules("server")["request"]
 
@@ -293,6 +294,9 @@ def build_app(
             return JSONResponse({"error": "대화 id 모양이 틀렸어요"}, status_code=422)
         key = f"{user}/{body.thread_id}"
         with guard:
+            # [왜] 지우는 동안 시작한 차례는 지운 대화 기록·기억을 다시 쓴다. 삭제가 끝날 때까지 막는다
+            if user in deleting:
+                return JSONResponse({"error": "계정을 지우는 중이에요"}, status_code=409)
             if key in running:
                 return JSONResponse({"error": "이 대화는 아직 답하는 중이에요"}, status_code=409)
             running.add(key)
@@ -318,9 +322,16 @@ def build_app(
         except AuthError as error:
             return JSONResponse({"error": str(error)}, status_code=error.status)
         with guard:  # [왜] /agui와 같은 잠금. 그 사용자의 차례가 도는 중이면 지워도 기록이 다시 생긴다
+            if user in deleting:
+                return JSONResponse({"error": "계정을 지우는 중이에요"}, status_code=409)
             if any(key.startswith(f"{user}/") for key in running):
                 return JSONResponse({"error": "답하는 중인 대화가 있어요"}, status_code=409)
-        await anyio.to_thread.run_sync(forget, user)
+            deleting.add(user)
+        try:
+            await anyio.to_thread.run_sync(forget, user)
+        finally:
+            with guard:  # [왜] 지우기가 실패해도(500) 그 사용자를 영영 막지 않는다
+                deleting.discard(user)
         return Response(status_code=204)
 
     async def health(request: Request) -> Response:
@@ -350,8 +361,8 @@ def forget_account(conn: psycopg.Connection, store: BaseStore, user: str, url: s
     [주의] 하나의 트랜잭션이 아니다. 감시(forget_user), 장기 기억(Store의 자기 연결), 대화 기록(아래 한
            트랜잭션)이 차례로 따로 커밋된다. 중간에 죽으면 500이고, 셋 다 다시 불러도 안전해서(없으면 0줄)
            같은 요청을 다시 보내면 마저 지워진다. 지우는 동안 그 사용자의 차례가 돌고 있으면 그 차례가 대화
-           기록을 다시 쓸 수 있어, DELETE /account는 그 사용자의 차례가 도는 중이면 409로 거절한다.
-           (거절한 뒤에 시작한 차례까지는 막지 않는다.)
+           기록을 다시 쓸 수 있어, DELETE /account는 그 사용자의 차례가 도는 중이면 409로 거절하고,
+           지우는 동안 들어온 그 사용자의 /agui도 409로 거절한다(build_app의 deleting).
     [왜] conn은 감시 전용 공유 연결이다. 그 위에 트랜잭션을 열면 다른 사용자의 감시 문장이 섞인다(R-041).
          대화 기록 삭제는 url로 짧게 연 자기 연결에서 한다.
     """
```

- [ ] **Step 4: 확인**: 명령 A. Expected: `819 passed`, ruff·형식·pyright 오류 0 [실측 11-08].

- [ ] **Step 5: 커밋**

```bash
git add src/marvia/server.py tests/graph/test_server.py
git commit -m "fix(server): 계정을 지우는 동안 그 사용자의 새 차례와 두 번째 삭제를 409로 막음"
```

### Task 2: 409에는 서버가 정한 까닭을 보이고, 지난 카드일 때만 카드를 치운다 (항목 B, C2)

**배울 것:** 409(충돌)는 셋 중 하나다: 같은 대화의 앞 차례가 아직 잠금을 쥐고 있다, 답할 카드가 이미 지났다, 계정을 지우는 중이다. 지금 화면은 셋을 한 글로 보이고 카드를 늘 치운다. 그래서 끊긴 뒤 바로 다시 묻거나, 카드가 뜬 직후 잠금이 풀리기 전에 답하면 아직 살아 있는 카드가 사라진다. 서버가 까닭을 칸(`code`)으로 알려 주면 화면은 글만 보이고 카드 처리는 그 칸으로 정한다. 화면 시험은 Playwright `page.route`로 409 응답을 흉내 낸다. 화면(`web-e2e:3000`)과 API(`api-e2e:8080`)는 출처가 달라 흉내 낸 응답에도 `access-control-allow-origin`이 있어야 브라우저가 읽는다.

#### 커밋 2: fix(web): 409는 서버가 정한 글을 보이고 지난 카드일 때만 카드를 치움

**Files:**
- Modify: `src/marvia/server.py`, `web/lib/agui.ts`, `web/app/page.tsx`
- Test: `tests/graph/test_server.py`, `web/e2e/flows.spec.ts`

**Interfaces:**
- Produces: `Refused(status, message, code=None)`, `/agui`의 거절 본문 `{"error": str, "code": str | null}`(지난 카드만 `"stale_card"`), `HttpError(status, reason={})`와 `HttpError.code: string | null`
- Consumes: 없음

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/graph/test_server.py
+++ b/tests/graph/test_server.py
@@ -675,6 +675,32 @@ def test_a_turn_that_starts_while_the_account_is_being_deleted_is_409():
     assert client.post("/agui", json=body("t24", "질문"), headers=mine).status_code == 200  # 끝나면 푼다
 
 
+def test_only_a_409_for_a_card_that_is_gone_carries_the_stale_card_code():
+    # [왜] 화면은 이 code를 볼 때만 카드를 치운다. 앞 차례가 아직 도는 409에 카드를 치우면
+    #      아직 답할 수 있는 카드가 사라진다 (계획 6c)
+    entered, gate = threading.Event(), threading.Event()
+
+    class Slow(Stub):
+        def stream(self, *args, **kwargs):
+            entered.set()
+            gate.wait(10)
+            return iter([])
+
+    client = TestClient(build_app(Slow(), verify, web_origin="http://x.test", forget=print))
+    head = {"Authorization": "Bearer tok-a"}
+    resume = [{"interruptId": "x", "status": "resolved", "payload": {}}]
+    gone = client.post("/agui", json=body("t25", resume=resume), headers=head)
+    worker = threading.Thread(target=lambda: run(client, body("t25", "질문")))
+    worker.start()
+    assert entered.wait(10)
+    busy = client.post("/agui", json=body("t25", resume=resume), headers=head)
+    gate.set()
+    worker.join(10)
+    assert gone.status_code == busy.status_code == 409
+    assert gone.json() == {"error": "답할 질문이 없거나 이미 지난 카드예요", "code": "stale_card"}
+    assert busy.json() == {"error": "이 대화는 아직 답하는 중이에요"}
+
+
 def test_running_is_only_touched_while_the_guard_is_held(monkeypatch):
     # [왜] 잠금 밖의 변경은 시간이 맞아야만 드러나서(GIL) 아래의 스레드 시험은 못 잡는다. 여기서는 running의
     #      추가·삭제·순회가 일어날 때마다 잠금이 잡혀 있는지를 직접 본다 (한 번에 한 요청씩이라 결정적이다)
--- a/web/e2e/flows.spec.ts
+++ b/web/e2e/flows.spec.ts
@@ -77,3 +77,29 @@ test("승인 카드에서 거절하면 하지 않는다", async ({ page }) => {
   await expect(answers(page)).toContainText("확인한 내용을 정리했어요");
   await expect(answers(page)).not.toContainText("이번 차례에 한 일");
 });
+
+test("409에는 서버가 보낸 까닭을 보이고, 지난 카드일 때만 카드를 치운다", async ({ page }) => {
+  await ask(page, "장치기간이 궁금해요");
+  const card = page.getByRole("heading", { name: "어느 항구 기준으로 볼까요?" });
+  await expect(card).toBeVisible();
+  // [왜] 앞 차례가 아직 잠금을 쥔 틈과 지난 카드는 가짜 API로 만들 수 없다. 서버가 보내는 409 본문을 흉내 낸다
+  const refuse = (reason: object) =>
+    page.route("**/agui", (route) =>
+      route.fulfill({
+        status: 409,
+        contentType: "application/json",
+        headers: { "access-control-allow-origin": new URL(page.url()).origin },
+        body: JSON.stringify(reason),
+      }),
+    );
+  await refuse({ error: "이 대화는 아직 답하는 중이에요" });
+  await page.getByRole("button", { name: /인천/ }).click();
+  const told = page.locator('p[role="alert"]'); // [왜] Next의 경로 안내(role=alert)와 겹치지 않게 화면 글만 본다
+  await expect(told).toHaveText("이 대화는 아직 답하는 중이에요");
+  await expect(card).toBeVisible();
+  await page.unroute("**/agui");
+  await refuse({ error: "답할 질문이 없거나 이미 지난 카드예요", code: "stale_card" });
+  await page.getByRole("button", { name: /인천/ }).click();
+  await expect(told).toHaveText("답할 질문이 없거나 이미 지난 카드예요");
+  await expect(card).toBeHidden();
+});
```

- [ ] **Step 2: 실패를 본다**

```bash
uv run pytest -q tests/graph/test_server.py -k stale_card_code
```

Expected: `1 failed`. `AssertionError: assert {'error': '답할...나 이미 지난 카드예요'} == {'error': '답할... 'stale_card'}` (`Right contains 1 more item: {'code': 'stale_card'}`) [실측 11-08].

그다음 명령 C. Expected: `1 failed`, `4 passed`. 새 흐름이 `Expected: "이 대화는 아직 답하는 중이에요"`, `Received: "앞 차례가 아직 끝나지 않았거나 지난 카드예요"`로 실패한다 [실측 11-08].

- [ ] **Step 3: 코드**

```diff
--- a/src/marvia/server.py
+++ b/src/marvia/server.py
@@ -80,11 +80,11 @@ CHOICE_KEYS = ("selected", "custom", "timeout")  # 선택지 재개 값에서 
 
 
 class Refused(Exception):
-    """그래프를 부르기 전에 요청을 거절한다. status에 상태 코드를 둔다."""
+    """그래프를 부르기 전에 요청을 거절한다. status에 상태 코드, code에 화면이 갈래를 나눌 까닭을 둔다."""
 
-    def __init__(self, status: int, message: str) -> None:
+    def __init__(self, status: int, message: str, code: str | None = None) -> None:
         super().__init__(message)
-        self.status = status
+        self.status, self.code = status, code
 
 
 def _merge(live: dict, update: dict, inside: bool) -> bool:
@@ -184,7 +184,8 @@ def turn_input(graph, body: RunAgentInput, config: dict) -> Any:
     if body.resume:
         state = graph.get_state(config)
         if not state.interrupts or body.resume[0].interrupt_id != state.interrupts[0].id:
-            raise Refused(409, "답할 질문이 없거나 이미 지난 카드예요")
+            # [왜] 화면은 이 code일 때만 카드를 치운다. 다른 409(답하는 중, 계정 삭제 중)의 카드는 살아 있다
+            raise Refused(409, "답할 질문이 없거나 이미 지난 카드예요", code="stale_card")
         value, raw = state.interrupts[0].value, body.resume[0].payload
         # [왜] 취소한 카드는 payload를 읽지 않는다. 선택지는 권장안으로, 승인은 모두 거절로 간다
         raw = raw if isinstance(raw, dict) and body.resume[0].status == "resolved" else {}
@@ -305,7 +306,7 @@ def build_app(
             payload = await anyio.to_thread.run_sync(turn_input, graph, body, config)
         except Refused as error:
             release(key)
-            return JSONResponse({"error": str(error)}, status_code=error.status)
+            return JSONResponse({"error": str(error), "code": error.code}, status_code=error.status)
         except BaseException:
             release(key)
             raise
--- a/web/app/page.tsx
+++ b/web/app/page.tsx
@@ -82,8 +82,9 @@ export default function Home() {
             ? failure.message
             : "서버에 닿지 못했어요. 잠시 뒤 다시 해 주세요",
         );
-        // [왜] 409만 지난 카드이거나 앞 차례가 안 끝난 경우다. 422는 서버가 카드를 그대로 열어 두므로 다시 보낼 수 있다
-        if (failure instanceof HttpError && failure.status === 409) setCard(null);
+        // [왜] 카드는 서버가 지난 카드라고 할 때(stale_card)만 치운다. 답하는 중·계정 삭제 중(409)과
+        //      422는 카드가 아직 살아 있어 다시 보낼 수 있다
+        if (failure instanceof HttpError && failure.code === "stale_card") setCard(null);
         if (failure instanceof HttpError && failure.status === 401) signOut().then(() => setToken(null));
       } finally {
         sending.current = false;
--- a/web/lib/agui.ts
+++ b/web/lib/agui.ts
@@ -62,18 +62,26 @@ export function newId(): string {
   return Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
 }
 
-// 서버가 거절한 상태 코드. 화면이 코드별로 안내하고 응답 본문은 보이지 않는다
+// 서버가 거절한 상태 코드. 화면이 코드별로 정해 둔 글로 안내한다.
+// [왜] 409만 까닭이 셋(답하는 중, 지난 카드, 계정 삭제 중)이라 서버가 정한 글(error)과 까닭(code)을 받아 보인다
 export class HttpError extends Error {
-  constructor(readonly status: number) {
+  readonly code: string | null;
+  constructor(
+    readonly status: number,
+    reason: { error?: unknown; code?: unknown } = {},
+  ) {
     super(
-      status === 401
-        ? "다시 로그인해 주세요"
-        : status === 409
-          ? "앞 차례가 아직 끝나지 않았거나 지난 카드예요"
-          : status === 413 || status === 422
-            ? "질문이 너무 길거나 모양이 틀렸어요"
-            : `서버가 요청을 받지 않았어요 (${status})`,
+      status === 409 && typeof reason.error === "string"
+        ? reason.error
+        : status === 401
+          ? "다시 로그인해 주세요"
+          : status === 409
+            ? "앞 차례가 아직 끝나지 않았거나 지난 카드예요"
+            : status === 413 || status === 422
+              ? "질문이 너무 길거나 모양이 틀렸어요"
+              : `서버가 요청을 받지 않았어요 (${status})`,
     );
+    this.code = typeof reason.code === "string" ? reason.code : null;
   }
 }
 
@@ -107,7 +115,9 @@ export async function runTurn(
     signal,
   });
   if (!response.ok || !response.body) {
-    throw new HttpError(response.status);
+    // [주의] 본문이 JSON이 아니어도(프록시 오류 쪽) 정해 둔 글로 떨어진다
+    const reason = response.status === 409 ? await response.json().catch(() => ({})) : {};
+    throw new HttpError(response.status, reason);
   }
   // SSE: "data: {json}" 줄들이 빈 줄로 나뉜다. 조각이 이벤트 중간에서 끊길 수 있어 버퍼에 모은다
   const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
```

- [ ] **Step 4: 확인**: 명령 A. Expected: `820 passed`, 오류 0. 명령 B. Expected: `web-ok`. 명령 C. Expected: 첫 줄 `root`(T6 전), `5 passed`, 스크린샷 셋 [실측 11-08].

- [ ] **Step 5: 커밋**

```bash
git add src/marvia/server.py tests/graph/test_server.py web/lib/agui.ts web/app/page.tsx web/e2e/flows.spec.ts
git commit -m "fix(web): 409는 서버가 정한 글을 보이고 지난 카드일 때만 카드를 치움"
```

### Task 3: 컨테이너 선택지 뒤 이번 차례에 이미 조회한 B/L을 다시 조회하지 않는다 (항목 F, C3)

**배울 것:** 메인 그래프는 식별 서브그래프 다음 질문이 있으면 `ask`에서 멈추고, 재개되면 `lookup`(식별 안과 같은 조회 서브그래프)이 `numbers` 전체를 조회한다. 컨테이너 질문은 식별 안 조회가 끝난 뒤(`choose`)에 생기므로, 그 글의 B/L은 이미 조회되어 공책 `cargos`에 사실이 있다. 애매한 덩어리·오타 질문은 조회 전(`read`)에 생기므로 `cargos`에는 지난 차례 값이 남아 있다. 그래서 "사실이 있으면 다시 쓰기"(`reuse`)는 ask 뒤 조회에만 켜고, `read`가 물을 때 `cargos`를 비워 ask 뒤 조회가 늘 이번 차례 결과만 보게 한다. `fan_out`은 조건 갈림 함수라 `reuse`를 읽으려고 `collect`처럼 빌더 안으로 옮긴다.

#### 커밋 3: fix(graph): 컨테이너 선택지 뒤 이번 차례에 이미 조회한 B/L을 다시 조회하지 않음

**Files:**
- Modify: `src/marvia/graph/identify.py`, `src/marvia/graph/main.py`
- Test: `tests/graph/test_main.py`

**Interfaces:**
- Produces: `build_lookup_graph(watched: Watched | None = None, reuse: bool = False)`. 모듈의 `fan_out` 함수는 빌더 안으로 옮긴다(부르는 곳은 빌더뿐이다). `read`는 질문이 있으면 `"cargos": []`도 돌려준다
- Consumes: `cargos`의 `token`·`kind`·`facts`, `mask_map`

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/graph/test_main.py
+++ b/tests/graph/test_main.py
@@ -118,6 +118,56 @@ def test_two_mistyped_containers_asked_once_and_both_looked_up_as_bl(agent_deps)
     assert "DEMU1234565:" in out["answer"] and "TESU0000012:" in out["answer"]
 
 
+def looked_up(monkeypatch) -> list[str]:
+    """식별·조회 서브그래프가 조회 함수(lookup_cargo)에 넘긴 번호를 모은다."""
+    from marvia.graph import identify
+
+    seen: list[str] = []
+    real = identify.lookup_cargo
+    monkeypatch.setattr(identify, "lookup_cargo", lambda number: seen.append(number) or real(number))
+    return seen
+
+
+def watching(*numbers: str):
+    """감시 목록 번호만 주는 가짜 감시."""
+    from marvia.watch import WatchDeps
+
+    return WatchDeps(
+        add=lambda *row: None,
+        news=lambda user: [],
+        ack=lambda user, ids: None,
+        numbers=lambda user: list(numbers),
+    )
+
+
+def test_after_a_container_card_a_bl_already_looked_up_this_turn_is_not_looked_up_again(
+    agent_deps, monkeypatch
+):
+    # [왜] 같은 글의 B/L은 식별이 이미 조회했다. ask 뒤 조회가 또 부르면 UNI-PASS 호출이 두 배다 (계획 6c)
+    seen = looked_up(monkeypatch)
+    graph = build_main_graph(agent_deps(watch=watching("DEMO0003")), InMemorySaver())
+    config = {"configurable": {"thread_id": "cc1", "user_id": "u1"}}
+    out = graph.invoke({"text": "DEMO0002 TESU0000013 어디야?"}, config)
+    assert [o["label"] for o in out["__interrupt__"][0].value["options"]] == [
+        "[BL1] + [BL2]",
+        "[BL1]",
+        "[BL2]",
+    ]
+    out = graph.invoke(Command(resume={"selected": 2}), config)  # [BL2] = DEMO0003
+    assert "DEMO0002: 수입신고 (부산)" in out["answer"] and "DEMO0003: 수입신고수리 (부산)" in out["answer"]
+    assert seen.count("DEMO0002") == 1
+
+
+def test_after_an_ambiguous_card_a_number_from_the_last_turn_is_looked_up_afresh(agent_deps, monkeypatch):
+    # [왜] 애매한 덩어리를 물은 차례는 조회 전에 멈춘다. 지난 차례 화물의 사실을 이번 차례 것으로 쓰지 않는다
+    seen = looked_up(monkeypatch)
+    graph = build_main_graph(agent_deps(), InMemorySaver())
+    graph.invoke({"text": "DEMO0001 어디야?"}, cfg("cc2"))
+    graph.invoke({"text": "DEMO0001 MOCK12345678TEST87654321 어디야?"}, cfg("cc2"))
+    graph.invoke(Command(resume={"selected": 0}), cfg("cc2"))
+    assert seen.count("DEMO0001") == 2  # 차례마다 한 번
+
+
 def test_no_number_guides_user(agent_deps):
     asked = Draft(
         answer="화물을 찾으려면 번호가 필요해요.",
```

- [ ] **Step 2: 실패를 본다**

```bash
uv run pytest -q tests/graph/test_main.py -k "looked_up_again or afresh"
```

Expected: `1 failed, 1 passed`. `assert 2 == 1`(조회한 번호 `['DEMO0002', 'DEMO0003', 'DEMO0002', 'DEMO0003']`). 둘째 시험은 지금도 통과하는 지킴 시험이다. Step 3 뒤 `read`의 `cleared` 줄을 `{}`로 바꾸면 `assert 1 == 2`로 실패한다 [실측 11-08].

- [ ] **Step 3: 코드**

```diff
--- a/src/marvia/graph/identify.py
+++ b/src/marvia/graph/identify.py
@@ -77,8 +77,11 @@ def read(state: IdentifyState) -> dict:
         # [주의] 애매한 덩어리의 질문이 이기면 오타 번호는 권장안(B/L 조회)을 따른다.
         #        번호가 말없이 빠지지 않게 한다
         numbers += [n.value for n in typos]
+    # [왜] 물으면 조회하지 않고 끝난다. 지난 차례 화물을 비운다. 남기면 ask 뒤 조회(reuse)가
+    #      그 사실을 이번 차례에 얻은 것으로 다시 쓴다
+    cleared = {"cargos": []} if question else {}
     # [왜] 바꾼 칸만 돌려준다. LangGraph가 공책의 그 칸들만 덮어쓰고 나머지 칸(text 등)은 그대로 둔다
-    return {"masked_text": masked, "mask_map": mask_map, "numbers": numbers, "question": question}
+    return {"masked_text": masked, "mask_map": mask_map, "numbers": numbers, "question": question, **cleared}
 
 
 def identify_number(number: str, mask_map: dict[str, str]) -> dict:
@@ -180,17 +183,6 @@ def assign(state: IdentifyState) -> dict:
     return {"mask_map": mask_map}
 
 
-def fan_out(state: IdentifyState) -> list[Send] | str:
-    """번호마다 갈래(Send) 하나를 보낸다. 컨테이너 번호는 collect가 찾는다. 보낼 것이 없으면 바로 collect."""
-    mask_map = state.get("mask_map", {})
-    sends = [
-        Send("one", {"idx": i, "number": n, "mask_map": mask_map})
-        for i, n in enumerate(state.get("numbers", []))
-        if kind_of(n) != "container"
-    ]
-    return sends or "collect"
-
-
 def one(state: LookupTask) -> dict:
     """갈래 하나: 번호 하나를 조회해 순서 번호와 함께 돌려준다. 실패도 결과다(identify_number)."""
     # [왜] 표 복사본을 넘긴다. 토큰은 assign이 넣어 두어 identify_number가 표를 바꿀 일이 없다
@@ -198,14 +190,39 @@ def one(state: LookupTask) -> dict:
     return {"found": [{"idx": state["idx"], "cargo": cargo}]}
 
 
-def build_lookup_graph(watched: Watched | None = None):
+def build_lookup_graph(watched: Watched | None = None, reuse: bool = False):
     """조회 서브그래프: 번호마다 Send로 나눠 함께 조회하고 처음 순서대로 모은다 (설계 4.3).
-    watched가 있으면 컨테이너 번호를 감시 목록의 화물에서도 찾는다 (계획 6a)."""
+    watched가 있으면 컨테이너 번호를 감시 목록의 화물에서도 찾는다 (계획 6a).
+    reuse가 참이면 공책 cargos에 이미 사실이 있는 번호는 다시 조회하지 않는다(메인 그래프의 ask 뒤 조회)."""
+
+    def reused(state: IdentifyState) -> dict[str, dict]:
+        """다시 조회하지 않을 번호 → 그 화물 결과. reuse가 거짓이면 비어 있다."""
+        if not reuse:
+            return {}
+        mask_map = state.get("mask_map", {})
+        # [왜] 도구 lookup_cargo의 have와 같은 규칙이다: 사실이 있는 화물만 다시 쓰고 실패한 조회는 다시 한다
+        return {
+            mask_map[cargo["token"]]: cargo
+            for cargo in state.get("cargos", [])
+            if cargo.get("facts") and cargo["kind"] != "container" and cargo["token"] in mask_map
+        }
+
+    def fan_out(state: IdentifyState) -> list[Send] | str:
+        """번호마다 갈래(Send) 하나를 보낸다. 컨테이너와 이미 사실이 있는 번호는 보내지 않는다."""
+        mask_map, done = state.get("mask_map", {}), reused(state)
+        sends = [
+            Send("one", {"idx": i, "number": n, "mask_map": mask_map})
+            for i, n in enumerate(state.get("numbers", []))
+            if kind_of(n) != "container" and n not in done
+        ]
+        return sends or "collect"
 
     def collect(state: LookupState, config: RunnableConfig) -> dict:
         """갈래 결과를 처음 번호 순서대로 화물 칸에 둔다. 컨테이너 번호는 아는 화물 사실에서 찾는다."""
         found = {f["idx"]: f["cargo"] for f in state.get("found", [])}
         numbers = state.get("numbers", [])
+        done = reused(state)
+        found |= {i: done[n] for i, n in enumerate(numbers) if n in done}
         containers = {i: n for i, n in enumerate(numbers) if kind_of(n) == "container"}
         if containers:
             # [왜] 갈래 조회가 끝난 뒤에 찾는다. 같은 글에 함께 적은 B/L의 사실도 쓸 수 있다.
--- a/src/marvia/graph/main.py
+++ b/src/marvia/graph/main.py
@@ -474,7 +474,9 @@ def build_main_graph(
     graph.add_node("identify", build_identify_graph(watched(deps.watch)))
     graph.add_node("ask", ask)
     # 식별 서브그래프와 같은 조회 서브그래프를 다시 쓴다
-    graph.add_node("lookup", build_lookup_graph(watched(deps.watch)))
+    # [왜] reuse: ask 앞의 cargos는 이번 차례 식별이 조회한 결과다(물으면 read가 비운다). 그 번호는 다시
+    #      조회하지 않는다 (같은 글의 B/L을 컨테이너 선택지 뒤에 또 조회하지 않게)
+    graph.add_node("lookup", build_lookup_graph(watched(deps.watch), reuse=True))
     graph.add_node("write", write)
     graph.add_node("verify", check)
     graph.add_node("respond", shown(respond))
```

- [ ] **Step 4: 확인**: 명령 A. Expected: `822 passed`, 오류 0 [실측 11-08].

- [ ] **Step 5: 커밋**

```bash
git add src/marvia/graph/identify.py src/marvia/graph/main.py tests/graph/test_main.py
git commit -m "fix(graph): 컨테이너 선택지 뒤 이번 차례에 이미 조회한 B/L을 다시 조회하지 않음"
```

### Task 4: 조회할 번호의 중복을 한 곳에서 뺀다 (항목 G, C4)

**배울 것:** 번호 목록은 세 곳에서 만들어진다(글 읽기, 선택지 답, 도구 인자). 셋 다 조회 서브그래프의 첫 노드 `assign`을 지나므로 거기서 한 번 빼면 된다. `dict.fromkeys`는 처음 나온 순서를 지킨다. 조회 서브그래프의 출력 모양이 식별 공책이라 뺀 목록이 부모의 `numbers`로 돌아간다.

#### 커밋 4: fix(graph): 조회할 번호의 중복을 한 곳(assign)에서 뺌

**Files:**
- Modify: `src/marvia/graph/identify.py`
- Test: `tests/graph/test_main.py`

**Interfaces:**
- Produces: `assign`이 `{"mask_map", "numbers"}`를 돌려준다(`numbers`는 중복 없이 처음 순서)

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/graph/test_main.py
+++ b/tests/graph/test_main.py
@@ -168,6 +168,24 @@ def test_after_an_ambiguous_card_a_number_from_the_last_turn_is_looked_up_afresh
     assert seen.count("DEMO0001") == 2  # 차례마다 한 번
 
 
+def test_a_number_typed_twice_is_looked_up_and_shown_once(agent_deps, monkeypatch):
+    seen = looked_up(monkeypatch)
+    graph = build_main_graph(agent_deps(), InMemorySaver())
+    out = graph.invoke({"text": "DEMO0001 그리고 DEMO0001 어디야?"}, cfg("dd1"))
+    assert out["answer"].count("DEMO0001: 반입신고 (부산)") == 1 and "건으로 읽었어요" not in out["answer"]
+    assert seen == ["DEMO0001"]
+
+
+def test_choosing_all_cargo_on_a_container_with_its_bl_in_the_message_reads_each_cargo_once(agent_deps):
+    # [왜] 같은 글의 B/L이 컨테이너 후보이기도 하다. "모두"를 고르면 그 B/L이 두 번 든다
+    graph = build_main_graph(agent_deps(watch=watching("DEMO0003")), InMemorySaver())
+    config = {"configurable": {"thread_id": "dd2", "user_id": "u1"}}
+    graph.invoke({"text": "DEMO0002 TESU0000013 어디야?"}, config)
+    out = graph.invoke(Command(resume={"selected": 0}), config)  # [BL1] + [BL2] 모두
+    assert "2건으로 읽었어요." in out["answer"]
+    assert out["answer"].count("DEMO0002: 수입신고 (부산)") == 1
+
+
 def test_no_number_guides_user(agent_deps):
     asked = Draft(
         answer="화물을 찾으려면 번호가 필요해요.",
```

- [ ] **Step 2: 실패를 본다**

```bash
uv run pytest -q tests/graph/test_main.py -k "typed_twice or reads_each_cargo_once"
```

Expected: `2 failed`. 첫째는 `assert (2 == 1)`(답에 `'2건으로 읽었어요.\nDEMO0001: 반입신고 (부산) 2026-10-27\nDEMO0001: 반입신고 (부산) 2026-10-27…'`), 둘째는 `assert '2건으로 읽었어요.' in '3건으로 읽었어요.\nDEMO0002: …\nDEMO0002: …\nDEMO0003: …'` [실측 11-08].

- [ ] **Step 3: 코드**

```diff
--- a/src/marvia/graph/identify.py
+++ b/src/marvia/graph/identify.py
@@ -174,13 +174,15 @@ class LookupTask(TypedDict):
 
 
 def assign(state: IdentifyState) -> dict:
-    """조회할 번호마다 토큰을 먼저 정한다."""
+    """조회할 번호의 중복을 빼고, 번호마다 토큰을 먼저 정한다."""
+    # [왜] 같은 번호를 두 번 적거나 고른 후보가 같은 글의 B/L이면 번호가 겹친다. 처음 순서대로 한 번만 둔다
+    numbers = list(dict.fromkeys(state.get("numbers", [])))
     # [왜] 갈래마다 토큰을 만들면 같은 이름표([BL2])가 두 번호에 붙을 수 있다. 나누기 전에 한 곳에서 정한다
     # [왜] 공책의 dict를 직접 고치지 않고 복사해서 고친다. 노드는 바꾼 값을 돌려주는 방식으로만 공책을 바꾼다
     mask_map = dict(state.get("mask_map", {}))
-    for number in state.get("numbers", []):
+    for number in numbers:
         token_for(mask_map, number, kind_of(number))
-    return {"mask_map": mask_map}
+    return {"mask_map": mask_map, "numbers": numbers}
 
 
 def one(state: LookupTask) -> dict:
```

- [ ] **Step 4: 확인**: 명령 A. Expected: `824 passed`, 오류 0 [실측 11-08].

- [ ] **Step 5: 커밋**

```bash
git add src/marvia/graph/identify.py tests/graph/test_main.py
git commit -m "fix(graph): 조회할 번호의 중복을 한 곳(assign)에서 뺌"
```

### Task 5: 역슬래시나 공백이 든 Langfuse 주소를 거절한다 (항목 J, C5)

**배울 것:** 같은 주소 글도 읽는 라이브러리마다 호스트를 다르게 읽을 수 있다. `urllib.parse.urlsplit`은 `http://evil.test\@localhost`의 `@` 앞을 사용자 칸으로 보아 호스트를 localhost로 읽지만, urllib3·requests는 역슬래시를 경로 시작으로 보아 evil.test로 보낸다. 검사는 `urlsplit`으로 하는데 HTTP 라이브러리는 같은 글을 다르게 읽을 수 있으므로, 읽는 쪽마다 다르게 읽는 글자(역슬래시, 공백·탭)를 먼저 거절한다.

#### 커밋 5: fix(trace): Langfuse 주소에 역슬래시나 공백이 있으면 거절

**Files:**
- Modify: `src/marvia/trace.py`
- Test: `tests/graph/test_trace.py`

**Interfaces:**
- Produces: `_safe_host(host)`가 역슬래시·공백 글자가 있으면 `False`. 거절 글 "MARVIA_LANGFUSE_HOST는 역슬래시·공백 없는 https:// 주소여야 합니다(localhost·127.0.0.1·[::1]만 http 허용)"

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/graph/test_trace.py
+++ b/tests/graph/test_trace.py
@@ -414,7 +414,16 @@ def test_https_or_loopback_http_host_is_accepted(monkeypatch, host):
 
 
 @pytest.mark.parametrize(
-    "host", ["http://langfuse.example.com", "http://localhost.evil.test", "ftp://x.test"]
+    "host",
+    [
+        "http://langfuse.example.com",
+        "http://localhost.evil.test",
+        "ftp://x.test",
+        # [왜] urlsplit은 역슬래시 앞을 사용자 칸으로 읽어 localhost를 보지만 urllib3은 evil.test로 보낸다
+        "http://evil.test\\@localhost",
+        "https://x.test\\@localhost",
+        "http://evil.test\t@localhost",  # [왜] 탭은 urlsplit이 지우고 requests는 %09로 남겨 읽는 값이 갈린다
+    ],
 )
 def test_a_remote_plain_http_host_is_refused_without_naming_the_keys(monkeypatch, host):
     monkeypatch.setattr(langfuse_trace, "build", lambda *keys: pytest.fail("building must not start"))
```

- [ ] **Step 2: 실패를 본다**

```bash
uv run pytest -q tests/graph/test_trace.py -k refused
```

Expected: `3 failed, 3 passed`. 새 셋이 `Failed: building must not start` [실측 11-08].

- [ ] **Step 3: 코드**

```diff
--- a/src/marvia/trace.py
+++ b/src/marvia/trace.py
@@ -98,7 +98,11 @@ def _walk(value: Any, active: set[int]) -> Any:
 
 
 def _safe_host(host: str) -> bool:
-    """https이거나, 포트가 있어도 loopback(localhost·127.0.0.1·[::1])의 http이면 참."""
+    """https이거나, 포트가 있어도 loopback(localhost·127.0.0.1·[::1])의 http이면 참. 역슬래시·공백은 거짓."""
+    # [왜] urlsplit은 http://evil.test\@localhost를 localhost로 읽지만 urllib3·requests는 evil.test로 보낸다.
+    #      주소를 읽는 쪽마다 달리 읽는 글자는 받지 않는다
+    if "\\" in host or any(ch.isspace() for ch in host):
+        return False
     url = urlsplit(host)
     return url.scheme == "https" or (
         url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1")
@@ -129,6 +133,7 @@ def tracer_callbacks(settings: Settings) -> list:
     # [주의] 메시지에 키나 주소 값을 넣지 않는다
     if all(keys) and not _safe_host(keys[2]):
         raise ValueError(
-            "MARVIA_LANGFUSE_HOST는 https:// 주소여야 합니다(localhost·127.0.0.1·[::1]만 http 허용)"
+            "MARVIA_LANGFUSE_HOST는 역슬래시·공백 없는 https:// 주소여야 합니다"
+            "(localhost·127.0.0.1·[::1]만 http 허용)"
         )
     return [_handler(*keys)] if all(keys) else []
```

- [ ] **Step 4: 확인**: 명령 A. Expected: `827 passed`, 오류 0 [실측 11-08].

- [ ] **Step 5: 커밋**

```bash
git add src/marvia/trace.py tests/graph/test_trace.py
git commit -m "fix(trace): Langfuse 주소에 역슬래시나 공백이 있으면 거절"
```

장부에 확인점 줄을 남긴다: `CP1 (11-08 18:00): T1~T5 done? <yes/no, cut applied>`.

### Task 6: 로컬 화면 서버는 127.0.0.1에서만 듣고, 시험 이미지는 pwuser로 돈다 (항목 D, C6)

**배울 것:** `next dev`·`next start`는 `-H`가 없으면 모든 주소에서 듣는다. 같은 망의 다른 기기가 개발 화면에 붙을 수 있다. 운영 이미지(`web/Dockerfile`)는 `node server.js`와 `HOSTNAME=0.0.0.0`으로 돌아 이 스크립트를 쓰지 않는다. 공식 Playwright 이미지에는 `pwuser` 사용자가 있다. Playwright는 시작할 때 작업 폴더에 `test-results`를 만들므로 root가 만든 `/work`의 주인만 넘긴다. 스크린샷은 compose가 붙이는 폴더에 쓴다.

#### 커밋 6: fix(web): 로컬 화면 서버는 127.0.0.1에서만 듣고 e2e 이미지는 pwuser로 돎

**Files:**
- Modify: `web/package.json`, `web/e2e.Dockerfile` (잠금 파일은 바뀌지 않는다)
- Test: `tests/test_docker.py`

**Interfaces:**
- Produces: `npm run dev`·`npm start`가 `127.0.0.1:3000`에서 듣는다. 시험 이미지 실행 사용자 `pwuser`

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/test_docker.py
+++ b/tests/test_docker.py
@@ -132,3 +132,16 @@ def test_prepare_db_twice_makes_the_tables_the_server_needs_and_the_second_run_c
     assert all(count[0] > 0 for count in first[1])
     prepare_db.main()
     assert snapshot() == first
+
+
+def test_local_web_servers_listen_on_loopback_and_the_e2e_image_does_not_run_as_root():
+    # [왜] next dev·start는 -H가 없으면 모든 주소에서 듣는다. 같은 망의 다른 기기가 개발 화면에 붙는다
+    scripts = json.loads((ROOT / "web" / "package.json").read_text())["scripts"]
+    assert "-H 127.0.0.1" in scripts["dev"] and "-H 127.0.0.1" in scripts["start"]
+    # [왜] 시험 이미지도 root로 돌지 않는다. 공식 이미지에 있는 pwuser로 돈다
+    users = [
+        line.split()[1]
+        for line in (ROOT / "web" / "e2e.Dockerfile").read_text().splitlines()
+        if line.startswith("USER ")
+    ]
+    assert users[-1:] == ["pwuser"], users
```

- [ ] **Step 2: 실패를 본다**

```bash
uv run pytest -q tests/test_docker.py -k loopback
```

Expected: `1 failed`. `assert ('-H 127.0.0.1' in 'next dev --port 3000')` [실측 11-08].

- [ ] **Step 3: 코드**

```diff
--- a/web/e2e.Dockerfile
+++ b/web/e2e.Dockerfile
@@ -9,4 +9,7 @@ RUN test "$(node -p "require('playwright-core/package.json').version")" = "1.64.
 COPY playwright.config.ts ./
 COPY e2e ./e2e
 ENV NEXT_TELEMETRY_DISABLED=1
+# [왜] root로 돌지 않는다. 공식 이미지의 pwuser로 돌고, 시험 결과(test-results)를 쓸 작업 폴더만 그에게 준다
+RUN chown pwuser /work
+USER pwuser
 CMD ["npx", "playwright", "test"]
--- a/web/package.json
+++ b/web/package.json
@@ -3,9 +3,9 @@
   "version": "2.0.0",
   "private": true,
   "scripts": {
-    "dev": "next dev --port 3000",
+    "dev": "next dev -H 127.0.0.1 --port 3000",
     "build": "next build",
-    "start": "next start --port 3000",
+    "start": "next start -H 127.0.0.1 --port 3000",
     "typecheck": "tsc --noEmit",
     "e2e": "playwright test"
   },
```

- [ ] **Step 4: 확인**: 명령 A. Expected: `828 passed`, 오류 0. 명령 B. Expected: `web-ok`. 명령 C. Expected: 첫 줄 `pwuser`, `5 passed`, 스크린샷 셋 [실측 11-08]. (`RUN chown pwuser /work`를 빼면 명령 C가 `Error: EACCES: permission denied, mkdir '/work/test-results'`로 끝난다 [실측 11-08].)

- [ ] **Step 5: 커밋**

```bash
git add web/package.json web/e2e.Dockerfile tests/test_docker.py
git commit -m "fix(web): 로컬 화면 서버는 127.0.0.1에서만 듣고 e2e 이미지는 pwuser로 돎"
```

### Task 7: ② 겹이 SDK의 JSON 값을 읽어서 가리고, ISO 시각은 그대로 둔다 (항목 I, C7)

**배울 것:** Langfuse SDK는 span 속성 일부를 JSON 글로 적는다(trace metadata 값은 모두 `json.dumps`, 스트리밍 첫 글자 시각 `completion_start_time`도 JSON 글). ② 겹은 지금 그 글을 그냥 글로 보고 번호 덩어리를 찾는다. 그러면 `"gate\nDEMO0011"`의 `\n` 뒤 `nDEMO0011`이 한 덩어리가 되어 `\[가림]`이 남고 JSON이 깨진다. 읽어서(`json.loads`) 글마다 가리고 다시 적으면 이스케이프를 건드리지 않는다. 숫자만인 번호(12자리 B/L)는 JSON에서 수로 읽혀 글 가림을 지나므로, `parse_int`·`parse_float`로 읽기 전 글자를 보고 가린다.

#### 커밋 7: fix(trace): ②가 SDK의 JSON 값을 읽어서 가리고 ISO 시각은 그대로 둠

**Files:**
- Modify: `src/marvia/langfuse_trace.py`
- Test: `tests/graph/test_trace.py`

**Interfaces:**
- Produces: `langfuse_trace.ISO_TIME`, `_number(literal)`, `_clean_json(value)`, `_clean_text(text)`. `_clean`과 `scrub_spans`의 모양은 그대로

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/graph/test_trace.py
+++ b/tests/graph/test_trace.py
@@ -348,6 +348,19 @@ def test_removing_any_one_layer_leaves_its_numbers(agent_deps, monkeypatch, laye
     assert [number for number in left if number not in dump] == []
 
 
+def test_layer_two_reads_sdk_json_values_so_they_stay_json_and_times_stay_times():
+    # [왜] SDK는 trace metadata 값과 시각을 JSON 글로 적는다. 글 그대로 가리면 \n 뒤 덩어리가 \[가림]이 되어
+    #      JSON이 깨지고, 시각은 [가림]:34:56이 된다 (계획 6c). 읽어서 가리되 번호는 남기지 않는다
+    clean = langfuse_trace._clean
+    assert json.loads(clean(json.dumps("gate\nDEMO0011", ensure_ascii=False))) == f"gate\n{MASK}"
+    when = json.dumps("2026-11-08T12:34:56.123456+00:00")
+    assert clean(when) == when
+    numbers = json.dumps({"bl": 123456789012, "n": 3, "said": "DEMO0012 어디야"})
+    assert json.loads(clean(numbers)) == {"bl": MASK, "n": 3, "said": f"{MASK} 어디야"}
+    assert clean("DEMO0013 조회 실패") == f"{MASK} 조회 실패"  # JSON이 아닌 글은 전처럼 가린다
+    assert clean("123456789012") == json.dumps(MASK, ensure_ascii=False)
+
+
 def test_media_upload_is_off(monkeypatch):
     # [왜] data URI 사진은 ①이 가리기 전에 SDK가 미디어로 올린다. 끄는 길은 환경 변수 하나뿐이다
     exporter, key, handler = tracer()
```

- [ ] **Step 2: 실패를 본다**

```bash
uv run pytest -q tests/graph/test_trace.py -k layer_two
```

Expected: `1 failed`. `json.decoder.JSONDecodeError: Invalid \escape: line 1 column 6 (char 5)` [실측 11-08].

- [ ] **Step 3: 코드**

```diff
--- a/src/marvia/langfuse_trace.py
+++ b/src/marvia/langfuse_trace.py
@@ -14,7 +14,9 @@
 
 from __future__ import annotations
 
+import json
 import os
+import re
 from typing import Any
 
 from langchain_core.messages import ToolMessage
@@ -25,12 +27,12 @@ from langfuse.types import MaskOtelSpansParams, MaskOtelSpansResult, OtelSpanPat
 from langgraph.errors import GraphBubbleUp
 from opentelemetry.sdk.trace.export import SpanExporter
 
-from marvia.trace import scrub, scrub_text
+from marvia.trace import MASK, scrub, scrub_text
 
 # [왜] ①이 JSON으로 바꾸기 전에 가린 칸이다. ②가 JSON 글을 다시 가리면 \u 이스케이프가 깨진다
 #      (11-07 실측: "제241조"를 적은 \uc81c241이 번호 후보로 가려져 JSON을 읽을 수 없게 된다)
 #      trace.metadata는 여기 없다: SDK가 propagate_attributes로 적어 ①을 거치지 않고, thread_id처럼
-#      사용자가 정한 글이 든다. ②가 가려도 JSON이 유효함을 11-08에 쟀다
+#      사용자가 정한 글이 든다. ②는 JSON 값을 읽어서 가리고 다시 적는다(_clean)
 PAYLOAD = (
     "langfuse.observation.input",
     "langfuse.observation.output",
@@ -38,12 +40,47 @@ PAYLOAD = (
 )
 
 
+# [왜] SDK가 JSON으로 적는 시각(completion_start_time)은 그대로 둔다. 번호 덩어리 규칙은 날짜와 시를
+#      한 덩어리로 가려 시각이 아니게 만든다. 이 꼴에는 숫자와 정한 기호뿐이라 번호가 들 수 없다
+ISO_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?", re.ASCII)
+
+
+def _number(literal: str) -> Any:
+    """JSON 수 글자 하나를 읽는다. 번호처럼 생긴 수(12자리 B/L 등)는 MASK 글로 바꾼다."""
+    # [왜] 읽기 전 글자로 본다. 읽은 뒤의 수는 글자 모양이 바뀔 수 있다(0.0000000123 → 1.23e-08)
+    return MASK if scrub_text(literal) != literal else json.loads(literal)
+
+
+def _clean_json(value: Any) -> Any:
+    """JSON에서 읽은 값의 글을 가린다. ISO 시각 글은 그대로 둔다(수는 _number가 읽을 때 가렸다)."""
+    if isinstance(value, str):
+        return value if ISO_TIME.fullmatch(value) else scrub_text(value)
+    if isinstance(value, list):
+        return [_clean_json(item) for item in value]
+    if isinstance(value, dict):
+        # [주의] 가린 뒤 겹치는 키는 뒤 값만 남는다(트레이스 값을 잃을 뿐 번호는 나가지 않는다)
+        return {scrub_text(key): _clean_json(item) for key, item in value.items()}
+    return value
+
+
+def _clean_text(text: str) -> str:
+    """글 하나를 가린다. SDK가 JSON으로 적은 값(trace metadata, 시각)은 읽어서 가린 뒤 다시 적는다."""
+    # [왜] JSON 글을 그대로 가리면 \n 같은 이스케이프 뒤 덩어리가 \[가림]이 되어 JSON이 깨진다 (계획 6c)
+    try:
+        value = json.loads(text)
+    except ValueError:
+        return scrub_text(text)  # JSON이 아닌 글(status_message 등)
+    cleaned = _clean_json(json.loads(text, parse_int=_number, parse_float=_number))
+    # [왜] 가릴 것이 없으면 SDK가 적은 글을 그대로 둔다(띄어쓰기 모양도 바꾸지 않는다)
+    return text if cleaned == value else json.dumps(cleaned, ensure_ascii=False)
+
+
 def _clean(value: Any) -> Any:
     """속성 값 하나를 가린다. 글 목록(OTel은 tuple로 둔다)은 글만 가린다."""
     if isinstance(value, str):
-        return scrub_text(value)
+        return _clean_text(value)
     if isinstance(value, (list, tuple)):
-        return tuple(scrub_text(item) if isinstance(item, str) else item for item in value)
+        return tuple(_clean_text(item) if isinstance(item, str) else item for item in value)
     return value
 
 
```

- [ ] **Step 4: 확인**: 명령 A. Expected: `829 passed`, 오류 0. 6b 문 시험(`test_every_exported_span_field_is_free_of_numbers`, 겹 빼기 넷)이 그 안에서 통과한다 [실측 11-08].

- [ ] **Step 5: 커밋**

```bash
git add src/marvia/langfuse_trace.py tests/graph/test_trace.py
git commit -m "fix(trace): ②가 SDK의 JSON 값을 읽어서 가리고 ISO 시각은 그대로 둠"
```

### Task 8: 계정 삭제 화면 다듬기 (항목 E, C8)

**배울 것:** 확인 단추를 누르면 그 단추가 사라지고 초점이 문서 처음으로 간다. 키보드·화면 낭독 사용자는 무엇을 묻는지 모른다. 선택지·승인 카드처럼 새로 뜬 묶음에 `tabIndex=-1`을 주고 초점을 옮긴다. 지운 뒤에는 로그아웃만 하면 화면 상태(대화 줄, 패널, 카드)가 메모리에 남아 다시 들어오면 지운 계정의 대화가 보인다. 401은 차례 보내기와 같게 로그아웃한다. 삭제의 409도 T2처럼 서버 글을 보인다.

#### 커밋 8: fix(web): 계정 삭제 확인에 초점, 401이면 로그아웃, 지운 뒤 대화 비움, 409는 서버 글

**Files:**
- Modify: `web/app/page.tsx`, `web/lib/agui.ts`, `src/marvia/server.py`(삭제 거절 글 하나)
- Test: `web/e2e/flows.spec.ts`

**Interfaces:**
- Produces: `deleteAccount`가 409 본문을 `HttpError`에 담는다. `DELETE /account`의 답하는 중 409 글 "답하는 중인 대화가 있어요. 끝난 뒤 다시 눌러 주세요"

- [ ] **Step 1: 실패하는 흐름**

```diff
--- a/web/e2e/flows.spec.ts
+++ b/web/e2e/flows.spec.ts
@@ -103,3 +103,29 @@ test("409에는 서버가 보낸 까닭을 보이고, 지난 카드일 때만 
   await expect(told).toHaveText("답할 질문이 없거나 이미 지난 카드예요");
   await expect(card).toBeHidden();
 });
+
+test("계정 삭제는 확인에 초점을 옮기고, 지운 뒤 다시 들어오면 대화가 비어 있다", async ({ page }) => {
+  await ask(page, "앞으로 자세히 설명해 줘");
+  await expect(page.getByRole("heading", { name: "승인이 필요해요" })).toBeVisible();
+  await page.getByRole("button", { name: "계정 삭제" }).click();
+  await expect(page.getByRole("group", { name: "계정 삭제 확인" })).toBeFocused();
+  await accessible(page);
+  await page.getByRole("button", { name: "지우기" }).click();
+  await expect(page.locator('p[role="alert"]')).toHaveText("계정을 지웠어요. 대화 기록과 저장한 값이 모두 지워졌어요");
+  await page.getByLabel("개발 로그인 토큰").fill(TOKEN);
+  await page.getByRole("button", { name: "들어가기" }).click();
+  await expect(page.getByRole("heading", { name: "대화" })).toBeVisible();
+  await expect(page.locator(".chat li")).toHaveCount(0); // 지운 계정의 대화가 남지 않는다
+  await expect(page.locator(".card")).toHaveCount(0);
+});
+
+test("계정 삭제가 401이면 로그아웃한다", async ({ page }) => {
+  // [왜] 토큰이 만료되면 서버가 401을 준다. 가짜 API의 개발 토큰은 만료되지 않아 응답을 흉내 낸다
+  await page.route("**/account", (route) =>
+    route.fulfill({ status: 401, headers: { "access-control-allow-origin": new URL(page.url()).origin } }),
+  );
+  await page.getByRole("button", { name: "계정 삭제" }).click();
+  await page.getByRole("button", { name: "지우기" }).click();
+  await expect(page.getByLabel("개발 로그인 토큰")).toBeVisible();
+  await expect(page.locator('p[role="alert"]')).toHaveText("다시 로그인해 주세요");
+});
```

- [ ] **Step 2: 실패를 본다**: 명령 C. Expected: `2 failed`, `5 passed`. 계정 삭제 흐름이 `toBeFocused() failed`(`Received: inactive`), 401 흐름이 `toBeVisible() failed`(`element(s) not found`)로 실패한다 [실측 11-08]. 초점 줄을 뺀 사본에서는 계정 삭제 흐름이 `toHaveCount(0)`에서 `Received: 1`(지운 계정의 대화 줄)로 실패한다 [실측 11-08].

- [ ] **Step 3: 코드**

```diff
--- a/src/marvia/server.py
+++ b/src/marvia/server.py
@@ -326,7 +326,9 @@ def build_app(
             if user in deleting:
                 return JSONResponse({"error": "계정을 지우는 중이에요"}, status_code=409)
             if any(key.startswith(f"{user}/") for key in running):
-                return JSONResponse({"error": "답하는 중인 대화가 있어요"}, status_code=409)
+                return JSONResponse(
+                    {"error": "답하는 중인 대화가 있어요. 끝난 뒤 다시 눌러 주세요"}, status_code=409
+                )
             deleting.add(user)
         try:
             await anyio.to_thread.run_sync(forget, user)
--- a/web/app/page.tsx
+++ b/web/app/page.tsx
@@ -27,6 +27,12 @@ export default function Home() {
 
   const running = useRef<AbortController | null>(null);
   const sending = useRef(false); // [왜] busy는 상태라 빠른 두 번 입력 사이에 아직 안 바뀐다
+  const confirmBox = useRef<HTMLDivElement>(null);
+
+  // 계정 삭제 확인이 뜨면 초점을 옮긴다. 누른 버튼이 사라져 초점이 문서 처음으로 가지 않게 한다
+  useEffect(() => {
+    if (confirmingDelete) confirmBox.current?.focus();
+  }, [confirmingDelete]);
 
   // 화면을 떠나면 진행 중인 차례를 멈춘다
   useEffect(() => () => running.current?.abort(), []);
@@ -110,16 +116,17 @@ export default function Home() {
       await deleteAccount(API_URL, fresh);
       running.current?.abort();
       await signOut();
+      // [왜] 지운 계정의 대화·카드·패널이 다음 로그인 화면에 남지 않게 화면 상태도 비운다
+      setLines([]);
+      setView(EMPTY_VIEW);
+      setCard(null);
       setToken(null);
       setError("계정을 지웠어요. 대화 기록과 저장한 값이 모두 지워졌어요");
     } catch (failure) {
-      setError(
-        failure instanceof HttpError && failure.status === 409
-          ? "답하는 중인 대화가 있어요. 끝난 뒤 다시 눌러 주세요"
-          : failure instanceof HttpError
-            ? failure.message
-            : "서버에 닿지 못했어요. 잠시 뒤 다시 해 주세요",
-      );
+      // [왜] 409(답하는 중, 지우는 중)는 서버가 정한 글을 그대로 보인다
+      setError(failure instanceof HttpError ? failure.message : "서버에 닿지 못했어요. 잠시 뒤 다시 해 주세요");
+      // [왜] 차례 보내기와 같다. 토큰이 만료됐거나 틀리면 로그인 화면으로 간다
+      if (failure instanceof HttpError && failure.status === 401) signOut().then(() => setToken(null));
     }
   }
 
@@ -194,7 +201,7 @@ export default function Home() {
       <section aria-labelledby="account-title" className="panel">
         <h2 id="account-title">계정</h2>
         {confirmingDelete ? (
-          <div role="group" aria-label="계정 삭제 확인">
+          <div ref={confirmBox} tabIndex={-1} role="group" aria-label="계정 삭제 확인">
             <p>계정을 지우면 대화 기록, 저장한 값, 감시 목록이 모두 지워지고 되돌릴 수 없어요. 지울까요?</p>
             <div className="row">
               <button type="button" onClick={removeAccount}>
--- a/web/lib/agui.ts
+++ b/web/lib/agui.ts
@@ -165,8 +165,10 @@ export function parseBlock(block: string): AgUiEvent[] {
   return events;
 }
 
-// 계정 삭제. 204면 지워진 것이고, 그 밖의 거절은 상태 코드를 담아 던진다 (답하는 중이면 409)
+// 계정 삭제. 204면 지워진 것이고, 그 밖의 거절은 상태 코드를 담아 던진다 (답하는 중·지우는 중이면 409)
 export async function deleteAccount(apiUrl: string, token: string): Promise<void> {
   const response = await fetch(`${apiUrl}/account`, { method: "DELETE", headers: { authorization: `Bearer ${token}` } });
-  if (response.status !== 204) throw new HttpError(response.status);
+  if (response.status === 204) return;
+  const reason = response.status === 409 ? await response.json().catch(() => ({})) : {};
+  throw new HttpError(response.status, reason);
 }
```

- [ ] **Step 4: 확인**: 명령 A. Expected: `829 passed`(파이썬 시험 수 그대로), 오류 0. 명령 B. Expected: `web-ok`. 명령 C. Expected: 첫 줄 `pwuser`, `7 passed`, 스크린샷 셋 [실측 11-08].

- [ ] **Step 5: 커밋**

```bash
git add web/app/page.tsx web/lib/agui.ts src/marvia/server.py web/e2e/flows.spec.ts
git commit -m "fix(web): 계정 삭제 확인에 초점, 401이면 로그아웃, 지운 뒤 대화 비움, 409는 서버 글"
```

장부에 확인점 줄을 남긴다: `CP2 (11-09 09:00): T6~T8 done? <yes/no, cut applied>`.

### Task 9: 대화 id 길이 상한을 규칙 파일로 옮긴다 (항목 C, C9)

**배울 것:** 상한 같은 값은 코드가 아니라 `rules/*.yaml`에 둔다(저장소 규칙). 정규식은 글자 모양만 보고 길이는 규칙 값으로 따로 본다.

#### 커밋 9: fix(server): 대화 id 길이 상한을 rules/server.yaml로 옮김

**Files:**
- Modify: `rules/server.yaml`, `src/marvia/server.py`
- Test: `tests/graph/test_server.py`

**Interfaces:**
- Produces: `load_rules("server")["request"]["max_thread_id"] == 64`

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/graph/test_server.py
+++ b/tests/graph/test_server.py
@@ -186,6 +186,17 @@ def test_bad_requests_are_refused_before_the_graph_runs(agent_deps, payload, sta
     assert response.status_code == status
 
 
+def test_the_thread_id_length_limit_comes_from_the_rules():
+    # [왜] 상한은 rules/server.yaml에 둔다 (계획 6c). 정규식에 숫자로 적지 않는다
+    from marvia.tools.rules import load_rules
+
+    limit = load_rules("server")["request"]["max_thread_id"]
+    client = TestClient(build_app(Stub(), verify, web_origin="http://x.test", forget=print))
+    head = {"Authorization": "Bearer tok-a"}
+    assert client.post("/agui", json=body("a" * (limit + 1), "질문"), headers=head).status_code == 422
+    assert client.post("/agui", json=body("a" * limit, "질문"), headers=head).status_code == 200
+
+
 def test_a_second_run_on_a_busy_thread_is_409(agent_deps, fake_rag):
     entered, gate = threading.Event(), threading.Event()
     rag = fake_rag()
```

- [ ] **Step 2: 실패를 본다**

```bash
uv run pytest -q tests/graph/test_server.py -k length_limit
```

Expected: `1 failed`. `KeyError: 'max_thread_id'` [실측 11-08].

- [ ] **Step 3: 코드**

```diff
--- a/rules/server.yaml
+++ b/rules/server.yaml
@@ -14,6 +14,7 @@ auth:
 
 request:
   max_text: 2000 # 사용자 글 한 번의 글자 수 상한. 넘으면 422
+  max_thread_id: 64 # 화면이 정하는 대화 id(영문·숫자·_·-)의 글자 수 상한. 넘으면 422
   max_body_bytes: 65536 # 요청 본문 바이트 상한. 넘으면 413
 
 question:
--- a/src/marvia/server.py
+++ b/src/marvia/server.py
@@ -71,8 +71,8 @@ LOG = logging.getLogger(__name__)
 ERROR_TEXT = "이번 차례를 끝내지 못했어요. 다시 물어봐 주세요."
 
 # [왜] 화면이 정하는 thread id는 이름 공간 안의 이름일 뿐이다.
-#      서버가 "사용자/이름"으로 묶어 남의 대화에 닿지 못한다
-THREAD_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
+#      서버가 "사용자/이름"으로 묶어 남의 대화에 닿지 못한다. 길이 상한은 rules/server.yaml(max_thread_id)
+THREAD_ID = re.compile(r"[A-Za-z0-9_-]+")
 # [왜] 프록시·압축이 이벤트를 모았다가 한꺼번에 보내면 "진행 중인 할 일"이 답과 함께 뜬다
 SSE_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}
 LIVE_KEYS = ("todos", "plan", "cargos", "evidence", "mask_map")  # 화면 보기를 바꾸는 공책 칸
@@ -291,7 +291,7 @@ def build_app(
             return JSONResponse({"error": str(error)}, status_code=error.status)
         except ValidationError:
             return JSONResponse({"error": "요청 모양이 틀렸어요"}, status_code=422)
-        if not THREAD_ID.fullmatch(body.thread_id):
+        if not THREAD_ID.fullmatch(body.thread_id) or len(body.thread_id) > cfg["max_thread_id"]:
             return JSONResponse({"error": "대화 id 모양이 틀렸어요"}, status_code=422)
         key = f"{user}/{body.thread_id}"
         with guard:
```

- [ ] **Step 4: 확인**: 명령 A. Expected: `830 passed`, 오류 0 [실측 11-08].

- [ ] **Step 5: 커밋**

```bash
git add rules/server.yaml src/marvia/server.py tests/graph/test_server.py
git commit -m "fix(server): 대화 id 길이 상한을 rules/server.yaml로 옮김"
```

### Task 10: 식별 질문·선택지 글을 규칙 파일로 옮긴다 (항목 H, C10)

**배울 것:** 화면에 보이는 정한 글은 규칙 파일에 두고 코드는 `{…}` 칸만 채운다(`str.format`). 채우는 값(가린 토큰, 건수, 애매한 덩어리 원문)은 인자로 들어가므로 글 틀 안의 중괄호로 해석되지 않는다. YAML에서 `{`로 시작하는 값은 묶음(mapping)으로 읽히므로 따옴표로 감싼다.

#### 커밋 10: refactor(graph): 식별 질문·선택지 글을 rules/identify.yaml로 옮김

**Files:**
- Create: `rules/identify.yaml`
- Modify: `src/marvia/graph/identify.py`
- Test: `tests/graph/test_identify.py`

**Interfaces:**
- Produces: `load_rules("identify")["questions"]`의 `ambiguous`(question, option), `typo`(question, as_bl, skip_label, skip), `container`(question, all, one)

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/graph/test_identify.py
+++ b/tests/graph/test_identify.py
@@ -1,6 +1,7 @@
 from langchain_core.runnables import RunnableConfig
 
 from marvia.graph.identify import build_identify_graph
+from marvia.tools.rules import load_rules
 
 
 def run(text: str) -> dict:
@@ -232,3 +233,26 @@ def test_a_spaced_container_with_a_wrong_check_digit_is_asked_before_any_lookup(
     assert "DEMU" not in shown and "123456" not in shown
     assert out["masked_text"] == "[BL1] 어디야?" and out["numbers"] == []
     assert seen == []
+
+
+def test_question_and_choice_texts_come_from_the_rules():
+    # [왜] 화면에 보이는 정한 글은 rules/identify.yaml에 둔다 (계획 6c). 글을 바꿀 때 이 파일만 고친다
+    texts = load_rules("identify")["questions"]
+    ambiguous = run("MOCK12345678TEST87654321")["question"]
+    assert ambiguous["question"] == texts["ambiguous"]["question"].format(raw="MOCK12345678TEST87654321")
+    assert ambiguous["options"][0]["description"] == texts["ambiguous"]["option"].format(count=2)
+    typo = run("DEMU1234565 어디야?")["question"]
+    assert typo["question"] == texts["typo"]["question"].format(tokens="[BL1]")
+    assert typo["options"] == [
+        {"label": "[BL1]", "description": texts["typo"]["as_bl"]},
+        {"label": texts["typo"]["skip_label"], "description": texts["typo"]["skip"]},
+    ]
+    many = build_identify_graph(lambda config: ["DEMO0002", "DEMO0003"]).invoke(
+        {"text": "TESU0000013 어디야?"}
+    )
+    assert many["question"]["question"] == texts["container"]["question"].format(token="[CNTR1]")
+    assert [o["description"] for o in many["question"]["options"]] == [
+        texts["container"]["all"].format(count=2),
+        texts["container"]["one"],
+        texts["container"]["one"],
+    ]
```

- [ ] **Step 2: 실패를 본다**

```bash
uv run pytest -q tests/graph/test_identify.py -k from_the_rules
```

Expected: `1 failed`. `FileNotFoundError: [Errno 2] No such file or directory: '…/rules/identify.yaml'` [실측 11-08].

- [ ] **Step 3: 코드**

```diff
--- /dev/null
+++ b/rules/identify.yaml
@@ -0,0 +1,15 @@
+# 번호를 읽다가 묻는 질문과 선택지 글 (설계 4.1·6.3). src/marvia/graph/identify.py가 읽는다.
+# {…} 칸은 코드가 채운다. 실제 번호가 드는 칸은 ambiguous의 raw뿐이다(주인의 화면에만 가고 모델에는 가지 않는다)
+questions:
+  ambiguous: # 붙여 쓴 번호를 어떻게 끊을지 모를 때 (계획 1)
+    question: "'{raw}'를 어떻게 읽을까요?"
+    option: "{count}건으로 조회" # 끊는 안마다 붙는 설명
+  typo: # 컨테이너 번호 모양인데 확인 숫자가 틀릴 때 (계획 6a). tokens는 가린 토큰([BL1] + [BL2])
+    question: "{tokens}은 컨테이너 번호 모양인데 확인 숫자가 맞지 않아요. 번호를 확인해 주세요"
+    as_bl: B/L 번호로 조회 # 권장안(같은 모양의 B/L일 수 있다)
+    skip_label: 조회하지 않음
+    skip: 고친 번호를 직접 적어 주세요
+  container: # 아는 화물 여럿이 한 컨테이너에 실렸을 때 (계획 6a). token은 컨테이너 토큰([CNTR1])
+    question: "컨테이너 {token}에 실린 화물이 여럿이에요. 어느 화물을 볼까요?"
+    all: "{count}건 모두 조회" # 권장안
+    one: 이 화물만 조회
--- a/src/marvia/graph/identify.py
+++ b/src/marvia/graph/identify.py
@@ -31,6 +31,7 @@ Watched = Callable[[RunnableConfig], list[str]]
 def read(state: IdentifyState) -> dict:
     """번호를 읽고 가린다. 애매한 덩어리나 확인 숫자가 틀린 컨테이너 모양 번호가 있으면 선택지를 만든다."""
     text = state.get("text", "")
+    asks = load_rules("identify")["questions"]  # 질문·선택지 글
     # [왜] 같은 대화(thread)의 앞 차례 표를 이어 쓴다. 차례가 바뀌어도 같은 번호는 같은 토큰이고,
     #      모델이 기록에서 본 [BL1]을 이번 차례에도 조회할 수 있다 (계획 3d)
     masked, mask_map = mask_text(text, state.get("mask_map"))
@@ -43,10 +44,13 @@ def read(state: IdentifyState) -> dict:
             #        오타 번호는 아래에서 이 질문에 밀리지 않게 따로 모은다
             question = {
                 "kind": "choice",
-                "question": f"'{read_result.raw}'를 어떻게 읽을까요?",
+                "question": asks["ambiguous"]["question"].format(raw=read_result.raw),
                 # 선택지마다 화면에 보일 이름과 설명
                 "options": [
-                    {"label": " + ".join(alt), "description": f"{len(alt)}건으로 조회"}
+                    {
+                        "label": " + ".join(alt),
+                        "description": asks["ambiguous"]["option"].format(count=len(alt)),
+                    }
                     for alt in read_result.alternatives
                 ],
                 "recommended": 0,  # [왜] 권장안을 맨 앞에 둔다 (Codex·DeepSeek 방식, 설계 결정 4)
@@ -63,12 +67,13 @@ def read(state: IdentifyState) -> dict:
         #      (계획 6a). 오타가 여럿이어도 질문은 하나이고, 화면 글에는 토큰만 쓴다
         tokens = [token_for(mask_map, n.value, n.kind) for n in typos]
         joined = " + ".join(tokens)
+        typo = asks["typo"]
         question = {
             "kind": "choice",
-            "question": f"{joined}은 컨테이너 번호 모양인데 확인 숫자가 맞지 않아요. 번호를 확인해 주세요",
+            "question": typo["question"].format(tokens=joined),
             "options": [
-                {"label": joined, "description": "B/L 번호로 조회"},
-                {"label": "조회하지 않음", "description": "고친 번호를 직접 적어 주세요"},
+                {"label": joined, "description": typo["as_bl"]},
+                {"label": typo["skip_label"], "description": typo["skip"]},
             ],
             "recommended": 0,
             "alternatives": [[n.value for n in typos], []],
@@ -266,11 +271,12 @@ def choose(state: IdentifyState) -> dict:
     mask_map = dict(state.get("mask_map", {}))
     # [왜] 선택지 글에는 토큰만 쓴다. 화면에 보낼 때 view.interrupt_card가 실제 번호로 되돌린다
     tokens = [token_for(mask_map, number, kind_of(number)) for number in many["candidates"]]
+    asks = load_rules("identify")["questions"]["container"]
     question = {
         "kind": "choice",
-        "question": f"컨테이너 {many['token']}에 실린 화물이 여럿이에요. 어느 화물을 볼까요?",
-        "options": [{"label": " + ".join(tokens), "description": f"{len(tokens)}건 모두 조회"}]
-        + [{"label": token, "description": "이 화물만 조회"} for token in tokens],
+        "question": asks["question"].format(token=many["token"]),
+        "options": [{"label": " + ".join(tokens), "description": asks["all"].format(count=len(tokens))}]
+        + [{"label": token, "description": asks["one"]} for token in tokens],
         "recommended": 0,  # [왜] 하나를 짐작하지 않고 모두 보이는 안을 권장한다
         "alternatives": [many["candidates"]] + [[number] for number in many["candidates"]],
     }
```

- [ ] **Step 4: 확인**: 명령 A. Expected: `831 passed`, 오류 0. 질문 글을 박은 기존 시험이 고치지 않은 채 통과한다 [실측 11-08].

- [ ] **Step 5: 커밋**

```bash
git add rules/identify.yaml src/marvia/graph/identify.py tests/graph/test_identify.py
git commit -m "refactor(graph): 식별 질문·선택지 글을 rules/identify.yaml로 옮김"
```

### Task 11: 컨테이너 선택지가 떠 있는 동안 화물 카드에 그 컨테이너의 "여럿" 줄을 싣지 않는다 (항목 K, C11)

**배울 것:** 서버는 그래프 갱신을 흘려 받으며 화면 보기를 만든다. 서브그래프 안의 갱신은 화물 칸에 합치기만 하고(`merge_cargos`), 서브그래프가 끝나면 바깥 노드 갱신으로 칸을 통째로 바꾼다. 그래서 `choose`가 돌려준 `cargos`가 카드가 뜰 때의 마지막 화면 보기가 된다. 후보 줄은 조회 서브그래프(`collect`)가 그대로 만들고, 선택지는 그 줄의 후보로 만든 뒤 칸에서 뺀다.

#### 커밋 11: fix(graph): 컨테이너 선택지가 떠 있는 동안 화물 카드에 그 컨테이너의 여럿 줄을 싣지 않음

**Files:**
- Modify: `src/marvia/graph/identify.py`
- Test: `tests/graph/test_server.py`, `tests/graph/test_identify.py`(기존 시험의 관찰 지점만 옮김)

**Interfaces:**
- Produces: `choose`가 `{"question", "mask_map", "numbers", "cargos"}`를 돌려준다(`cargos`에서 후보 줄을 뺀 값)

- [ ] **Step 1: 실패하는 시험**: `test_server.py`의 새 시험이 실패하는 시험이다. `test_identify.py`의 기존 시험은 같은 단언을 조회 서브그래프 출력에서 본다(식별 출력에서는 이 커밋이 그 줄을 뺀다. 지금도 통과한다).

```diff
--- a/tests/graph/test_identify.py
+++ b/tests/graph/test_identify.py
@@ -1,6 +1,6 @@
 from langchain_core.runnables import RunnableConfig
 
-from marvia.graph.identify import build_identify_graph
+from marvia.graph.identify import build_identify_graph, build_lookup_graph
 from marvia.tools.rules import load_rules
 
 
@@ -104,10 +104,9 @@ def test_a_bl_in_the_same_message_carries_the_container(monkeypatch):
 
 def test_a_container_on_two_watched_cargos_is_left_as_candidates(monkeypatch):
     # [왜] 한 컨테이너에 여러 화물(LCL)이 실릴 수 있다. 하나를 골라 답하지 않는다
+    # [왜] 후보 줄은 조회 서브그래프가 만든다. 식별은 선택지를 띄울 때 그 줄을 화물 칸에서 뺀다 (계획 6c)
     seen = spy(monkeypatch)
-    out = build_identify_graph(lambda config: ["DEMO0002", "DEMO0003"]).invoke(
-        {"text": "TESU0000013 어디야?"}
-    )
+    out = build_lookup_graph(lambda config: ["DEMO0002", "DEMO0003"]).invoke({"numbers": ["TESU0000013"]})
     cargo = out["cargos"][0]
     assert (cargo["token"], cargo["confidence"], cargo["candidates"]) == (
         "[CNTR1]",
--- a/tests/graph/test_server.py
+++ b/tests/graph/test_server.py
@@ -712,6 +712,19 @@ def test_only_a_409_for_a_card_that_is_gone_carries_the_stale_card_code():
     assert busy.json() == {"error": "이 대화는 아직 답하는 중이에요"}
 
 
+def test_the_screen_under_a_container_card_shows_no_container_many_line(agent_deps):
+    # [왜] 카드는 "어느 화물을 볼까요?"인데 화물 카드가 "B/L 번호를 알려 주세요"를 보이면 서로 어긋난다
+    watched = lambda user: ["DEMO0002", "DEMO0003"]  # noqa: E731
+    watch = WatchDeps(
+        add=lambda *row: None, news=lambda user: [], ack=lambda user, ids: None, numbers=watched
+    )
+    _, client = served(agent_deps, AIMessage(""), watch=watch)
+    events = run(client, body("t26", "DEMO0001 TESU0000013 어디야?"))
+    assert events[-1]["outcome"]["type"] == "interrupt"
+    last = [e["snapshot"] for e in events if e["type"] == "STATE_SNAPSHOT"][-1]
+    assert [(c["number"], c["error"]) for c in last["cargos"]] == [("DEMO0001", None)]
+
+
 def test_running_is_only_touched_while_the_guard_is_held(monkeypatch):
     # [왜] 잠금 밖의 변경은 시간이 맞아야만 드러나서(GIL) 아래의 스레드 시험은 못 잡는다. 여기서는 running의
     #      추가·삭제·순회가 일어날 때마다 잠금이 잡혀 있는지를 직접 본다 (한 번에 한 요청씩이라 결정적이다)
```

- [ ] **Step 2: 실패를 본다**

```bash
uv run pytest -q tests/graph/test_server.py tests/graph/test_identify.py -k "container_many_line or left_as_candidates"
```

Expected: `1 failed, 1 passed`. `Left contains one more item: ('TESU0000013', '이 컨테이너에 실린 화물이 여럿이에요. B/L 번호나 화물관리번호를 알려 주세요')` [실측 11-08].

- [ ] **Step 3: 코드**

```diff
--- a/src/marvia/graph/identify.py
+++ b/src/marvia/graph/identify.py
@@ -283,7 +283,10 @@ def choose(state: IdentifyState) -> dict:
     # [왜] 고른 화물을 메인 그래프의 lookup이 조회한다. 컨테이너는 조회할 번호에서 뺀다(두면 후보가 또 나온다)
     container = mask_map[many["token"]]
     numbers = [number for number in state.get("numbers", []) if number != container]
-    return {"question": question, "mask_map": mask_map, "numbers": numbers}
+    # [왜] 카드가 떠 있는 동안 화물 카드에 이 컨테이너의 "여럿이에요, B/L을 알려 주세요" 줄을 보이지 않는다.
+    #      카드와 어긋난다. 고른 뒤의 조회가 cargos를 새로 채운다
+    cargos = [cargo for cargo in state.get("cargos", []) if cargo is not many]
+    return {"question": question, "mask_map": mask_map, "numbers": numbers, "cargos": cargos}
 
 
 def _after_read(state: IdentifyState) -> str:
```

- [ ] **Step 4: 확인**: 명령 A. Expected: `832 passed`, 오류 0 [실측 11-08].

- [ ] **Step 5: 커밋**

```bash
git add src/marvia/graph/identify.py tests/graph/test_server.py tests/graph/test_identify.py
git commit -m "fix(graph): 컨테이너 선택지가 떠 있는 동안 화물 카드에 그 컨테이너의 여럿 줄을 싣지 않음"
```

### Task 12: 문서

**Files:**
- Modify: `docs/specs/2026-10-28-marvia-v2-design.md`, 이 계획 문서(결과 표)

- [ ] **Step 1: 설계**: 아래 diff대로 고친다. 자른 태스크가 있으면 그 줄은 넣지 않는다. 커밋한 날이 11-08이 아니면 날짜만 바꾼다.

```diff
--- a/docs/specs/2026-10-28-marvia-v2-design.md
+++ b/docs/specs/2026-10-28-marvia-v2-design.md
@@ -81,7 +81,7 @@
 |---|---|---|---|
 | ① 자동 식별 | 화물관리번호, B/L | UNI-PASS로 조회해 확정 | 1차 |
 | ① 자동 식별 | 서류 사진, 포워더 메시지 | 글에서 번호를 뽑아 위로 넘김 | 1차 |
-| ② 후보 제시 | 컨테이너 번호 | 이미 아는 화물(이 대화에서 조회한 화물, 감시 목록)의 컨테이너 번호와 맞춰 하나면 그 화물, 여럿이면 선택지, 없으면 B/L·화물관리번호를 묻는 정한 글. UNI-PASS로는 찾지 않는다. 실제 응답에 컨테이너 칸이 오는지 확인하기 전까지는 재생 데이터에서만 맞추고, 실제 모드에서는 감시 목록을 다시 조회하지 않고 정한 글을 낸다 (11-07, 계획 6a) | 1차 |
+| ② 후보 제시 | 컨테이너 번호 | 이미 아는 화물(이 대화에서 조회한 화물, 감시 목록)의 컨테이너 번호와 맞춰 하나면 그 화물, 여럿이면 선택지, 없으면 B/L·화물관리번호를 묻는 정한 글. UNI-PASS로는 찾지 않는다. 실제 응답에 컨테이너 칸이 오는지 확인하기 전까지는 재생 데이터에서만 맞추고, 실제 모드에서는 감시 목록을 다시 조회하지 않고 정한 글을 낸다 (11-07, 계획 6a). 선택지가 떠 있는 동안 화물 카드에는 그 컨테이너의 "여럿이에요" 줄을 보이지 않고, 고른 뒤에는 이번 차례에 이미 조회한 번호를 다시 조회하지 않는다 (11-08, 계획 6c) | 1차 |
 | ② 후보 제시 | 선박명·항차 | 후보를 찾아 좁히고 여럿이면 선택지 | 2차 |
 | ③ 안내 | 번호 없음(품목·출발지·예정일) | 필요한 번호와 이유를 설명하고 포워더에게 보낼 문장을 써 줌. 번호를 받아 오면 ①로 | 1차 |
 
@@ -90,7 +90,7 @@
 - 화물관리번호: 19자리 = MRN 11 + MSN 4 + HSN 4. 앞 11자리 MRN이 해수부 선박운항정보의 `mrNum`과 같아 배를 특정한다(v1 `backend/app/services/judge/customs.py:13`, 실제 B/L로 확인).
 - B/L: 영문 접두어 + 숫자. 같은 접두어가 반복되면 그 자리에서 나눈다(`HASL0001HASL0002` → 2건).
 - 컨테이너 번호 (11-07, 계획 6a): ISO 6346 모양(소유자 부호 영문 3 + U·J·Z + 숫자 6 + 확인 숫자)에 확인 숫자가 맞을 때만 컨테이너로 읽는다. 컨테이너 모양으로 띄어 쓴 꼴(`DEMU 123456 0`, `DEMU 123 456 0`, `DEMU 123456 (0)`, 공백 여러 칸·탭·NBSP·하이픈)은 확인 숫자와 상관없이 한 덩어리로 가린다. 확인 숫자가 틀린 같은 모양은 전처럼 B/L로 읽되 조회 전에 "확인 숫자가 맞지 않아요"로 묻는다(권장안은 B/L 조회). 그런 번호가 여럿이면 한 질문으로 묻고, 같은 글에 애매한 덩어리 질문이 있으면 그 질문이 남고 오타 번호는 권장안대로 B/L로 조회한다(오타 번호는 말없이 빠지지 않는다. 애매한 덩어리가 둘이면 마지막 것만 묻는 계획 1의 한계는 그대로다). 남은 한계: 에이전트 길에서는 모델이 사용자가 카드에서 고른 답을 보지 못해, "조회하지 않음"을 고른 번호를 `lookup_cargo`로 다시 조회하거나 컨테이너 카드에서 화물을 고른 뒤에도 컨테이너 토큰을 조회해 "B/L을 알려 주세요" 줄을 더할 수 있다. 번호가 드러나지는 않는다. 고치려면 측정한 에이전트 지시문을 바꿔야 해서 다음 유료 측정 때 함께 정한다. 띄어 쓴 컨테이너 둘을 붙인 꼴은 가리지 않는다. 확인 숫자까지 맞는 11자 B/L은 컨테이너로 읽혀 어느 길로도 조회할 수 없다(11-07 저녁). 화물통관진행정보는 화물관리번호·B/L로만 찾으므로(data.go.kr 15126268) 컨테이너 번호는 어느 모드에서도 UNI-PASS에 보내지 않는다.
-- 정리: 공백·하이픈 제거, 대문자화, OCR 혼동 후보(O/0, I/1)는 원본과 함께 후보로 남긴다.
+- 정리: 공백·하이픈 제거, 대문자화, OCR 혼동 후보(O/0, I/1)는 원본과 함께 후보로 남긴다. 같은 번호는 처음 순서대로 한 번만 조회하고 한 줄로 보인다(같은 번호를 두 번 적거나 고른 컨테이너 후보가 같은 글의 B/L일 때, 11-08 계획 6c).
 - 나누는 방법이 하나뿐이고 형식 검사를 통과하면 진행하고 "두 건(…)으로 읽었어요"와 "다르게 읽기"를 보여 준다. 여럿이거나 실패하면 선택지 interrupt.
 - 서류 사진: OCR(v1 rapidocr 방식 참고) 후 같은 규칙. 메시지: 정규식이 먼저, 정규식이 못 잡은 칸만 LLM 구조화 추출.
 - 번호 가림: LLM에 넘기기 전에 실제 번호를 `[BL1]`, `[CARGO1]`, `[CNTR1]` 같은 토큰으로 바꾼다. 실제 값은 state의 `masked_map`에만 둔다.
@@ -212,7 +212,7 @@
 
 ### 6.3 interrupt 두 통로
 
-- 선택지 질문: `{"kind": "choice", "question", "options": [{"label", "description"}], "recommended": 0}` → 재개 값 `{"selected": i, "custom": "..."}`. 화면이 "기타" 입력칸과 "권장안으로 진행" 버튼을 붙인다. 답이 없는 재개 `{"timeout": true}`(시간은 서버나 화면이 잰다)는 권장안으로 진행하고 `assumptions`에 남긴다. `ask_user`는 그 차례의 도구 호출 중 혼자여야 한다.
+- 선택지 질문: `{"kind": "choice", "question", "options": [{"label", "description"}], "recommended": 0}` → 재개 값 `{"selected": i, "custom": "..."}`. 화면이 "기타" 입력칸과 "권장안으로 진행" 버튼을 붙인다. 답이 없는 재개 `{"timeout": true}`(시간은 서버나 화면이 잰다)는 권장안으로 진행하고 `assumptions`에 남긴다. `ask_user`는 그 차례의 도구 호출 중 혼자여야 한다. 식별이 묻는 질문(애매한 덩어리, 컨테이너 모양 오타, 컨테이너 후보)의 글은 `rules/identify.yaml`에 둔다 (11-08, 계획 6c).
 - 승인: `HumanInTheLoopMiddleware`의 묶음(batched) 모양을 따른다. `{"action_requests": [{"name", "args", "description"}], "review_configs": [...]}` → 재개 값 `{"decisions": [{"type": "approve" | "edit" | "reject", ...}]}`. 카드 설명에는 저장할 사실을 보인다. 권한 모드는 ask/auto이고, auto여도 밖으로 나가는 메시지는 늘 묻고(always_ask), 모르는 값은 묻는다.
 - 승인 지점: 품목 카드 저장·수정, 설명 깊이 저장(`save_preference`), 감시 목록 등록(`watch_cargo`)은 auto에서도 늘 묻는다(`approval.always_ask`). 카드에서 고친(edit) 인자로 도구가 돌고 고친 값도 같은 검사를 받는다 (시험 있음, 11-06). 밖으로 나가는 메시지 발송(2차), 웹 자료를 코퍼스에 추가(2차).
 - 감시 끄기 (11-07, 계획 4b): `unwatch_cargo`도 `always_ask`라 auto에서도 승인 뒤에만 돈다. 번호는 서버의 감시 표에서 해시로 찾고, 모델에게 가는 글은 토큰뿐이다.
@@ -275,7 +275,7 @@ UNI-PASS 같은 외부 조회 호출은 타임아웃, 재시도 2회, 실패하
   - 감시 표(`watches`, `watch_events`): 실제 번호는 앱이 Fernet으로 암호화해 두고 같은 번호 검사는 HMAC-SHA256 해시로 한다. 암호화 키와 해시 키는 `MARVIA_DATA_KEY`에서 HKDF로 따로 뽑는다. 키가 없거나 Fernet 키 모양이 아니면 감시를 끈다. 변화는 답에 보인 뒤에만 본 것으로 표시한다. `forget_user`가 한 사용자의 감시와 변화 기록을 지운다 (11-06)
   - 마이그레이션은 SQL 파일로 둔다. 운영은 표 준비를 한 번 도는 명령(`python -m marvia.prepare_db`, compose `prepare`, Cloud Run 작업)으로 하고 서버 시작에서는 하지 않는다 (11-07)
   - 검색·조문 조회는 autocommit 읽기 연결 풀에서 부를 때마다 연결을 빌린다. 읽은 뒤 열린 트랜잭션(idle in transaction)이 남지 않는다 (11-07 R-066)
-  - 계정 삭제(`DELETE /account`)는 감시 목록과 변화, 장기 기억(`("users", uid)` 아래 모든 이름 공간), 그 사용자의 대화 기록(`uid/`로 시작하는 thread의 체크포인트 세 표)을 지운다. 감시 연결은 공유라 그 위에 트랜잭션을 열지 않고, 대화 기록 삭제는 짧게 연 자기 연결의 트랜잭션 하나로 한다. 감시·기억·대화 기록은 따로 커밋되지만 다시 불러도 안전하다. 그 사용자의 차례가 도는 중이면 409다. 화물 하나의 감시는 `unwatch_cargo`가 승인 뒤에 끈다 (11-07 R-033)
+  - 계정 삭제(`DELETE /account`)는 감시 목록과 변화, 장기 기억(`("users", uid)` 아래 모든 이름 공간), 그 사용자의 대화 기록(`uid/`로 시작하는 thread의 체크포인트 세 표)을 지운다. 감시 연결은 공유라 그 위에 트랜잭션을 열지 않고, 대화 기록 삭제는 짧게 연 자기 연결의 트랜잭션 하나로 한다. 감시·기억·대화 기록은 따로 커밋되지만 다시 불러도 안전하다. 그 사용자의 차례가 도는 중이면 409이고, 지우는 동안 들어온 그 사용자의 새 차례와 두 번째 삭제도 409다(11-08, 계획 6c). 화물 하나의 감시는 `unwatch_cargo`가 승인 뒤에 끈다 (11-07 R-033)
 - Store 네임스페이스: `("users", uid, "items")` 품목 카드, `("users", uid, "prefs")` 설명 깊이 같은 설정(값은 규칙의 목록 안에서만)
 - 품목 카드는 승인 뒤에만 Store `("users", uid, "items")`에 저장한다. 이름은 짧게(규칙 `memory.max_item_name`), 화물 번호·토큰·문장 부호를 넣지 않는다 (11-06).
 - 저장 기준: 승인된, 다음 수입에도 유효한 사실만 저장한다. 이번 대화 값은 state에만 둔다. B/L 원문과 지시문처럼 보이는 문장은 저장하지 않는다.
@@ -293,7 +293,7 @@ UNI-PASS 같은 외부 조회 호출은 타임아웃, 재시도 2회, 실패하
 - Next.js(App Router). AG-UI 이벤트를 받아 그린다.
 - 구성: 채팅 / 계획 진행(할 일 목록과 현재 단계) / "이렇게 읽었어요" 표시 / 선택지 카드 / 승인 카드 / 답변과 근거 패널(조문 원문, 시행일, 출처 링크) / 화물 카드(통관 단계, ETA, 등급).
 - 로그인: Supabase Auth. 사용자 id로 thread와 Store를 나눈다.
-- 구현 (11-07, 계획 4b): 서버는 ag-ui-langgraph 어댑터 없이 `ag-ui-protocol` 1.0.0의 이벤트로 `POST /agui` 하나를 직접 쓴다(어댑터는 화면이 보낸 메시지·state를 그래프 입력에 합치고 공책 전체를 보낸다). 받는 값은 마지막 사용자 글과 재개 값뿐이고, 보내는 값은 허용 목록(할 일, 읽은 번호, 화물 카드, 근거 패널, 카드)뿐이다. 사용자는 서명을 확인한 토큰(ES256, 공개키 목록 JWKS)과 소유자 목록에서만 꺼내고, 대화 키는 서버가 "사용자/이름"으로 만든다. 토큰은 aud·iss·exp·sub가 모두 있어야 하고 시계 차이는 30초까지 봐주며, 공개키 목록 받기는 5초에 끊고, Supabase 주소는 https여야 서버가 뜬다. 목록 밖 사용자는 403, 그 밖의 실패는 사유 글 없이 401이다. 서버는 마지막 사용자 메시지 하나만 읽고(그 메시지가 사용자 글이 아니면 422), 선택지 번호는 멈춘 카드의 선택지 안에서만 받고(밖이면 422), 취소한 카드는 payload를 읽지 않고 권장안(승인 카드는 거절)으로 간다. 지난 카드 id로 재개하거나 답하는 중인 대화에 또 보내면 409다. 서버는 `MARVIA_HOST`(기본 127.0.0.1)에서 듣고, 컨테이너만 0.0.0.0으로 연다. 같은 대화 잠금이 프로세스 안에서만 지켜지므로 Cloud Run은 인스턴스 하나로 배포한다(`--max-instances 1`, 늘릴 때는 thread 키에 `pg_try_advisory_lock`, R-073). 화면은 Next.js 16 한 쪽이고 SSE를 `fetch`로 읽는다(CopilotKit·`@ag-ui/client` 없이). 화물 카드의 ETA·등급은 선박 위치 조회와 함께 2차로 미루고 카드에 그렇게 적는다. 승인 카드에서 고친 값과 거절 글은 서버가 그 대화의 가림 표로 다시 가린 뒤 재개한다. 고친 인자는 JSON 글로 모델에 가므로 키와 숫자 값까지 번호 검사를 하고, 대화에 없던 번호가 하나라도 있으면 실행하지 않고 정해 둔 거절로 바꾼다. 승인 카드 글은 도구 이름 대신 한국어 이름(`rules/agent.yaml`의 `approval.labels`)을 쓴다. 바깥으로 메시지를 보내는 도구는 만들지 않았다(보낼 통로가 없고 6.3에서 2차로 둔 일이다). 주요 흐름 넷과 접근성(axe)은 공식 Playwright 이미지 안에서 가짜 모델로 시험한다
+- 구현 (11-07, 계획 4b): 서버는 ag-ui-langgraph 어댑터 없이 `ag-ui-protocol` 1.0.0의 이벤트로 `POST /agui` 하나를 직접 쓴다(어댑터는 화면이 보낸 메시지·state를 그래프 입력에 합치고 공책 전체를 보낸다). 받는 값은 마지막 사용자 글과 재개 값뿐이고, 보내는 값은 허용 목록(할 일, 읽은 번호, 화물 카드, 근거 패널, 카드)뿐이다. 사용자는 서명을 확인한 토큰(ES256, 공개키 목록 JWKS)과 소유자 목록에서만 꺼내고, 대화 키는 서버가 "사용자/이름"으로 만든다. 토큰은 aud·iss·exp·sub가 모두 있어야 하고 시계 차이는 30초까지 봐주며, 공개키 목록 받기는 5초에 끊고, Supabase 주소는 https여야 서버가 뜬다. 목록 밖 사용자는 403, 그 밖의 실패는 사유 글 없이 401이다. 서버는 마지막 사용자 메시지 하나만 읽고(그 메시지가 사용자 글이 아니면 422), 선택지 번호는 멈춘 카드의 선택지 안에서만 받고(밖이면 422), 취소한 카드는 payload를 읽지 않고 권장안(승인 카드는 거절)으로 간다. 지난 카드 id로 재개하거나 답하는 중인 대화에 또 보내면 409다. 409 본문은 서버가 정한 글이고 화면은 그 글을 그대로 보이며, 지난 카드(`code: stale_card`)일 때만 카드를 치운다(11-08, 계획 6c). 화면이 정하는 대화 id의 길이 상한은 `rules/server.yaml`의 `request.max_thread_id`(64)다. 서버는 `MARVIA_HOST`(기본 127.0.0.1)에서 듣고, 컨테이너만 0.0.0.0으로 연다. 같은 대화 잠금이 프로세스 안에서만 지켜지므로 Cloud Run은 인스턴스 하나로 배포한다(`--max-instances 1`, 늘릴 때는 thread 키에 `pg_try_advisory_lock`, R-073). 화면은 Next.js 16 한 쪽이고 SSE를 `fetch`로 읽는다(CopilotKit·`@ag-ui/client` 없이). 화물 카드의 ETA·등급은 선박 위치 조회와 함께 2차로 미루고 카드에 그렇게 적는다. 승인 카드에서 고친 값과 거절 글은 서버가 그 대화의 가림 표로 다시 가린 뒤 재개한다. 고친 인자는 JSON 글로 모델에 가므로 키와 숫자 값까지 번호 검사를 하고, 대화에 없던 번호가 하나라도 있으면 실행하지 않고 정해 둔 거절로 바꾼다. 승인 카드 글은 도구 이름 대신 한국어 이름(`rules/agent.yaml`의 `approval.labels`)을 쓴다. 바깥으로 메시지를 보내는 도구는 만들지 않았다(보낼 통로가 없고 6.3에서 2차로 둔 일이다). 주요 흐름 넷과 접근성(axe)은 공식 Playwright 이미지 안에서 가짜 모델로 시험한다. 11-08(계획 6c): 409 안내, 계정 삭제(확인에 초점, 지운 뒤 대화를 비움, 401이면 로그아웃) 흐름을 더했고, Playwright 이미지는 root가 아닌 `pwuser`로 돈다
 
 ## 11. 평가와 관측
 
@@ -310,7 +310,7 @@ UNI-PASS 같은 외부 조회 호출은 타임아웃, 재시도 2회, 실패하
 - GitHub Actions (11-06 구현): 키 없이 린트·형식·타입·시험을 돌리고, 저장소에 커밋한 파생 값 줄을 지금 지표 코드로 다시 채점해 바닥값 아래면 실패시킨다. 바닥값은 코드가 기준 실행에서 만들고(`run_eval.py floors`), 저장한 결과가 평가셋 문항을 모두 덮어야 통과한다. 모델 응답은 저장소에 두지 않으므로 응답 재생은 하지 않는다.
 - 간접 주입 시험 (11-06 구현): promptfoo가 Docker 안에서 다섯 통로(검색 결과 본문, 저장된 품목 카드, 공식 페이지 제목, 서류 사진 글, 사용자 글)에 같은 주입 글을 넣고, 같은 사례를 pytest가 가짜 모델로 키 없이 돈다. 차례가 실제로 돌지 않은 경우는 통과로 치지 않는다. 실제 모델 5/5 통과, 주입을 따르는 가짜 모델 5/5 실패 [실측 11-06].
 - 측정 뒤 바뀐 것 (11-07, 계획 4b): 위 평가 수치는 각 줄에 적은 측정 커밋의 코드와 지시문으로 잰 값이다. 그 뒤 에이전트 지시문(`prompts/agent.md`)에 규칙 한 줄(`unwatch_cargo`, `cc1aa92`)이 더해졌고 도구가 하나 늘었다. 이 변경 뒤로 평가셋은 다시 돌리지 않았으므로 수치는 새 지시문에서 잰 값이 아니다.
-- Langfuse (11-08 연결, 계획 6b): 노드·도구·LLM 호출마다 트레이스(OTel, SDK 5.0.4)를 남긴다. 기본은 꺼짐이고 `MARVIA_LANGFUSE_PUBLIC_KEY`·`MARVIA_LANGFUSE_SECRET_KEY`·`MARVIA_LANGFUSE_HOST`가 모두 있을 때만 켜진다(하나라도 비면 SDK를 불러오지도 않는다). 서버·CLI(`scripts/try_agent.py`)·평가(`scripts/run_eval.py`, 결과 meta의 `tracing`)가 같은 콜백(`trace.tracer_callbacks`)을 쓴다. 내보내는 값은 네 겹으로 가린다: Langfuse SDK가 만든 span만 내보내기(다른 라이브러리의 OTel span은 내보내지 않는다), `mask=scrub`(input·output·metadata), `mask_otel_spans`(그 밖의 span 속성, 끼어들기 질문이 드는 `status_message` 포함), 오류를 가린 사본으로 넘기는 콜백(span 상태 설명). 감시 변화·Send 갈래·식별 끼어들기·직접 입력·조사 서브에이전트·답·도구와 모델 오류를 지나는 한 시나리오에서 내보낸 span 전체에 번호가 0개이고, 네 겹을 모두 빼면 11개(사용자가 정한 thread_id 포함)가 모두 남고, 한 겹씩 빼면 그 겹이 맡은 번호가 남는 문 시험이 있다. 실제 Langfuse 서버로는 아직 보내 보지 않았다(키). 가림 때문에 사용자·thread id(UUID 모양)와 모델 이름으로는 트레이스를 찾거나 비용을 계산할 수 없고, 끼어들기와 재개는 트레이스 둘이다(LangGraph 1.2.18). SDK의 미디어 올리기는 끈다(가림 전에 base64 글을 풀어 올리기 때문). Langfuse 주소는 https만 받는다(로컬 http 예외). LangSmith 추적 환경 변수(R-069)나 접두어 없는 `LANGFUSE_*` 환경 변수가 있으면 서버가 뜨지 않는다. 프롬프트 등록과 평가 점수 붙이기는 15절로 미뤘다.
+- Langfuse (11-08 연결, 계획 6b): 노드·도구·LLM 호출마다 트레이스(OTel, SDK 5.0.4)를 남긴다. 기본은 꺼짐이고 `MARVIA_LANGFUSE_PUBLIC_KEY`·`MARVIA_LANGFUSE_SECRET_KEY`·`MARVIA_LANGFUSE_HOST`가 모두 있을 때만 켜진다(하나라도 비면 SDK를 불러오지도 않는다). 서버·CLI(`scripts/try_agent.py`)·평가(`scripts/run_eval.py`, 결과 meta의 `tracing`)가 같은 콜백(`trace.tracer_callbacks`)을 쓴다. 내보내는 값은 네 겹으로 가린다: Langfuse SDK가 만든 span만 내보내기(다른 라이브러리의 OTel span은 내보내지 않는다), `mask=scrub`(input·output·metadata), `mask_otel_spans`(그 밖의 span 속성, 끼어들기 질문이 드는 `status_message` 포함), 오류를 가린 사본으로 넘기는 콜백(span 상태 설명). 감시 변화·Send 갈래·식별 끼어들기·직접 입력·조사 서브에이전트·답·도구와 모델 오류를 지나는 한 시나리오에서 내보낸 span 전체에 번호가 0개이고, 네 겹을 모두 빼면 11개(사용자가 정한 thread_id 포함)가 모두 남고, 한 겹씩 빼면 그 겹이 맡은 번호가 남는 문 시험이 있다. 실제 Langfuse 서버로는 아직 보내 보지 않았다(키). 가림 때문에 사용자·thread id(UUID 모양)와 모델 이름으로는 트레이스를 찾거나 비용을 계산할 수 없고, 끼어들기와 재개는 트레이스 둘이다(LangGraph 1.2.18). SDK의 미디어 올리기는 끈다(가림 전에 base64 글을 풀어 올리기 때문). Langfuse 주소는 https만 받는다(로컬 http 예외). 역슬래시나 공백이 든 주소는 거절한다(주소를 읽는 쪽마다 다른 호스트로 읽는다, 11-08 계획 6c). `mask_otel_spans`는 SDK가 JSON으로 적은 값(trace metadata, 시각)을 읽어서 가린 뒤 다시 적어, 가린 뒤에도 JSON이 깨지지 않고 ISO 시각은 그대로 남는다(11-08 계획 6c). LangSmith 추적 환경 변수(R-069)나 접두어 없는 `LANGFUSE_*` 환경 변수가 있으면 서버가 뜨지 않는다. 프롬프트 등록과 평가 점수 붙이기는 15절로 미뤘다.
 
 ## 12. 신뢰 경계
 
@@ -332,7 +332,7 @@ UNI-PASS 같은 외부 조회 호출은 타임아웃, 재시도 2회, 실패하
 | 에이전트 | LangGraph 1.x, langgraph-checkpoint-postgres, PostgresStore |
 | LLM | Anthropic API, 기본 `claude-haiku-5-5`. `init_chat_model`로 만들어 모델 이름만 바꾸면 다른 모델로 돈다. 구조화 출력은 `method="json_schema"` |
 | 임베딩·리랭커 | Voyage AI API 직접: 임베딩 `voyage-4`, 리랭커 `rerank-3` (11-02 문서 확인: 두 모델 모두 무료 2억 토큰, 그 뒤 백만 토큰당 $0.06·$0.05) |
-| 로컬 | docker compose: Postgres + pgvector, Neo4j, profile app(표 준비 → api :8080, 화면 :3000), profile e2e(가짜 모델 API, 화면, Playwright, 바깥 막힌 망). 모든 포트는 127.0.0.1, 이미지는 digest 고정 (11-07) |
+| 로컬 | docker compose: Postgres + pgvector, Neo4j, profile app(표 준비 → api :8080, 화면 :3000), profile e2e(가짜 모델 API, 화면, Playwright, 바깥 막힌 망). 모든 포트는 127.0.0.1, 이미지는 digest 고정 (11-07). `npm run dev`·`npm start`도 127.0.0.1에서만 듣는다 (11-08) |
 | 배포 | API Cloud Run(서울), 화면 Vercel, DB Supabase, 그래프 AuraDB 무료판, 해수부 릴레이는 기존 Cloud Run 유지 |
 | CI/CD | GitHub Actions, WIF(키 파일 없이 GCP 인증), Secret Manager, Docker 멀티스테이지(non-root, uid 10001). 배포 워크플로는 손으로만 시작하고(`workflow_dispatch`, 저장소 변수로 켜야 돈다), Cloud Run은 인스턴스 하나, 절차와 로컬 확인 기록은 `docs/deploy.md` (11-07) |
 | 저장소 규칙 | `main`은 v1 동결, 작업은 `v2`, 1차 완성 뒤 검토를 거쳐 `main`에 합친다 |
@@ -387,3 +387,4 @@ UNI-PASS 같은 외부 조회 호출은 타임아웃, 재시도 2회, 실패하
 - 11-07: 계획 4b. 원문·답 저장 안 함(8절), 읽기 연결 풀·표 준비 명령·계정 삭제와 감시 끄기(6.3·8절), AG-UI 직접 엔드포인트와 Starlette, 로그인·입력 검사·인스턴스 하나(3절·10절·12절), 승인 편집의 번호 거절과 한국어 이름(10절), 트레이스 가림 문과 남은 단서(11절), 측정 뒤 지시문 변경(11절), 로컬 compose와 배포 워크플로(13절)
 - 11-07: 계획 6a. 컨테이너 번호 식별(확인 숫자, 토큰 `[CNTR1]`, 아는 화물에서 찾기, 오타 질문) (4.1, 4.2, 15절)
 - 11-08: 계획 6b. Langfuse 트레이스 연결(기본 꺼짐, 네 겹 가림, `LANGFUSE_*` 시작 거절) (11절, 12절, 15절)
+- 11-08: 계획 6c. 지난 검토에서 넘긴 고침: 계정 삭제 중 409, 409 안내와 카드, 대화 id 상한 규칙, 로컬 화면 127.0.0.1·e2e pwuser, 계정 삭제 화면, 같은 번호 다시 조회 안 함과 중복 빼기, 식별 질문 글 규칙, ② JSON 가림, Langfuse 주소 거절, 컨테이너 카드 화면 (4.1, 4.2, 6.3, 8, 10, 11, 13절)
```

- [ ] **Step 2: 이 문서 끝에 "실행 결과" 표**: 태스크마다 커밋, 시험 수, 확인점에서 자른 것, C1~C12 판정(통과·못 넘음과 근거)을 적는다. 자른 항목은 "남은 한계"로 옮긴다.

- [ ] **Step 3: 진행 기록(저장소 밖)**: 4b 전체 검토 S-5·S-12·S-14·S-16, 4b의 삭제 버튼 다듬기, 6a C-3·C-6·minor 3·minor 4, 6b L-4와 주소 검사 줄을 닫힘으로 바꾸고 커밋을 적는다.

- [ ] **Step 4: 커밋**

```bash
git add docs/specs/2026-10-28-marvia-v2-design.md docs/plans/2026-11-08-marvia-v2-plan-6c-fixes.md
git commit -m "docs: 설계에 계획 6c 반영(계정 삭제 중 409, 409 안내, 다시 조회 안 함, 질문 글 규칙, ② JSON 가림)"
```

---
## 끝나면 되는 것

- 계정을 지우는 동안 그 사용자의 새 질문과 두 번째 삭제는 409 "계정을 지우는 중이에요"이고, 지운 기록이 다시 생기지 않는다. 다른 사용자는 막지 않는다.
- 화면은 409마다 서버가 정한 까닭을 그대로 보이고, 지난 카드일 때만 카드를 치운다. 답하는 중 409 뒤에도 카드에 다시 답할 수 있다.
- 컨테이너 카드에서 화물을 골라도 같은 글의 B/L은 한 번만 조회한다. 같은 번호를 두 번 적거나 "모두"가 같은 글의 B/L을 다시 담아도 조회와 답 줄은 하나다.
- 역슬래시나 공백이 든 Langfuse 주소로는 서버가 뜨지 않는다.
- `npm run dev`·`npm start`는 127.0.0.1에서만 듣고, 화면 시험은 root가 아닌 `pwuser`로 돈다.
- 트레이스 ② 겹이 가린 trace metadata는 JSON으로 읽히고, 스트리밍 시각은 시각으로 남는다. 번호는 여전히 0개다.
- 계정 삭제 확인에 초점이 가고, 401이면 로그아웃하고, 지운 뒤 다시 들어오면 대화가 비어 있다.
- 대화 id 상한(64)과 식별 질문 글이 규칙 파일에 있다. 컨테이너 카드가 떠 있는 동안 화물 카드는 카드와 어긋나는 줄을 보이지 않는다.
- 시험 832개가 키 없이 돌고, 화면 흐름 7개가 공식 Playwright 이미지에서 돈다.

## 설계와 대조

| 설계 | 이 계획 | 차이 |
|---|---|---|
| 4.1 ② 후보 제시(컨테이너) | 카드가 떠 있는 동안 후보 줄을 화면에 보이지 않는다(K), 고른 뒤 같은 글의 B/L을 다시 조회하지 않는다(F) | T12에서 줄을 더한다 |
| 4.2 정리 | 같은 번호는 한 번만 조회하고 한 줄로 보인다(G) | T12에서 줄을 더한다 |
| 6.3 선택지 질문 | 식별 질문 글을 `rules/identify.yaml`에 둔다(H). 글은 그대로다 | T12에서 줄을 더한다 |
| 8 계정 삭제 "그 사용자의 차례가 도는 중이면 409" | 지우는 동안 들어온 새 차례와 두 번째 삭제도 409(A) | T12에서 고친다 |
| 10 화면 "지난 카드 id로 재개하거나 답하는 중인 대화에 또 보내면 409" | 409 본문의 글을 화면이 보이고 `stale_card`일 때만 카드를 치운다(B). 대화 id 상한은 규칙 값(C). 계정 삭제 흐름과 pwuser(E·D) | T12에서 줄을 더한다 |
| 11 Langfuse "Langfuse 주소는 https만 받는다(로컬 http 예외)" | 역슬래시·공백 거절(J), ② 겹의 JSON 가림(I) | T12에서 줄을 더한다 |
| 12 신뢰 경계 | 바뀌지 않는다(가리는 범위는 그대로, 읽는 방식만 바뀐다) | 없음 |
| 13 로컬 "모든 포트는 127.0.0.1" | `npm run dev`·`npm start`도 127.0.0.1(D) | T12에서 줄을 더한다 |

## 직접 할 일

1. 배포한 화면에서(Supabase 로그인) 계정 삭제를 한 번 해 본다: 확인 묶음에 초점이 가는지, 지운 뒤 로그인 화면이 뜨고 다시 들어오면 대화가 비어 있는지. 시험은 개발 로그인과 가짜 API로만 보았다.
2. (11-08 끝남) 명령 C는 `ckpt/6c-final` 태그 트리를 푼 깨끗한 사본과 따로 만든 compose 프로젝트(내부 망, `pwuser` 이미지)에서 돌려 흐름 일곱이 모두 통과했다(8.5초) [실측 11-08]. 이 저장소의 작업 트리에서는 실행 확인을 받지 못해 돌리지 않았다.
3. 계획 6b의 직접 할 일 2(실제 Langfuse로 한 번 보내 보기)를 할 때, trace metadata(thread id)가 JSON으로 읽히고 스트리밍 응답의 첫 글자 시각(completion start time)이 시각으로 보이는지 함께 본다.

## 확인하지 못한 것

- Langfuse 서버가 ② 겹이 다시 적은 JSON 값(띄어쓰기 모양이 SDK와 다를 수 있다)과 시각을 받아 그대로 보이는지 [미확인, 키 없음]. 직접 할 일 3.
- 실제 UNI-PASS에서 F가 줄이는 호출. 지금 컨테이너 후보는 재생 모드에서만 생긴다. 고른 후보 B/L은 식별 안에서 한 번, ask 뒤에 한 번 더 조회한다(남은 한계).
- 같은 오타를 두 번 적으면 오타 카드 이름표가 `[BL1] + [BL1]`이다. "이렇게 읽었어요"에 컨테이너 후보 B/L이 보이는 것과, 카드가 뜨기 전 중간 화면 보기에 후보 줄이 잠깐 보일 수 있는 것은 그대로다.
- 애매한 덩어리·오타 카드가 떠 있는 동안 지난 차례 화물 카드가 사라진다(F의 `read`가 비운다). 화면 시험으로는 보지 않았다.
- Linux의 바인드 마운트에서 `pwuser`가 스크린샷 폴더에 쓸 수 있는지. macOS Docker Desktop에서만 보았다. CI는 화면 흐름을 돌리지 않는다.
- 플레인 `next dev`(`-H` 없음)의 듣는 주소는 표시된 Network 줄로만 보았다. 한 폴더에 dev 서버가 하나만 떠서 `/proc/net/tcp`로 함께 재지 못했다. `next start`는 재었다 [실측 11-08].
- 409·401 화면 흐름은 응답을 흉내 낸다. 실제 서버의 "잠금이 풀리기 전 재개" 틈을 브라우저로 만들지는 못했다. 서버 본문은 파이썬 시험이 본다.
- 평가셋을 다시 돌리지 않았다. 평가 문항에 같은 번호 두 번, 여럿 실린 컨테이너가 없다는 것은 번호 패턴 grep으로만 보았다.

## 실행 결과 (11-08)

하루 안에 끝나 자른 것은 없다. 유료 호출, 키, 실제 UNI-PASS는 쓰지 않았다($0). 시험 수는 커밋마다 `uv run pytest -q`를 저장소에서 돌린 값이다 [실측 11-08, 건너뜀 0]. 고침 커밋이 시험을 하나 더해 계획의 수보다 하나 많다.

| 태스크 | 커밋 | 시험 |
|---|---|---|
| T0 사전 등록 | e0444f5 | 818 |
| T1 A 계정을 지우는 동안 새 차례·두 번째 삭제 409 | 1ee0925 | 819 |
| T2 B 409에 서버의 까닭, 지난 카드일 때만 카드를 치움 | 6c969f2 | 820 |
| T3 F 컨테이너 선택지 뒤 같은 차례의 B/L 다시 조회 안 함 | 46745a2 | 822 |
| T4 G 조회할 번호의 중복을 한 곳에서 뺌 | dd13d3b | 824 |
| T5 J 역슬래시·공백이 든 Langfuse 주소 거절 | dd0d3c4 | 827 |
| T7 I ② 겹이 SDK의 JSON 값을 읽어 가리고 ISO 시각은 둠 | 8fa8624 | 828 |
| T7 고침: 시각 예외는 소수 6자리까지, 겹친 JSON 키는 글로 가림 | 0c27649 | 829 |
| T6 D 로컬 화면 서버 127.0.0.1, 시험 이미지 pwuser | 3ce7e47 | 830 |
| T8 E 계정 삭제 화면 다듬기 | 49dbbd5 | 830 |
| T8 고침: 지운 뒤 새 대화 id, 입력·진행 상태 비움 | ede19af | 830 |
| T9 C 대화 id 길이 상한을 규칙 파일로 | b2873a8 | 831 |
| T8 고침 2: 삭제 흐름이 둘째 요청을 기다린 뒤 견줌 | b15ba4d | 831 |
| T10 H 식별 질문·선택지 글을 규칙 파일로 | f4b14ff | 832 |
| T11 K 컨테이너 선택지 동안 화물 카드에 여럿 줄 없음 | 8a5c407 | 833 |

T6은 계획 순서와 달리 T7 뒤에 들어갔다(같은 날, 서로 다른 파일). 0c27649의 829는 그 커밋 상태의 시험 수를 셈한 값이다(그 시점의 전체 실행에는 아직 커밋하지 않은 T6 시험 하나가 섞여 830이었다).

| # | 판정 | 근거 |
|---|---|---|
| C1 | 통과 | 지우는 동안 같은 사용자의 `/agui`와 두 번째 삭제가 409, 다른 사용자는 200, `guard` 안에서만 집합을 바꾼다 |
| C2 | 통과 | 서버 409 본문과 `code: stale_card` 시험 통과. 화면 흐름 "409에는 서버가 보낸 까닭을 보이고, 지난 카드일 때만 카드를 치운다"는 T2 때 명령 C로 통과했고, `ckpt/6c-final` 깨끗한 사본에서 일곱 흐름과 함께 통과 [실측 11-08] |
| C3 | 통과 | DEMO0002 조회 1번, 애매한 덩어리 뒤에는 지난 차례 번호를 다시 조회(가림 줄을 빼면 `assert 1 == 2`) |
| C4 | 통과 | 같은 번호 두 번이 조회 1번·줄 하나, "모두"를 고르면 "2건으로 읽었어요." |
| C5 | 통과 | 새 주소 셋 거절, 받던 주소 넷 그대로, 거절 글에 키·주소 없음 |
| C6 | 통과 | `-H 127.0.0.1`과 `USER pwuser`(파이썬 시험 통과). 명령 C는 `ckpt/6c-final` 깨끗한 사본의 `pwuser` 이미지에서 흐름 일곱 통과 [실측 11-08]. 이 저장소의 작업 트리에서는 T6 뒤로 돌리지 않았다(실행 확인을 받지 못함) |
| C7 | 통과 | JSON 글이 JSON으로 남고 번호 0, ISO 시각 그대로, 소수 7자리 이상과 겹친 키는 가림, 6b 문 시험 그대로 통과 |
| C8 | 통과 | 화면 검사(명령 B) 통과. 새 흐름 둘("계정 삭제는 확인에 초점을 옮기고, 지운 뒤 다시 들어오면 대화가 비어 있다", "계정 삭제가 401이면 로그아웃한다")이 `ckpt/6c-final` 깨끗한 사본에서 통과 [실측 11-08] |
| C9 | 통과 | `request.max_thread_id` 64, 64자는 200, 65자는 422 |
| C10 | 통과 | 글 9개가 옛 글과 같고(프로그램으로 견줌), 글을 박은 기존 시험이 고치지 않은 채 통과 |
| C11 | 통과 | 서버 한 차례의 마지막 화물 카드가 DEMO0001 하나, 후보 줄은 조회 서브그래프 출력에 그대로 |
| C12 | 통과 | 818 → 833, 건너뜀 0, 커밋마다 ruff·형식·pyright 0, 커밋당 코드 파일 최대 5개(6c969f2), `git diff 7f715dc -- eval prompts` 0줄, em dash 0 |

남은 한계:
- 애매한 덩어리·오타 카드가 떠 있는 동안 지난 차례의 화물 카드가 화면에서 사라진다(T3의 대가).
- 명령 C는 이 저장소의 작업 트리에서 T6 뒤로 돌리지 못했고, `ckpt/6c-final` 깨끗한 사본에서 흐름 일곱 통과로 확인했다 [실측 11-08]. Linux 바인드 마운트에서 `pwuser`가 스크린샷 폴더에 쓸 수 있는지는 보지 않았다.
- `rules/identify.yaml`의 아래 키는 그 질문을 만들 때 읽으므로 키가 빠지면 시작할 때가 아니라 그때 오류가 난다.
- 계정 삭제를 그만두거나 실패하면 초점이 다시 사라진다.
- 아주 깊은 JSON(약 1000단)은 ② 겹에서 오류가 나 그 묶음을 내보내지 않는다(번호는 나가지 않는다).
