# FRONTEND_GUIDE

Next.js. Vercel에 배포. Root Directory = `frontend`.

## 구조

| 경로 | 무엇 |
|---|---|
| `app/page.tsx` | 주선자 화면. 왼쪽 카카오맵, 오른쪽 채팅창과 캡처 업로드, 결과 표, 공유 링크 (docs/PRD.md 4절) |
| `app/about/page.tsx` | 소개 페이지. 필수 조건 6. 서비스 화면과 별도 (아직 없음) |
| `app/s/[id]/page.tsx` | 공유 링크. 로그인해야 보인다. 참석자 목록에서 자기를 고르면(claim) 자기 핀을 옮길 수 있다 |
| `app/api/agent/route.ts` | `POST /api/agent` 프록시. 브라우저는 백엔드를 직접 부르지 않는다 |
| `app/api/session/[id]/route.ts` | `GET /api/session/{id}` 프록시 |
| `app/api/session/[id]/participants/route.ts` | `PATCH /api/session/{id}/participants` 프록시 |
| `components/MapView.tsx` | 지도 한 장. stage별 핀 구성, 후보·픽업·목적지 핀, 경로선 토글과 범례, bounds 맞춤 |
| `components/ParticipantPins.tsx` | 참석자 출발지 핀. 핀 소유권에 따른 드래그 허용(`canEdit`) |
| `components/RouteLines.tsx` | `per_participant[].polyline`. 이동수단별 색 3가지 |
| `components/ChatPanel.tsx` | 문장 입력, 캡처 업로드, 되묻기 표시, 입력 가이드 |
| `components/ResultTable.tsx` | 집결 후보(순위·근거)와 참석자별 출발 시각·소요·여유·첫차 |
| `components/AuthGate.tsx` | 로그인 전에는 로그인 버튼만 보여준다 |
| `lib/kakao.ts` | 지도 SDK 로더(autoload=false, 한 번만), 핀 이미지 |
| `lib/auth.ts` | 구글 로그인(Supabase Auth), 토큰 헤더 |
| `lib/proxy.ts` | `app/api/` 라우트 공용. `NEXT_PUBLIC_API_BASE`로 전달, 없으면 mock |
| `lib/mock.ts` | 백엔드 없이 화면을 확인할 고정 응답. 입력 문장으로 시나리오(함정·SI)와 stage를 고른다(파일 상단 주석). 서버에서만 import |
| `lib/mock-data.json` | mock 시나리오와 실제 경로 좌표. `routes`는 `scripts/fetch_mock_routes.py`가 채운다 |
| `lib/dev-user.ts` | 로컬 모드 사용자 id. 브라우저 코드는 mock 대신 이 파일을 import 한다 |
| `types/agent.ts` | SDD 2·3·4절 타입을 손으로 옮긴 것. `lib/api-types.ts`가 생기면 대체한다 |
| `lib/api-types.ts` | 생성물. `backend/app/schemas/`에서 `scripts/gen_types.sh`로 만든다. 손으로 고치지 않는다 (아직 없음) |

## 응답 stage에 따라 화면이 갈린다 (docs/SDD.md 2절)

| stage | 화면 |
|---|---|
| `need_confirm` | `geocoded`의 참석자 핀만. "위치가 맞나요" + 계산 버튼. 확정하면 `confirmed_participants`로 다시 요청 |
| `need_info` | `questions[]`를 채팅에 보여주고 대기 |
| `done` | 후보 핀 + 참석자 핀 + 픽업 핀 + 경로선 + ResultTable. `provisional`이면 "시각 미확정, 잠정" 배지 |
| `out_of_scope` | 범위 밖 안내만 |
| `failed` | 후보 핀만 찍고 안내와 재시도 버튼 |

## 지도 규칙

- 핀 좌표는 `AgentResponse.geocoded`에서만 온다. Slots에는 좌표가 없다
- 핀 소유권(SDD 7절): 주선자는 `owner_user_id`가 null인 핀만, 참석자는 자기 id인 핀만 끈다. 못 끄는 핀은 회색, 커서 `not-allowed`
- 주선자 재계산 때 `confirmed_participants`에는 주선자가 고칠 수 있는 핀만 담는다
- 공유 링크에서 자기 이름을 고르면 PATCH `claim: true`, 핀을 옮기면 `claim: false`. 403은 "본인 핀만 수정할 수 있습니다", 409는 "이미 다른 사람이 등록했습니다"
- 경로선 색은 이동수단(car·transit·walk) 세 가지. 사람마다 색을 바꾸지 않는다
- 참석자 4명 이하면 경로선 기본 켬, 5명 이상이면 기본 끔. 꺼져 있을 때 참석자 핀을 누르면 그 사람 것만 보인다
- `via_pickup`이 true인 참석자는 선을 그리지 않고 픽업 지점에 핀만 찍는다. 좌표는 `geocoded`의 `kind: "pickup"`, 없으면 그 사람 `polyline[0]`(탑승 지점)
- 핀 구성이 바뀌면(새 응답) bounds를 맞춘다. 드래그로는 다시 맞추지 않는다
- mock 경로는 실제 API에서 받아 둔 값이다. mock에서 핀을 옮기면 그 사람 선은 두 점 직선이 된다(백엔드가 붙으면 다시 계산된다). 시나리오 좌표를 바꾸면 `python scripts/fetch_mock_routes.py --force`

## 지킬 것

- `components/` 안에서 fetch하지 않는다. 페이지가 `app/api/` 라우트만 부른다
- 브라우저에 나가는 키는 `NEXT_PUBLIC_KAKAO_JS_KEY`와 Supabase anon key뿐이다. 카카오 REST 키는 프론트에 없다
- 카카오맵 외 지도 라이브러리를 쓰지 않는다
- 서비스 전체가 로그인 뒤에 있다. 익명 열람 경로를 만들지 않는다. Supabase 설정 없이 로그인을 건너뛰는 로컬 모드는 `next dev`에서만 켜지고(백엔드는 `AUTH_REQUIRED=false`), 배포 빌드에서는 화면이 막힌다
- 환경변수는 `frontend/.env.local` (루트 `.env`와 별개). `NEXT_PUBLIC_API_BASE`가 없으면 `lib/mock.ts`로 답한다
- 즉각 피드백, 오류 안내, 입력 가이드 세 가지가 화면에 있어야 한다 (가이드 8-3). 실패 화면은 데모 영상에 필요하다
- 부대명·고객사명을 예시 문구에 쓰지 않는다
- `next.config.ts`의 `agentRules: false`를 지우지 않는다. 지우면 `next dev`가 이 폴더에 AGENTS.md, CLAUDE.md를 만든다

## 실행

`cd frontend && npm install && npm run dev` (:3000). 카카오 콘솔 > 플랫폼 > Web에 `http://localhost:3000`과 Vercel 도메인을 등록해야 지도가 뜬다.
