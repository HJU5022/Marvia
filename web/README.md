# Marvia frontend

B/L 하나로 내 화물이 제때 오는지 판정하고, 왜 그런지 근거까지 보여주는 프론트엔드입니다.
**Next.js App Router + TypeScript · 모든 화물 데이터는 로컬 fixture · 백엔드/LLM 연결 없음.**

## 바로 실행

Node.js **20.9 이상**과 npm이 필요합니다. ZIP을 풀고 프로젝트 폴더에서 실행하세요.

```bash
npm install
npm run dev
```

브라우저에서 <http://localhost:3000>을 엽니다. 키, `.env`, Docker, Python, 원본 프로젝트가 필요 없습니다. 첫 실행은 정상 예시 화물을 자동으로 보여줍니다. 의존성 설치 후 폰트와 지도도 로컬 자산으로 동작합니다.

프로덕션 확인:

```bash
npm run build
npm start
```

`npm ci`로 package-lock.json의 정확한 의존성을 재설치할 수도 있습니다.

## 화면

| 주소 | 화면 |
| --- | --- |
| `/` | 내 화물: 5개 status, 3개 verdict, 후보 선택, 근거 원본 펼치기, 후속 질문 |
| `/history` | 이력 필터, 저장된 fixture 판정 재생 |
| `/metrics` | 평가지표, 베이스라인 비교, 게이트, 실험 이력(미측정) |
| `/settings` | 규칙 임계값·우선순위 읽기 전용, 미확인 모델 설정, 알림 미연결 |
| `/about` | 제품 소개, 판정 의미, 아키텍처 그림, 지표 표 |

## 예시와 상태 전환

- 개발 모드(`npm run dev`): 입력 폼 아래 **DEV · 상태 미리보기**에서 5개 status 및 watch/act 예시를 전환합니다.
- 개발 모드 URL 예시: `/?fixture=ok`, `/?fixture=partial`, `/?fixture=insufficient`, `/?fixture=failed`, `/?fixture=unsupported`, `/?fixture=watch`, `/?fixture=act`.
- 프로덕션에서는 DEV 선택기와 URL override가 제거됩니다. 일반 예시 화물 메뉴와 아래 B/L은 계속 사용 가능합니다.
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

후보 선택: insufficient에서 첫 후보를 선택하거나 후보 미선택 상태로 항차·포워더 ETA를 입력하면 정상 예시로 이어집니다. 후속 질문은 질문에 관계없이 저장된 답변을 돌려주며 화면에 재생임을 표시합니다.

## 폴더 구조

```text
app/                   App Router 5개 페이지, 공통 layout, CSS 토큰
components/            SDD 5.13 컴포넌트 13개 + 세션/공통 UI
lib/types.ts           백엔드 Pydantic 직렬화 계약 그대로 옮긴 타입
lib/api.ts             요청·이력 함수 + 명시적으로 분리한 로컬 데모 접근 함수
lib/format.ts          KST 날짜, B/L 마스킹, 표시용 라벨
lib/fixtures/          7개 응답, 이력, 데모 입력, 설정, 지표, 로컬 지형 JSON
scripts/               계약 검사, Playwright 화면·접근성 검사
screenshots/           1440/375px 전체 화면 캡처와 검증 결과
DESIGN.md              디자인 방향과 이유
NOTES.md               스키마·문서 차이, 알려진 한계, 미확인 값
THIRD_PARTY.md         지도·폰트 출처와 라이선스
```

필수 컴포넌트: TopBar, VerdictCard, VesselCard, EtaCompare, MapPanel, CustomsTimeline, EvidenceCards, AskPanel, CandidatePicker, FailureBanner, HistoryTable, MetricsPage, SettingsPage.

## 백엔드 붙이기

**교체 위치는 `lib/api.ts`의 다음 함수 두 개입니다.** 현재 함수 본문 전체를 실제 fetch 구현으로 교체하면 컴포넌트의 요청·응답 타입은 유지됩니다.

| 함수 | 실제 endpoint | 형식 |
| --- | --- | --- |
| `getAgentResponse(req)` | `POST /api/agent` | JSON AgentRequest → AgentResponse |
| `getHistory(sessionId)` | `GET /api/history?session_id=` | `{items: HistoryItem[], available: boolean}` |

- C2에 존재하는 필드만 보내세요. status, fixture ID, 해수부 전용 조회 모드를 요청에 추가하지 않습니다.
- 날짜는 ISO 문자열, 위치는 `lng`·`navistat`, ETA는 별도 4개 필드를 사용합니다. `null`은 0이나 정상으로 바꾸지 않습니다.
- `available: false`는 이력이 빈 경우와 다릅니다. HistoryTable에서 구분해 렌더링합니다.
- `getPresentationData`, `selectFixture`, `getReplaySnapshot`, `getGeography`는 **로컬 UI/데모 보조 함수**입니다. 추가 백엔드 endpoint가 아닙니다. 화면 컴포넌트는 fixture를 직접 import하지 않습니다.
- 실제 history API에는 과거 응답 전체가 없습니다. **현재의 상세 재생은 로컬 스냅샷 기능**입니다. 실제 과거 결과를 재현하려면 팀에서 상세 endpoint를 추가하고 `getReplaySnapshot` 경로를 교체해야 합니다. 현재 두 endpoint만으로 가능한 것처럼 처리하지 않았습니다.
- 서비스용 session ID 발급, 인증, 실제 진행 이벤트, 알림 저장, 실제 평가 결과 매핑은 연동 작업에서 별도로 결정하세요.
- 서버 API 키를 브라우저 코드나 `NEXT_PUBLIC_*` 값에 넣지 마세요.

## fixture 수정

1. `lib/fixtures/{status}.json`을 수정합니다. `watch.json`, `act.json`은 status가 `ok`인 추가 예시입니다.
2. 입력값·선택기 라벨·부산 기준 좌표는 `demo.json`에서 수정합니다.
3. 이력 요약은 `history.json`에 추가합니다. `request_id`는 재생할 응답의 `trace_id`와 일치해야 합니다.
4. 시나리오를 추가한다면 `lib/api.ts`의 레지스트리에도 등록합니다.
5. `metrics.json`과 `settings.json`은 별도 화면 fixture입니다. 미확인 값은 null·빈 배열로 유지합니다. 평가 지표의 실제 출력 계약은 아직 제공되지 않아 NOTES.md에 기록했습니다.
6. `npm run test:contracts`와 빌드로 계약·타입을 확인합니다.

## 검증 재실행

```bash
npm run typecheck
npm run test:contracts
npm run build
```

스크린샷·상호작용·접근성 검사에는 Google Chrome이 필요합니다. 서버를 하나 띄운 뒤 다른 터미널에서 실행합니다.

```bash
npm run dev -- --hostname 127.0.0.1 --port 3100
# 다른 터미널:
npm run test:e2e
```

다른 포트를 사용하면 `MARVIA_TEST_URL=http://127.0.0.1:포트 npm run test:e2e`로 지정하세요. 브라우저 채널은 `PLAYWRIGHT_CHANNEL`로 변경할 수 있습니다. 이 변수들은 검사 스크립트용이며 `.env` 파일이 필요하지 않습니다.

- 계약 검사는 원본 Python 스키마를 읽어 생성한 `scripts/backend-contract.json` 스냅샷으로 수행합니다. 원본 저장소에 접근하지 않아도 실행됩니다.
- 브라우저 검사는 외부 HTTP를 차단하고 요청 발생 여부를 검사합니다.
- 스크린샷은 5개 status + watch/act + 기타 4개 페이지를 각각 1440px, 375px로 촬영합니다.
- 접근성 자동 검사는 axe WCAG 2/2.1 A·AA 기준입니다. 자동 검사만으로 모든 접근성이 보장되는 것은 아닙니다.

원본과의 차이 및 데모 범위는 **NOTES.md**를 먼저 확인해 주세요.
