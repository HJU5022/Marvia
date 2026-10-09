# Marvia frontend

B/L 하나로 내 화물이 제때 오는지 판정하고, 왜 그런지 근거까지 보여주는 프론트엔드입니다.
**Next.js 16 App Router + React 19 + TypeScript. 기본은 로컬 fixture 데모, `NEXT_PUBLIC_API_BASE`를 주면 실제 백엔드에 연결.**
배포는 Railway `marvia-web`입니다. Vercel은 쓰지 않습니다 (루트 README "배포").

하지 않는 것: 외부 API 직접 호출, 서버 비밀 키 보유. 화면은 백엔드 API(`lib/api.ts`)만 부릅니다.

## 바로 실행

Node.js **20.9 이상**과 npm이 필요합니다. 프로젝트 폴더에서 실행하세요.

```bash
npm install
npm run dev
```

브라우저에서 <http://localhost:3000>을 엽니다. 키, `.env`, Docker, Python이 필요 없습니다. 첫 실행은 정상 예시 화물을 자동으로 보여줍니다. 폰트와 지도는 로컬 자산으로 동작합니다. 예외는 지도 바탕 한 곳(OpenFreeMap, 아래 "지도 바탕")이고, 그 호스트에 못 닿으면 레포 안 자산으로 되돌아갑니다.

`npm run dev`와 `npm run build` 앞에서 `scripts/copy-maplibre-worker.mjs`가 MapLibre 워커 파일을 `node_modules`에서 `public/maplibre/`로 복사합니다(`predev`, `prebuild`). 이 폴더는 git에 올리지 않습니다.

프로덕션 확인:

```bash
npm run build
npm start
```

`npm ci`로 package-lock.json의 정확한 의존성을 재설치할 수도 있습니다.

## 화면

| 주소 | 화면 | 누가 |
| --- | --- | --- |
| `/` | 내 화물: 대화(왼쪽)와 상세(오른쪽). 결과가 없으면 대화만 가운데에 100:0, 결과가 생기면 40:60으로 나뉨. 5개 status, 3개 등급(순항·주의·긴급), 후보 선택, 근거 펼치기, 후속 질문, 서류 사진·PDF, 선박 자세히 보기 | 로그인 사용자 |
| `/watch` | 지켜보는 화물: 지켜보기를 켠 화물의 배 위치와 지나온 길을 한 지도에 (`GET /api/watch`) | 로그인 사용자 |
| `/cargo` | 화물 현황 표: 신용장·출항일 편집, 엑셀 내려받기 (`/api/cargo/sheet*`) | 로그인 사용자 |
| `/history` | 조회 이력 (설정의 "조회 이력" 탭과 같은 화면) | 로그인 사용자 |
| `/settings` | 탭 다섯: 회원 정보 · 조회 이력 · 기억한 화물 · 설정(판단 기준 읽기 전용, 카카오 알림 연결) · 계정과 이력(기록 삭제, 탈퇴) | 로그인 사용자 |
| `/settings/kakao` | 카카오 동의 뒤 돌아오는 곳. 연결을 마무리하고 `/settings?kakao=결과`로 보냄 | 로그인 사용자 |
| `/metrics` | 평가 지표 (`GET /api/metrics`) | 운영자만 (`OperatorOnly`) |
| `/admin` | 관리: 고객 관리(수정·정지·강제 탈퇴·가린 정보 보기), 운영자 관리 | 운영자만 |
| `/about` | 제품 소개 (로그인 전에도 보임) | 누구나 |

일반 사용자 사이드바는 새 대화와 대화 목록(`conversations`, 대화 화면 `/`)이 가운데에 있고, 아래 "화물" 묶음(감시 화물 `/watch`, 화물 현황 `/cargo`, 조회 이력 `/history`)과 Marvia 소개, 계정 메뉴가 있습니다. 운영자에게는 평가 지표와 관리가 더해집니다 (`components/Shell.tsx`, `GET /api/me`). 대화가 40:60으로 나뉘어도 대화 목록은 그대로 보이고, 사이드바를 접었거나 좁은 화면이면 대화 칸 왼쪽 위 단추가 목록 패널을 엽니다.

## 예시와 상태 전환 (데모 모드)

`NEXT_PUBLIC_API_BASE`가 없으면 데모 모드입니다. 서버가 없어 LLM도 없으므로, 입력 문장 속 예시 B/L만 알아봅니다 (`lib/api.ts demoChat`).

- 입력창 아래 예시 문장 칩을 누르면 입력창에 채워질 뿐 자동으로 보내지 않습니다. 데모 모드의 칩은 `MRVDEMO1101 화물 괜찮아?`, `MRVDEMO1107 지금 조치해야 해?`, `중국에서 부산 들어오는 배 보여줘`입니다.
- 개발 모드(`npm run dev`) URL 예시: `/?fixture=ok`, `/?fixture=partial`, `/?fixture=insufficient`, `/?fixture=failed`, `/?fixture=unsupported`, `/?fixture=watch`, `/?fixture=act`. 프로덕션 빌드에서는 이 URL override가 제거됩니다. (예전 "DEV · 상태 미리보기" 선택기는 `TopBar.tsx`에만 남아 있고 화면에는 없습니다.)
- 모든 예시는 MASTER입니다. 저장된 날짜·구분과 다르게 조회하면 조건 불일치 안내가 나옵니다. **fixture를 새로운 입력에 맞춰 임의로 재판정하지 않습니다.**

| 예시 B/L (가공) | 판매 예정일 | 응답 |
| --- | --- | --- |
| MRVDEMO1101 | 2026-10-25 | ok / fine |
| MRVDEMO1102 | 2026-10-25 | insufficient / null |
| MRVDEMO1103 | 2026-10-25 | partial / null / stale 위치 |
| MRVDEMO1104 | 2026-10-25 | failed / null |
| MRVDEMO1105 | 2026-10-25 | unsupported / null |
| MRVDEMO1106 | 2026-10-25 | ok / watch / stale 위치 |
| MRVDEMO1107 | 2026-10-20 | ok / act |

(`verdict` 값은 `fine`, `watch`, `act`이고 화면 이름은 순항, 주의, 긴급입니다. `lib/format.ts verdictLabels`.)

후보 선택: insufficient에서 첫 후보를 선택하거나 후보 미선택 상태로 항차·포워더 ETA를 입력하면 정상 예시로 이어집니다. 후속 질문은 질문에 관계없이 저장된 답변을 돌려주며 화면에 재생임을 표시합니다.

## 폴더 구조

```text
app/                   App Router 페이지 (/, /watch, /cargo, /history, /settings(+/kakao), /metrics, /admin, /about),
                       공통 layout, globals.css(토큰 + 공통 규칙), icon.svg
app/styles/            화면별 CSS 열네 파일: admin, brand, cargo-sheet, chat, compare-vessel, detail, document, entry, evidence,
                       landing, metrics, settings, sidebar, watch (layout.tsx가 globals.css 뒤에 불러온다. 뒤 파일이 앞의 같은 선택자를 덮는다)
components/            화면 컴포넌트 47개 (아래 표)
lib/types.ts           백엔드 Pydantic 직렬화 계약을 옮긴 타입
lib/api.ts             요청 함수 전부 + 로컬 데모 접근 함수 (isLive로 분기)
lib/auth.ts            Supabase 로그인
lib/basemap.ts         지도 바탕 세 단계 (아래 "지도 바탕")
lib/format.ts          KST 날짜, B/L 마스킹, 표시용 라벨(verdictLabels 등)
lib/evidenceTypes.ts, shipList.ts, watchVessel.ts  근거 종류, 선박 목록, 선박 지켜보기 보조
lib/progress.ts        서버 처리 단계 이름·라벨과 SSE 해석 (docs/specs/chat-progress.md)
lib/composer.ts        다른 카드에서 AI 입력창으로 돌아가는 통로
lib/fixtures/          데모 응답(ok, partial, insufficient, failed, unsupported, watch, act), history, demo, document,
                       memory, settings, metrics, admin, watch, watch-map, geography(Natural Earth 해안선)
public/basemap/        미리 구운 지도 타일 (확대 3~8, webp, meta.json, sea.webp)
public/maplibre/       MapLibre 워커 사본 (git 제외, predev/prebuild가 만든다)
public/brand, about/   로고, 소개 페이지 캡처 이미지
scripts/               verify.mjs, verify-contract.mjs, bake-basemap.mjs, copy-maplibre-worker.mjs, backend-contract.json
screenshots/           verify.mjs가 찍는 캡처 (git 제외, 로컬에서 만들어진다)
DESIGN.md              디자인 방향과 이유
THIRD_PARTY.md         지도·폰트 출처와 라이선스
```

컴포넌트 (`components/`):

| 묶음 | 파일 |
| --- | --- |
| 틀·세션 | `AppProvider`(세션·로그인·사용량·대화 상태), `Shell`(레일·상단바·로그인/정지/회원정보 관문), `Drawer`, `Shared`, `OperatorOnly` |
| 대화 | `ChatBar`(입력창, `POST /api/chat/stream`), `ConversationList`, `ChatCargoTable`, `ChatVesselTable`, `ChatCandidateChips`, `ChatMiniMap`, `ConversationEvidence`, `EvidencePopover`, `WatchOfferAction` |
| 화물 결과 | `VerdictCard`, `VesselCard`, `EtaCompare`, `MapPanel`, `CustomsTimeline`, `CustomsDetailTable`, `EvidenceCards`, `CandidatePicker`, `FailureBanner` |
| 선박 | `VesselList`, `VesselDetail`, `VesselMap` |
| 서류 | `DocumentPanel`(사진·PDF 확인 화면) |
| 지켜보기·현황 | `WatchMap`, `WatchToggle`, `CargoSheet` |
| 소개·약관 | `IntroContent`, `LegalLinks`, `LegalModal` |
| 설정·계정 | `SettingsPage`, `ProfileForm`, `HistoryTable`, `MemoryPanel`, `KakaoPanel`, `AccountPanel`, `LoginScreen` |
| 운영 | `AdminPage`, `CustomerActions`(고객 한 명에 대한 수정·정지·탈퇴·가린 정보 보기), `MetricsPage` |
| 쓰지 않음 | `TopBar`, `AskPanel` (옛 입력 폼. 어디서도 불러오지 않지만 지우지 않았다) |

## 화면 틀과 스타일

- 토큰은 `app/globals.css`의 `:root`입니다. 바탕 연회색 `#F2F4F6`, 카드 흰색, 파랑 `#2962F5`(hover `#1D4FD7`)는 누를 수 있는 것에만, 신호등 색은 판정 등급에만 씁니다. 글자 크기는 14·16·20·26 네 단계입니다. 자세한 것은 DESIGN.md.
- `globals.css` 맨 끝 "Marvia 토스형 프레임" 구역이 옛 규칙(Ocean)을 덮고, 화면별 규칙은 `app/styles/*.css`가 뒤에서 덮습니다.
- 내 화물 화면(`app/page.tsx`)은 대화 칸 `clamp(380px, 40%, 720px)` + 상세 칸입니다 (`styles/chat.css`). 선박 표(열이 많음)일 때는 대화 칸이 `clamp(360px, 32%, 560px)`로 좁아집니다. 이 화면에서만 페이지 전체가 아니라 안쪽 칸이 스크롤합니다(`body[data-fit]`).
- 900px 이하에서는 상세가 아래에서 올라오는 시트가 되고(손잡이 줄만 보이게 접힘), 입력창을 누르면 시트가 접힙니다. 700px 이하에서는 사이드바가 위 띠로 바뀌어 틀을 세로로 쌓습니다 (`styles/chat.css`).

## 지도 바탕

네 지도(`MapPanel`, `ChatMiniMap`, `VesselMap`, `WatchMap`)가 `lib/basemap.ts` 한 곳을 씁니다. Leaflet 지도 밑에 아래 세 단계 중 되는 첫 단계를 깝니다. 배·부산항·경로·클러스터·말풍선은 모든 단계에서 Leaflet 것입니다.

1. **WebGL OpenFreeMap 벡터 지도** (`https://tiles.openfreemap.org/styles/positron`, MapLibre). 땅·바다 색은 불러온 뒤 `--land`, `--sea` 토큰으로 바꿉니다. 스타일이 8초 안에 안 오거나, 스타일이 온 뒤 8초 안에 타일이 한 장도 안 오거나, WebGL이 없으면 다음 단계로 갑니다.
2. **미리 구운 타일** `public/basemap/{z}/{x}/{y}.webp` (정적, 같은 모양의 래스터). WebGL이 없는 PC(발표장 등)를 위한 단계입니다. `public/basemap/meta.json`의 `tiles` 목록에 있는 것만 요청합니다. 구역은 위도 10~50, 경도 100~155이고 확대 3~7, 확대 8은 위도 28~40, 경도 118~136입니다(`meta.json`). 다시 굽기: `node scripts/bake-basemap.mjs`. Playwright의 Chrome(WebGL)과 `sharp`가 필요하고(둘 다 이미 `node_modules`에 있다), `lib/basemap.ts tune()`과 같은 손질을 스크립트 안에 똑같이 적었으니 한쪽을 고치면 다른 쪽도 고칩니다.
3. **Natural Earth 해안선** (`lib/fixtures/geography.json`, 손으로 쓴 이름표). 오프라인에서도 되는 마지막 단계입니다.

외부로 나가는 주소는 `tiles.openfreemap.org` 하나뿐입니다. 저작자 표시 `© OpenStreetMap · OpenFreeMap`를 지도 구석에 둡니다.

## 백엔드 붙이기 (실제 모드)

`NEXT_PUBLIC_API_BASE`가 있으면 실제 모드, 없으면 위의 fixture 데모 모드입니다. 값은 빌드할 때 들어가므로 바꾸면 dev 서버를 다시 켭니다.

값은 `web/.env`에 둡니다. `cp .env.example .env` 뒤 채우면 아래처럼 명령에 붙이지 않고 `npm run dev`만 해도 됩니다. `web/.env`는 커밋하지 않습니다.

```bash
# 레포 루트: 키 없이 백엔드 데모 13건 (루트 README "키 없이 데모")
docker compose up -d --build
docker compose exec api python -m scripts.demo.make_demo

# web/
NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev
```

- 실제 모드에서 입력창에 백엔드 데모 B/L(라이브 시연 10건 DEMOQD2610001~DEMOQD2610010 형태, 평가셋 3건 TESTBL01 정상·TESTBL04 되묻기·TESTBL26 판정 보류)을 문장에 넣어 조회합니다. 판매 예정일은 비우거나 make_demo가 알려 준 날을 넣습니다. (`lib/api.ts liveExamples`가 이 목록이고 지금은 쓰지 않는 `TopBar`만 읽습니다.)
- 백엔드 CORS `ALLOWED_ORIGINS`에 화면 주소(기본 http://localhost:3000)가 있어야 합니다.
- 세션 ID는 브라우저마다 만들어 localStorage에 둡니다. 대화 저장이 꺼진 환경(로그아웃, 로그인 기능 꺼짐, 서버가 401/503)에서는 탭 sessionStorage로 대화를 이어 갑니다.
- 로그인은 아래 "로그인 (G3)" 절을 봅니다.
- 이력 행의 상세 다시 보기는 실제 모드에서 동작하지 않습니다. GET /api/history는 요약만 주고, 새로 조회해서 과거 결과인 척하지 않습니다.

주요 함수와 endpoint (`lib/api.ts`):

| 함수 | 실제 endpoint |
| --- | --- |
| `sendChatStream` / `sendChat` | `POST /api/chat/stream` (SSE) / `POST /api/chat` (옛 서버 대체) |
| `getAgentResponse` | `POST /api/agent` (정해진 칸 입력, 되묻기 답, 다시 조회) |
| `getHistory`, `deleteMyHistory` | `GET /api/history?session_id=`, `DELETE /api/history` |
| `getUsage` | `GET /api/usage` |
| `readDocument`, `saveDocumentFacts` | `POST /api/document`, `POST /api/memory/document-facts` |
| `getVesselDetail` | `GET /api/vessels/detail` |
| `listConversations`, `getConversation`, `deleteConversation` | `/api/conversations*` |
| `getMemory`, `deleteAllMemory`, `deleteMemoryItem` | `/api/memory*` |
| `getWatchList`, `getWatchState`, `setWatch`, `getWatchChanges`, `markWatchChangesSeen` | `/api/watch*`, `/api/cargo/watch*` |
| `getCargoSheet`, `saveCargoLc`, `saveCargoDeparted`, `downloadCargoSheet` | `/api/cargo/sheet*` |
| `getKakaoStatus`, `connectKakao`, `finishKakaoLink`, `sendKakaoTest`, `unlinkKakao` | `/api/kakao/*` |
| `getProfile`, `saveProfile` | `GET`, `PUT /api/profile` |
| `getMe`, `getCustomers`, `getOperators`, `grantOperator`, `revokeOperator`, `unmaskCustomer`, `updateCustomer`, `deleteCustomer`, `suspendCustomer`, `resumeCustomer`, `getAdminActions` | `/api/me`, `/api/admin/*` |
| `getMetrics` | `GET /api/metrics` (운영자) |
| `deleteMyAccount` | `DELETE /api/account` |

- C2에 존재하는 필드만 보냅니다. 빈 날짜·빈 문자열은 null로 바꿔 보냅니다(빈 문자열 날짜는 422).
- 날짜는 ISO 문자열, 위치는 `lng`·`navistat`, ETA는 별도 4개 필드를 사용합니다. `null`은 0이나 정상으로 바꾸지 않습니다.
- `available: false`는 이력이 빈 경우와 다릅니다. 이력을 못 읽으면 화면을 죽이지 않고 이 값으로 표시합니다.
- `getPresentationData`, `selectFixture`, `getReplaySnapshot`, `getGeography`는 로컬 UI/데모 보조 함수입니다. 백엔드 endpoint가 아닙니다.
- 서버 API 키를 브라우저 코드나 `NEXT_PUBLIC_*` 값에 넣지 마세요.

## 로그인 (G3)

백엔드가 `SUPABASE_URL`로 로그인을 켜면 화면도 아래 두 값을 넣어 켭니다. 둘 다 브라우저에 보여도 되는 값입니다. secret 키는 절대 넣지 않습니다.

```bash
NEXT_PUBLIC_API_BASE=http://localhost:8000 NEXT_PUBLIC_SUPABASE_URL=https://<프로젝트>.supabase.co NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<publishable 키> npm run dev
```

- 값이 없으면 로그인이 꺼지고 세션 ID로만 돕니다. 채점용 compose(로그인 꺼짐)와 같습니다.
- 켜져 있으면 로그인 전에는 조회 화면 대신 로그인 화면이 나옵니다. 소개 페이지는 예외입니다.
- 로그인한 뒤 회원 정보(이름·전화·주소)가 없으면 입력 화면이 먼저 나옵니다 (`GET /api/me`의 `profile_complete`, docs/specs/user-profile.md). 운영자가 정지한 계정은 정지 안내만 보입니다.
- 요청마다 `Authorization: Bearer <JWT>`를 붙입니다. 백엔드는 ES256 공개키로 확인합니다 (backend/app/auth.py).
- Supabase 대시보드에서 Google 공급자를 켜고, Redirect URL에 화면 주소(예: http://localhost:3000/**)를 넣어야 돌아올 수 있습니다.
- 설정의 "계정과 이력" 탭에서 내 기록 삭제(DELETE /api/history)와 회원 탈퇴(DELETE /api/account)를 합니다.

## fixture 수정

1. `lib/fixtures/{status}.json`을 수정합니다. `watch.json`, `act.json`은 status가 `ok`인 추가 예시입니다.
2. 입력값·선택기 라벨·부산 기준 좌표는 `demo.json`에서 수정합니다.
3. 이력 요약은 `history.json`에 추가합니다. `request_id`는 재생할 응답의 `trace_id`와 일치해야 합니다.
4. 시나리오를 추가한다면 `lib/api.ts`의 레지스트리에도 등록합니다.
5. `metrics.json`, `settings.json`, `admin.json`, `memory.json`, `watch-map.json`은 별도 화면 fixture입니다. 미확인 값은 null·빈 배열로 유지합니다.
6. `npm run test:contracts`와 빌드로 계약·타입을 확인합니다.

## 검증 재실행

```bash
npm run typecheck
npm run test:contracts
npm run build
```

`test:contracts`는 가공 fixture 7개와 이력·서류·기억 fixture, SSE 해석, 단계 이름 일치, 화물 표 칸, 대화 목록 타입, 로그인 복귀 주소를 봅니다.

### e2e (`scripts/verify.mjs`)

Playwright로 화면·상호작용·접근성(axe WCAG 2/2.1 A·AA)을 검사합니다. 설치된 Google Chrome이 필요합니다 (`PLAYWRIGHT_CHANNEL`로 채널 변경). 서버를 하나 띄운 뒤 다른 터미널에서 실행합니다.

```bash
# 데모 모드 (기본 http://127.0.0.1:3100)
npm run dev -- --hostname 127.0.0.1 --port 3100
# 다른 터미널:
npm run test:e2e
# 접근성·스크린샷 없이 상호작용만 빠르게:
node scripts/verify.mjs --interactions
```

**실제 모드(live)** 검사(SSE 단계 표시, 일반 사용자 메뉴, 옛 서버 대체, 오류 이벤트, 이력 `available:false`)는 가짜 API 주소로 빌드한 서버를 하나 더 띄워서 봅니다. 가짜 API(기본 :3199, `MARVIA_MOCK_API_PORT`)는 검사 스크립트가 직접 띄웁니다.

```bash
NEXT_PUBLIC_API_BASE=http://127.0.0.1:3199 npm run build && npm run start -- --port 3101
# 다른 터미널:
MARVIA_LIVE_TEST_URL=http://127.0.0.1:3101 npm run test:e2e
```

- `MARVIA_LIVE_TEST_URL`이 없으면 실제 모드 검사는 SKIP으로 표시됩니다(통과로 세지 않음).
- 다른 포트를 쓰면 `MARVIA_TEST_URL=http://127.0.0.1:포트 npm run test:e2e`로 지정합니다.
- 브라우저 검사는 외부 HTTP를 차단하고 요청 발생 여부를 기록합니다. 예외로 지도 바탕 호스트 `tiles.openfreemap.org` 하나만 허용합니다(못 불러와도 지도는 해안선으로 되돌아가야 하므로 검사가 네트워크에 묶이지 않습니다).
- 스크린샷은 `screenshots/`에 쓰입니다(git 제외). 1440px, 375px로 찍고, 1024/768/390px는 가로 넘침을 검사합니다.
- 접근성 자동 검사만으로 모든 접근성이 보장되는 것은 아닙니다.

### 계약 검사 (`scripts/verify-contract.mjs`)

`npm run test:contracts`. 원본 Python 스키마를 읽어 생성한 `scripts/backend-contract.json` 스냅샷으로 가공 fixture를 검사하므로 원본 저장소·Python·API 없이 실행됩니다. 백엔드 `schemas/*`가 바뀌면 이 스냅샷도 다시 만들어야 합니다 (`AgentResponse`의 필드가 바뀌면 이 검사가 먼저 깨집니다).

