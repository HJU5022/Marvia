# Marvia 웹 화면

B/L 하나로 내 화물이 제때 오는지 판정하고 그 근거를 보여 주는 화면이다. Next.js 16 App Router, React 19, TypeScript로 만들었다 (`package.json`).

| 모드 | 조건 | 무엇이 뜨나 |
| --- | --- | --- |
| 데모 모드 | `NEXT_PUBLIC_API_BASE`가 비어 있음 (기본) | 백엔드 없이 `lib/fixtures/`의 가공 예시만 보여 준다 |
| 실제 모드 | `NEXT_PUBLIC_API_BASE`에 백엔드 주소가 있음 | 백엔드 API를 부른다 |

데모 모드는 화면만의 기능이다. 백엔드의 재생 모드(`REPLAY_MODE=true`, 외부 API 대신 `evals/fixtures/`를 읽는다)와는 다르다. 배포 화면(Railway `marvia-web`)은 실제 모드다.

화면은 백엔드 API(`lib/api.ts`)만 부른다. 외부 API를 직접 부르지 않고 서버 비밀 키를 갖지 않는다. 디자인 규칙은 [DESIGN.md](DESIGN.md), 지도·글꼴 출처는 [THIRD_PARTY.md](THIRD_PARTY.md)에 있다.

읽는 순서: [바로 실행](#바로-실행) → [화면](#화면) → [백엔드 붙이기](#백엔드-붙이기-실제-모드) → [검증](#검증).

## 바로 실행

Node.js 20.9 이상(`package.json` `engines`)과 npm이 필요하다. `web/`에서 실행한다.

```bash
npm install          # package-lock.json 그대로 받으려면 npm ci
npm run dev          # http://localhost:3000
```

키, `.env`, Docker, Python이 없어도 데모 모드로 뜨고, 첫 화면은 정상 예시 화물을 보여 준다. 글꼴과 지도는 레포 안 자산으로 돈다. 바깥으로 나가는 주소는 지도 바탕 `tiles.openfreemap.org` 하나이고, 닿지 않으면 레포 안 자산으로 되돌아간다 ([지도 바탕](#지도-바탕)).

프로덕션 빌드는 `npm run build && npm start`다. `npm run dev`와 `npm run build` 앞에서 `predev`·`prebuild`가 `scripts/copy-maplibre-worker.mjs`를 돌려 MapLibre 워커를 `public/maplibre/`로 복사한다. 이 폴더는 git에 올리지 않는다(`.gitignore`).

배포는 레포 루트에서 `railway up web --path-as-root --service marvia-web --detach`로 한다. `--path-as-root`가 없으면 루트 Dockerfile이 빌드돼 화면이 502가 된다 (루트 [CLAUDE.md](../CLAUDE.md) "배포 기록").

## 화면

페이지는 `app/` 아래 `page.tsx` 9개다. "보이는 사람"은 로그인이 켜져 있을 때 기준이다. 로그인이 꺼져 있으면 로그인 없이 열린다. 운영자 화면은 `GET /api/me`의 `is_operator`로 가리고, 데모 모드는 운영자로 본다 (`lib/api.ts` `getMe`).

| 주소 | 화면 | 보이는 사람 |
| --- | --- | --- |
| `/` | 대화와 화물 상세 | 로그인 사용자 |
| `/watch` | 감시 화물: 지켜보기를 켠 화물과 배의 위치·지나온 길을 한 지도에 (`GET /api/watch`), 그 아래 B/L 없이 지켜보는 배 목록 (`/api/watch/vessels`) | 로그인 사용자 |
| `/cargo` | 화물 현황 표: 신용장·출항일 편집, 엑셀 내려받기 (`/api/cargo/sheet*`) | 로그인 사용자 |
| `/history` | 조회 이력 (`GET /api/history`) | 로그인 사용자 |
| `/settings` | 탭 4개: 회원 정보, 기억한 화물, 알림·판정 기준(판단 기준 읽기 전용, 카카오 알림 연결), 계정 관리(내 기록 삭제, 회원 탈퇴) (`components/SettingsPage.tsx` `TABS`) | 로그인 사용자 |
| `/settings/kakao` | 카카오 동의 뒤 돌아오는 곳. 연결을 마무리하고 `/settings?kakao=결과`로 보낸다 | 로그인 사용자 |
| `/metrics` | 평가 지표 (`GET /api/metrics`) | 운영자 (`OperatorOnly`) |
| `/admin` | 탭 2개: 고객 관리(수정·정지·강제 탈퇴·가린 정보 보기), 운영자 관리 | 운영자 |
| `/about` | 제품 소개. 로그인 전에도 보인다 | 누구나 |

`/` 화면이 하는 일: 문장으로 묻기, 결과 status 5종(ok, partial, insufficient, failed, unsupported)과 판정 3등급(순항, 주의, 긴급) 표시, 후보 선박 고르기, 근거 펼치기, 후속 질문, 서류 사진·PDF 첨부, 선박 자세히 보기. 화면 나눔과 좁은 화면 동작은 [DESIGN.md](DESIGN.md) "화면 틀"에 있다.

사이드바 (`components/Shell.tsx`):

| 자리 | 항목 |
| --- | --- |
| 위 | 새 대화, 대화 목록 |
| 화물 묶음 | 감시 화물 `/watch`, 화물 현황 `/cargo`, 조회 이력 `/history` |
| 운영자에게만 | 평가 지표 `/metrics`, 관리 `/admin` (`GET /api/me`로 가린다. 권한은 서버가 막는다) |
| 아래 | Marvia 소개, 계정 메뉴(프로필, 알림·판정 기준, 계정 관리, 로그아웃) |

## 데모 모드

서버가 없으니 LLM도 없다. 입력 문장 속 예시 B/L만 알아보고 저장된 응답을 돌려준다 (`lib/api.ts` `demoChat`, `demoAgentResponse`). 저장된 예시를 새 입력에 맞춰 다시 판정하지 않는다.

- 입력창 아래 예시 칩은 누르면 입력창을 채울 뿐 보내지 않는다. 칩은 `MRVDEMO1101 화물 괜찮아?`, `MRVDEMO1107 지금 조치해야 해?`, `중국에서 부산 들어오는 배 보여줘`다 (`components/ChatBar.tsx`).
- 개발 서버(`npm run dev`)에서만 `/?fixture=ok|partial|insufficient|failed|unsupported|watch|act`로 첫 화면 예시를 고를 수 있다. 프로덕션 빌드에서는 이 주소 값을 무시한다 (`app/page.tsx`, `lib/api.ts` `selectFixture`).
- 예시는 모두 MASTER B/L이다. 저장된 판매 예정일·B/L 구분과 다르게 조회하면 조건이 다르다는 안내가 나온다.

| 예시 B/L (가공) | 판매 예정일 | 응답 (status / verdict) |
| --- | --- | --- |
| MRVDEMO1101 | 2026-10-25 | ok / fine |
| MRVDEMO1102 | 2026-10-25 | insufficient / null |
| MRVDEMO1103 | 2026-10-25 | partial / null, 위치 stale |
| MRVDEMO1104 | 2026-10-25 | failed / null |
| MRVDEMO1105 | 2026-10-25 | unsupported / null |
| MRVDEMO1106 | 2026-10-25 | ok / watch, 위치 stale |
| MRVDEMO1107 | 2026-10-20 | ok / act |

출처: `lib/fixtures/demo.json` `choices`, `lib/fixtures/{status}.json`. `verdict` 값 `fine`, `watch`, `act`의 화면 이름은 순항, 주의, 긴급이다 (`lib/format.ts` `verdictLabels`).

- 되묻기(insufficient)에서 첫 후보를 고르거나, 후보 없이 항차·포워더 ETA를 넣으면 정상 예시로 이어진다. 실제 식별 알고리즘이 아니라 한 가지 경우만 흉내 낸다.
- 후속 질문은 질문과 상관없이 `demo.json`의 `follow_up_answer`를 돌려주고, 이 답 첫 문장이 저장된 예시를 재생한다고 밝힌다.

## 백엔드 붙이기 (실제 모드)

`NEXT_PUBLIC_API_BASE` 값은 빌드할 때 들어가므로 바꾸면 dev 서버를 다시 켠다. 값은 `web/.env`에 둔다(`cp .env.example .env` 뒤 채운다, 커밋하지 않는다). 레포 루트 `.env`는 백엔드용이라 화면이 읽지 않는다.

```bash
# 레포 루트: 키 없이 백엔드 데모 13건 (루트 README "키 없이 데모")
docker compose up -d --build
docker compose exec api python -m scripts.demo.make_demo

# web/
NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev
```

- 백엔드 데모 B/L 13건은 라이브 시연 10건(`DEMO`로 시작)과 평가셋 3건(TESTBL01 정상, TESTBL04 되묻기, TESTBL26 판정 보류)이다 (`scripts/demo/make_demo.py` 머리 주석). 문장에 넣어 조회하고, 판매 예정일은 비우거나 `make_demo`가 보여 준 날을 넣는다.
- 백엔드 CORS `ALLOWED_ORIGINS`에 화면 주소(기본 `http://localhost:3000`, 루트 `.env.example`)가 있어야 한다.
- 세션 ID는 브라우저마다 만들어 localStorage에 둔다. 대화 저장이 꺼진 경우(로그아웃, 로그인 기능 꺼짐, 서버가 401/503)에는 탭의 sessionStorage로 대화를 이어 간다 (`components/AppProvider.tsx`).
- 제한: 이력 행에서 과거 결과 상세를 다시 볼 수 없다. `GET /api/history`는 요약만 주고, 화면은 새로 조회해서 과거 결과인 척하지 않는다.

### 로그인

백엔드가 `SUPABASE_URL`로 로그인을 켜면 화면도 아래 두 값을 넣어 켠다. 둘 다 브라우저에 보여도 되는 값이다. secret 키는 넣지 않는다.

```bash
NEXT_PUBLIC_API_BASE=http://localhost:8000 \
NEXT_PUBLIC_SUPABASE_URL=https://<프로젝트>.supabase.co \
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<publishable 키> npm run dev
```

| 상황 | 화면 |
| --- | --- |
| 두 값이 없음 | 로그인이 꺼지고 세션 ID로만 돈다. 채점용 compose와 같다 |
| 로그인 전 | 로그인 화면(Google). `/about`만 예외 |
| 로그인했지만 회원 정보(이름·전화·주소)가 없음 | 입력 화면이 먼저 나온다 (`GET /api/me`의 `profile_complete`, [docs/specs/user-profile.md](../docs/specs/user-profile.md)) |
| 운영자가 정지한 계정 | 정지 안내만 보인다 |

- 요청마다 `Authorization: Bearer <JWT>`를 붙인다. 백엔드는 ES256 공개키로 확인한다 (`backend/app/auth.py`).
- Supabase 대시보드에서 Google 공급자를 켜고 Redirect URL에 화면 주소(예: `http://localhost:3000/**`)를 넣어야 로그인 뒤 돌아온다.

### 함수와 endpoint (`lib/api.ts`, `lib/watchVessel.ts`)

| 함수 | 실제 endpoint |
| --- | --- |
| `sendChatStream` / `sendChat` | `POST /api/chat/stream` (SSE, 처리 단계 표시) / `POST /api/chat` (스트림 통로가 없는 서버면 이쪽으로 한 번 보낸다) |
| `getAgentResponse` | `POST /api/agent` (정해진 칸 입력, 되묻기 답, 다시 조회) |
| `readDocumentBl` | `POST /api/document/bl` (채팅 첨부, B/L·MRN만) |
| `readDocument`, `saveDocumentFacts` | `POST /api/document`, `POST /api/memory/document-facts` (옛 조회 폼 `DocumentPanel` 전용, 화면에서 안 씀) |
| `getHistory`, `deleteMyHistory` | `GET /api/history?session_id=`, `DELETE /api/history` |
| `getUsage` | `GET /api/usage` |
| `getVesselDetail` | `GET /api/vessels/detail` |
| `listConversations`, `getConversation`, `deleteConversation` | `/api/conversations*` |
| `getMemory`, `deleteAllMemory`, `deleteMemoryItem` | `/api/memory*` |
| `getWatchList`, `getWatchState`, `setWatch`, `getWatchChanges`, `markWatchChangesSeen` | `/api/watch*`, `/api/cargo/watch*` |
| `listWatchedVessels`, `watchVessel`, `unwatchVessel` (`lib/watchVessel.ts`) | `/api/watch/vessels*` |
| `getCargoSheet`, `saveCargoLc`, `saveCargoDeparted`, `downloadCargoSheet` | `/api/cargo/sheet*` |
| `getKakaoStatus`, `connectKakao`, `finishKakaoLink`, `sendKakaoTest`, `unlinkKakao` | `/api/kakao/*` |
| `getProfile`, `saveProfile` | `GET`, `PUT /api/profile` |
| `getMe`, `getCustomers`, `getOperators`, `grantOperator`, `revokeOperator`, `unmaskCustomer`, `updateCustomer`, `deleteCustomer`, `suspendCustomer`, `resumeCustomer`, `getAdminActions` | `/api/me`, `/api/admin/*` |
| `getMetrics` | `GET /api/metrics` (운영자) |
| `deleteMyAccount` | `DELETE /api/account` |

`getPresentationData`, `selectFixture`, `getReplaySnapshot`, `getGeography`는 화면 안의 보조 함수이고 endpoint가 아니다.

요청 규칙:

- `POST /api/agent`에는 요청 계약 `AgentRequest`(`backend/app/schemas/agent.py`)에 있는 칸만 보내고, 빈 값은 null로 바꿔 보낸다. 빈 문자열 날짜는 백엔드에서 422가 된다 (`lib/api.ts` `wireRequest`).
- 날짜는 ISO 문자열, 위치는 `lng`·`navistat`, ETA는 따로 된 4개 필드를 쓴다. `null`을 0이나 정상으로 바꾸지 않는다.
- 이력의 `available: false`는 "이력이 비었다"와 다르다. 이력을 못 읽어도 화면을 멈추지 않고 이 값으로 표시한다.
- 서버 API 키를 브라우저 코드나 `NEXT_PUBLIC_*` 값에 넣지 않는다.

## 지도 바탕

네 지도(`MapPanel`, `ChatMiniMap`, `VesselMap`, `WatchMap`)가 `lib/basemap.ts` 한 곳을 쓴다. Leaflet 지도 밑에 아래 세 단계 중 되는 첫 단계를 깐다. 배·부산항·경로·클러스터·말풍선은 어느 단계에서든 Leaflet이 그린다.

| 단계 | 바탕 | 다음 단계로 넘어가는 때 |
| --- | --- | --- |
| 1 | OpenFreeMap 벡터 지도 (`https://tiles.openfreemap.org/styles/positron`, MapLibre WebGL). 땅·바다 색은 `--land`, `--sea` 토큰으로 바꾼다 | WebGL이 없음, 스타일이 8초 안에 안 옴, 스타일이 온 뒤 8초 안에 타일이 한 장도 안 옴 |
| 2 | 미리 구운 타일 `public/basemap/{z}/{x}/{y}.webp`. WebGL이 없는 PC용. `public/basemap/meta.json`의 `tiles` 목록에 있는 것만 요청한다 | 타일을 못 불러옴 |
| 3 | Natural Earth 해안선 (`lib/fixtures/geography.json`). 오프라인에서도 되는 마지막 단계 | |

- 미리 구운 타일 범위는 위도 10~50, 경도 100~155, 확대 3~7이고, 확대 8은 위도 28~40, 경도 118~136이다 (`public/basemap/meta.json`).
- 다시 굽기: `node scripts/bake-basemap.mjs`. Playwright의 Chrome과 `sharp`를 쓴다. 지도 손질은 `lib/basemap.ts` `tune()`과 스크립트 안에 같은 내용으로 두 번 적혀 있으니 한쪽을 고치면 다른 쪽도 고친다.
- 저작자 표시는 1·2단계에서 `© OpenStreetMap · OpenFreeMap`, 3단계에서 `Natural Earth (public domain)`를 지도 구석에 둔다 (`lib/basemap.ts`).

## 검증

```bash
npm run typecheck        # tsc --noEmit
npm run test:contracts   # scripts/verify-contract.mjs
npm run build
```

### 계약 검사 (`npm run test:contracts`)

백엔드 Python 스키마를 읽어 만든 스냅샷 `scripts/backend-contract.json`으로 가공 fixture를 검사한다. 그래서 Python·API 없이 돈다. 보는 것: 응답 fixture 7개(ok, partial, insufficient, failed, unsupported, watch, act), 이력·서류·기억 fixture, SSE 해석, 단계 이름 일치, 화물 표 칸, 대화 목록 타입, 로그인 복귀 주소. 백엔드 `schemas/*`가 바뀌면 스냅샷도 다시 만든다 (`AgentResponse` 필드가 바뀌면 이 검사가 먼저 깨진다).

### e2e (`npm run test:e2e`, `scripts/verify.mjs`)

Playwright로 화면, 상호작용, 접근성(axe 태그 `wcag2a`, `wcag2aa`, `wcag21aa`)을 검사한다. 설치된 Google Chrome이 필요하다 (`PLAYWRIGHT_CHANNEL`로 채널을 바꾼다). 서버를 먼저 띄우고 다른 터미널에서 돌린다.

```bash
# 데모 모드 서버 (NEXT_PUBLIC_API_BASE는 비운다)
npm run dev -- --port 3100
# 다른 터미널
MARVIA_TEST_URL=http://localhost:3100 npm run test:e2e
# 접근성 검사와 스크린샷 없이 상호작용만
node scripts/verify.mjs --interactions
```

주소는 `localhost`로 쓴다. `127.0.0.1`이면 Next 개발 서버가 화면 스크립트를 막아 첫 단계에서 시간 초과가 난다 (`scripts/verify.mjs` 머리 주석). `MARVIA_TEST_URL`의 기본값도 `http://localhost:3100`이다.

실제 모드 검사(SSE 단계 표시, 일반 사용자 메뉴, `/api/chat` 대체 경로, 오류 이벤트, 이력 `available:false`)는 가짜 API 주소로 빌드한 서버를 하나 더 띄워서 본다. 가짜 API(기본 `:3199`, `MARVIA_MOCK_API_PORT`)는 검사 스크립트가 직접 띄운다.

```bash
NEXT_PUBLIC_API_BASE=http://127.0.0.1:3199 npm run build && npm run start -- --port 3101
# 다른 터미널
MARVIA_TEST_URL=http://localhost:3100 MARVIA_LIVE_TEST_URL=http://127.0.0.1:3101 npm run test:e2e
```

| 항목 | 내용 |
| --- | --- |
| SKIP 규칙 | `MARVIA_LIVE_TEST_URL`이 없으면 실제 모드 검사는 SKIP으로 나오고 통과로 세지 않는다 |
| 외부 요청 | 브라우저 검사는 외부 HTTP를 막고 기록한다. 지도 바탕 `tiles.openfreemap.org` 하나만 허용한다. 못 불러와도 지도는 해안선으로 되돌아가므로 검사가 네트워크에 묶이지 않는다 |
| 화면 폭 | 1440px, 375px로 검사하고 캡처한다. 1024, 768, 390px는 가로 넘침만 본다 |
| 탭 | 설정 탭 4개, 관리 탭 2개를 하나씩 열어 본다 |
| 캡처 | `screenshots/`에 쓴다 (git 제외) |

자동 접근성 검사를 통과했다고 모든 접근성이 보장되지는 않는다.

## 폴더 구조

```text
app/                   App Router 페이지 9개, 공통 layout, globals.css(토큰과 공통 규칙), icon.svg
app/styles/            화면별 CSS 14개 (layout.tsx가 globals.css 뒤에 불러온다)
components/            화면 컴포넌트 (아래 표)
lib/api.ts             요청 함수 전부와 데모 모드 함수 (isLive로 나뉜다)
lib/types.ts           백엔드 Pydantic 계약을 옮긴 타입
lib/auth.ts            Supabase 로그인
lib/basemap.ts         지도 바탕 세 단계
lib/format.ts          KST 날짜, B/L 가리기, 표시 라벨(verdictLabels 등)
lib/progress.ts        서버 처리 단계 이름·라벨과 SSE 해석 (docs/specs/chat-progress.md)
lib/composer.ts        다른 카드에서 입력창으로 돌아가는 통로
lib/evidenceTypes.ts   근거 종류
lib/shipList.ts        선박 목록 보조
lib/watchVessel.ts     B/L 없이 배 지켜보기
lib/fixtures/          데모 응답 7개(ok, partial, insufficient, failed, unsupported, watch, act)와 화면별 가공 데이터
                       (demo, history, document, memory, settings, metrics, admin, watch-map, geography)
public/basemap/        미리 구운 지도 타일 (확대 3~8, webp, meta.json, sea.webp)
public/maplibre/       MapLibre 워커 사본 (git 제외, predev/prebuild가 만든다)
public/brand/          로고
public/about/          소개 페이지 캡처 이미지
public/landing/        소개 페이지 사진 (출처는 public/landing/README.md)
scripts/               verify.mjs, verify-contract.mjs, backend-contract.json, bake-basemap.mjs, copy-maplibre-worker.mjs
screenshots/           verify.mjs가 찍는 캡처 (git 제외)
DESIGN.md              디자인 규칙과 이유
THIRD_PARTY.md         지도·글꼴 출처와 라이선스
```

화면이 쓰는 컴포넌트 (`components/`):

| 묶음 | 파일 |
| --- | --- |
| 틀·세션 | `AppProvider`(세션·로그인·사용량·대화 상태), `Shell`(사이드바·상단 줄·로그인/정지/회원 정보 관문), `Drawer`, `Shared`, `OperatorOnly` |
| 대화 | `ChatBar`(입력창), `ConversationList`, `ChatCargoTable`, `ChatVesselTable`, `ChatCandidateChips`, `ChatMiniMap`, `ConversationEvidence`, `EvidencePopover`, `WatchOfferAction` |
| 화물 결과 | `VerdictCard`, `VesselCard`, `EtaCompare`, `MapPanel`, `CustomsTimeline`, `CustomsDetailTable`, `EvidenceCards`, `CandidatePicker`, `FailureBanner` |
| 선박 | `VesselList`, `VesselDetail`, `VesselMap` |
| 지켜보기·현황 | `WatchMap`, `WatchToggle`, `WatchedVessels`, `WatchVesselButton`, `CargoSheet` |
| 소개·약관 | `IntroContent`, `LegalLinks`, `LegalModal` |
| 설정·계정 | `SettingsPage`, `ProfileForm`, `HistoryTable`, `MemoryPanel`, `KakaoPanel`, `AccountPanel`, `LoginScreen` |
| 운영 | `AdminPage`, `CustomerActions`(고객 한 명의 수정·정지·탈퇴·가린 정보 보기), `MetricsPage` |

`TopBar`, `AskPanel`, `DocumentPanel`(옛 조회 폼과 그 서류 확인 화면)은 파일만 남아 있고 어느 페이지에서도 불러오지 않는다.

## fixture 고치기

1. 응답은 `lib/fixtures/{status}.json`에서 고친다. `watch.json`, `act.json`은 status가 `ok`인 추가 예시다.
2. 예시 입력값, 예시 라벨, 부산 기준 좌표는 `demo.json`에서 고친다.
3. 이력 요약은 `history.json`에 더한다. `request_id`는 재생할 응답의 `trace_id`와 같아야 한다.
4. 예시를 더하면 `lib/api.ts`의 응답 목록에도 등록한다.
5. 다른 화면용 fixture에서 확인하지 않은 값은 null이나 빈 배열로 둔다.
6. `npm run test:contracts`와 `npm run build`로 계약과 타입을 확인한다.
