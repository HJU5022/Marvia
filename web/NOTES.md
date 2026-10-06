# 원본과 계약 차이 / 구현 판단

초판 기준일: 2026-09-28. 현행화: 2026-10-06 (코드 기준, 아래 "10-06 현행화"). 이 문서는 인계용이며 원본 문서를 변경하지 않습니다.
표의 "초판" 칸은 9/28 인계 당시 판단이고, "10-06" 칸이 지금 코드입니다. 10-06 칸이 비어 있으면 초판 판단이 그대로 맞는지 이번에 다시 확인하지 않은 것입니다.

## 백엔드 코드가 기준인 항목

| 위치 | 목업·문서 | 실제 코드 / 구현 |
| --- | --- | --- |
| PRD 7절·SDD 5.13 화면 설명 | 일부 status만 설명 | `ok / partial / insufficient / failed / unsupported` 모두 분기. status와 verdict를 별개로 처리 |
| 목업 README·선박 카드 | position.lon, navstat | `lng`, `navistat` 사용 |
| 목업 README·ETA | sources[], adopted, priority_note | 실제 `ais_eta / mof_eta / calc_eta / trusted_eta / distance_nm`. 채택 사유는 `conflicts[].why`가 있을 때만 표시 |
| 목업 통관 필드 | customs.stage | 실제 `stage_name`, `stage_code`, `plain_explanation`, `next_stage`, `needs_broker`, `history`. 10-06: 처리 이력 원문은 `customs_detail`로 따로 온다 (`CustomsDetailTable`, docs/specs/customs-detail.md) |
| 목업 판정 주체 | rule + llm | `decided_by`는 `rule / llm / null`. 합성 enum을 만들지 않음 |
| 판정 이름 | fine / watch / act | 10-06 화면 이름은 순항 / 주의 / 긴급 (`lib/format.ts verdictLabels`, 서버 `VERDICT_LABEL`). 계약 값(`fine`, `watch`, `act`)은 그대로 |
| 목업 실패 | partial이면 watch, 캐시·재시도·로그 | 라우터는 partial에 null verdict를 반환할 수 있음. 재시도 횟수·이벤트 로그 필드 없음. 임의로 만들지 않음 |
| 실패 화면 버튼 | 해수부 기록만으로 판정 보기 | 요청에 이런 모드 필드가 없음. **해수부 근거만 보기**라는 로컬 필터로 구현. 재판정이라고 표시하지 않음 |
| 목업 설정 | 저장 버튼, 모델 변경, 카카오 연결 | 판단 기준은 SDD 5.13대로 읽기 전용(설정 탭). 10-06: 카카오 알림 연결은 `/api/kakao/*`가 생겨 실제로 동작한다(`KakaoPanel`, 연결·테스트 발송·해제). 모델 변경·저장 버튼은 여전히 없다 |
| 목업 조회 이력 | 배열, 선박·MMSI·여유일·재시도·링크·응답 재현 | 실제 `{items, available}`. HistoryItem은 `request_id, bl_masked, status, verdict, vessel_match, decided_by, model(항상 null, DB 칸은 018에서 지움), trace_id, created_at, reason`. 선박·MMSI·여유일 칸은 없다. `reason`은 코드가 만든 한 줄 이유 |
| E11 | 행에서 과거 판정 열기 | GET /api/history는 전체 응답을 안 돌려줌. 데모 모드는 fixture trace/request ID에 대응하는 **별도 로컬 스냅샷**을 재생. 실제 모드는 재생하지 않는다(새 POST를 과거 결과라고 위장하지 않음) |
| 초판 README의 "LLM 판정·REPLAY_MODE 미구현" 설명 | 미구현 | 구현돼 있다 (루트 README, 10-06). 이 항목의 "문서 현행화 안 함"은 해소 |
| E1 / E10 | Vercel 배포 URL | 10-06: 배포는 Railway `marvia-web`이다. Vercel은 쓰지 않는다 (10-05 결정, 루트 README "배포") |

## 모르는 값과 빈 값

- (초판) `AgentResponse.vessel`은 스키마에 있지만 읽은 `routers/agent.py`에서는 값 조립이 보이지 않았습니다. **10-06: 지금은 `_vessel_info`가 채웁니다.** 실제 연동 시에도 null을 정상 처리하며 확정된 단일 후보가 있으면 후보의 확인된 식별자만 표시합니다.
- IMO·호출부호·항차·장치장을 추측하지 않아 해당 예시 필드는 null입니다. 후보에도 확인하지 못한 IMO는 null입니다. 통관 이력의 코드가 없으면 빈 문자열입니다.
- `position`에는 AIS 목적지 필드가 없습니다. 목적지는 후보의 `dest`에 있을 때만 표시합니다. `freshness` unknown은 정상 수신으로 표현하지 않습니다.
- 트레이스 ID는 제공하지만 실제 Langfuse 프로젝트·URL은 모릅니다. ID만 표시하고 동작하지 않는 링크를 만들지 않았습니다.
- 평가지표: (초판) 평가 결과 계약을 몰라 fixture를 프론트 표시용으로만 만들었고 점수·게이트·개수·갱신일은 null이었습니다. **10-06: `GET /api/metrics`가 `evals/results/*.json`의 구성별 최신 파일을 읽어 화면 모양으로 돌려줍니다** (`backend/app/services/metrics.py`, 운영자 전용). 데모 모드의 `lib/fixtures/metrics.json`은 여전히 표시용 가공값이고 실제 결과 숫자가 아닙니다. 실행하지 않은 값은 서버가 null로 내보내고 화면은 "미측정"으로 둡니다.
- 모델명, judge 모델, 프롬프트 버전, 토큰 상한, 비용 상한, 외부 서비스 접속 상태는 화면이 확정하지 않습니다. null 또는 미연결로 표시합니다. 서버 환경변수·API 키는 읽지 않았습니다.

## fixture 데모의 경계 (NEXT_PUBLIC_API_BASE가 없을 때)

- 모든 B/L·선박·좌표·시각은 가공값입니다. `990…` MMSI는 시연용이며 실제 선박과 매칭하지 않습니다. 이 모드에는 API·LLM 호출이 없습니다. (실제 모드에서는 `lib/api.ts`가 백엔드를 부릅니다. 초판의 "서버 연결 코드는 없습니다"는 틀려졌습니다.)
- 고정된 예시 B/L은 **그 예시에 저장된 판매 예정일과 M/H 구분**으로만 조회합니다. 날짜·구분을 바꿔도 가공 판정을 재계산하지 않습니다. 다른 조건을 넣으면 안내 오류가 나며, 화면에는 이전 결과임을 표시합니다.
- 데모 대화(`demoChat`)는 LLM 없이 문장 속 `MRVDEMO11xx`만 알아보고, 배 검색은 가공 예시 표를 돌려줍니다.
- 되묻기는 첫 후보 선택, 또는 후보를 선택하지 않고 항차·ETA 입력 시 저장된 정상 결과로 이어지는 시뮬레이션입니다. 두 번째 후보는 확정되지 않습니다. 실제 식별 알고리즘이 아닙니다.
- 후속 질문은 session/B/L과 질문을 함수에 전달하지만 답변 생성은 하지 않습니다. 저장된 답변을 재생한다는 문구와 반환 근거를 함께 표시합니다.
- 진행 단계 표시: 실제 모드는 서버가 SSE로 보낸 단계만 그립니다. 데모 모드는 단계를 지어내지 않고 "체험 모드에서는 진행 단계를 보여 드리지 않아요"와 경과 시간만 보입니다 (`ChatBar`). 초판의 "데모 타이머"는 10-02에 없앴습니다.
- 지도 바탕: (초판) Leaflet + 번들 Natural Earth 지형만 쓰고 외부 타일 서버를 부르지 않았습니다. **10-06: 세 단계입니다.** WebGL OpenFreeMap 벡터 지도 → 미리 구운 타일(`public/basemap`) → Natural Earth 해안선 (`lib/basemap.ts`, web/README.md "지도 바탕"). 외부로 나가는 주소는 `tiles.openfreemap.org` 하나이고, 못 닿으면 레포 안 자산으로 되돌아갑니다. 부산항 좌표는 읽은 rules.md의 `busan_ref` 값을 demo fixture에 저장했습니다. 점선은 목적항 방향 안내이며 실측 항적·항로 예측이 아닙니다.
- 설정 규칙 수치는 `skills/ais-reliability/rules.md`의 읽기 전용 스냅샷(`lib/fixtures/settings.json`)입니다. 화면에서 수정하거나 저장하지 않습니다.

## 10-02 화면 개편 (Ocean, AI 입력 중심) 기록

기준: 바탕화면 `Marvia_Claude_구현작업서.md`. 기능·계약은 그대로 두고 배치와 색을 바꿨다. 색과 배치는 10-06에 토스형으로 다시 바뀌었으나(DESIGN.md), 아래 동작 판단은 그대로 유효하다.

- **대기 표시**: 예전 화면은 0.35초·0.7초 타이머로 "이해 → 조회 → 정리" 단계를 넘겼다(작업 리스트 E3). 실제 진행과 무관해서 지웠고, 서버가 실제 단계에 들어갈 때 보내는 SSE 소식(POST /api/chat/stream)만 표시한다. 정운 결정(10-02), 근거는 가이드 8-3 즉각 피드백과 특강 "스트리밍 응답 처리". Spec: `docs/specs/chat-progress.md`
- 정해진 칸 조회(POST /api/agent: 되묻기 답, 다시 조회)와 키 없는 데모 모드는 단계 소식이 없다. 기다림과 경과 시간만 보인다. 단계를 지어내지 않는다
- 새 통로가 없는 서버(404·405)나 응답 전 연결 실패면 POST /api/chat으로 한 번 대신 보낸다. 소식을 받은 뒤 끊기면 다시 보내지 않는다(유료 호출 중복)
- **예시 문장**은 입력창에 채우기만 한다. 예전에는 누르면 바로 보냈다. 실제 모드에서 의도치 않은 유료 호출을 막기 위해서다
- **선박 자세히 보기**는 표 행 안 펼침에서 오른쪽 드로어로 옮겼다. 보이는 칸은 같다(AIS 6칸, 해수부 일정 5칸, 관제 이벤트, 부분 오류). **서류 사진**도 드로어에서 확인한 뒤 입력창에 넣는다. 자동 조회는 없다
- **지원 범위 밖**의 "B/L 다시 입력"은 없어진 `#bl` 입력칸을 가리키는 깨진 링크였다. "질문 고치기" 버튼으로 바꿔 입력창으로 보낸다
- **여유 일수 음수**는 "N일 초과"에서 "N일 늦음"으로 바꾸고 "판매일이 이미 지났다는 뜻은 아닙니다"를 붙였다 (구현작업서 8절)
- **버그 수정**: 선박 검색 뒤 이력에서 "저장된 판정 열기"를 누르면 선박 표가 남아 재생 결과가 가려졌다. replay가 화물 보기로 바꾸게 했다
- 결과를 다시 받는 동안 지난 결과에 "이전 조회 결과입니다 · 새 결과를 기다리는 중"을 붙인다
- `TopBar.tsx`, `AskPanel.tsx`는 어디서도 쓰지 않지만 지우지 않았다. TopBar의 타이머 단계 표시 한 줄만 지웠다

### 10-02에 실행한 검증 (당시 기록, 이번 현행화에서 다시 세지 않음)

- `npm run typecheck`, `npm run test:contracts`(SSE 해석, 백엔드·화면 단계 이름 일치 추가), `npm run build`
- `npm run test:e2e`: 데모 상태·페이지 × 1440/375px, 1024/768/390px 가로 넘침, 입력 키·한글 조합·500자·중복 전송, 드로어 포커스·inert·Esc·복귀와 지도 정리, 서류 사진 → 입력(자동 조회 없음), 이력 재생, 움직임 줄이기. 실제 모드는 가공 API(:3199)로 일반 사용자 메뉴, /metrics 직접 접근 차단, SSE 단계 순서, 404 대체, 오류 이벤트와 입력 복구, 이력 available:false. axe WCAG A/AA 위반 0, 페이지 오류 0, 외부 요청 0
- 당시 기록에는 e2e 61건, 백엔드 pytest 671건 통과가 있었다. 10-06 이후 화면과 테스트가 바뀌었으므로 이 숫자를 지금의 값으로 쓰지 않는다.
- 10-06 현행화 때 다시 돌린 것: `npm run typecheck`와 `npm run test:contracts`는 통과했다. e2e와 build는 돌리지 않았다.

## 10-06 현행화

- **화면 전면 개편** (커밋 `7815533`, 마누스 시안 안A): 대화(왼쪽) + 상세(오른쪽) 40:60, 결과가 없으면 대화만 100, 휴대폰은 아래 시트. 새로 생긴 화면: 화물 현황(`/cargo`), 지켜보는 화물(`/watch`), 설정 5탭, 관리, 소개. 디자인은 DESIGN.md
- **CSS 분리**: 화면별 규칙을 `app/styles/*.css` 아홉 파일로 나눴다. `globals.css`는 토큰과 공통 규칙
- **파랑 `#2962F5`**, 연회색 바탕, 신호등 색은 등급에만. 판정 이름은 순항·주의·긴급
- **지도**: OpenFreeMap → 미리 구운 타일 → 해안선 세 단계, `scripts/bake-basemap.mjs`로 타일을 굽는다 (`public/basemap`, 파일 550개, 약 2.9MB 디스크 점유, `meta.json`의 `totalBytes`는 1,661,420). 이 숫자는 이번에 `du`와 `meta.json`에서 읽은 값이다
- **운영자 고객 검색**은 전화번호 뒷 4자리로 한다 (커밋 메시지 기준, 화면 코드는 이번에 다시 읽지 않았다)
- **e2e와 계약 검사**: `verify.mjs`는 지도 호스트 `tiles.openfreemap.org`만 허용하고, `verify-contract.mjs`는 `backend-contract.json` 스냅샷으로 새 칸까지 본다. 실행법은 README
- 화면이 쓰는 백엔드 endpoint가 크게 늘었다(대화, 기억, 지켜보기, 화물 시트, 카카오, 회원 정보, 운영자). 목록은 README "백엔드 붙이기"
- `package.json`에는 `@fontsource-variable/manrope`가 의존성으로 남아 있지만 `layout.tsx`는 Noto Sans KR과 IBM Plex Mono만 불러온다 (10-06 확인). 쓰이는지는 이번에 끝까지 확인하지 않았다

### 확인 못 한 것

- 실제 Google 로그인, 계정 정지 화면, 회원 정보 입력 화면의 새 색 적용(로그인 기능은 Supabase 키가 있어야 켜진다)
- 실제 백엔드·Railway를 거친 SSE 전달(중간 프록시가 모아 보내는지). 로컬 가공 API로만 확인했다 (10-02)
- 200% 확대, 스크린리더 실기 낭독, 키보드만으로 전 화면 순회(드로어 안 Tab 순환과 Enter 전송만 자동 검사)
- 10-06 개편 뒤 e2e 전체 통과 여부 (이번 현행화에서 돌리지 않았다)
