# FRONTEND_GUIDE

Next.js. Vercel에 배포. Root Directory = `frontend`.

## 구조

| 경로 | 무엇 |
|---|---|
| `app/page.tsx` | 지도 + 채팅. 왼쪽 카카오맵, 오른쪽 채팅창과 이미지 업로드 (docs/PRD.md 4절) |
| `app/about/page.tsx` | 소개 페이지. 필수 조건 6. 서비스 화면과 별도 |
| `app/s/[id]/page.tsx` | 공유 링크. 읽기 전용. `GET /api/session/{id}` |
| `app/api/agent/route.ts` | Cloud Run 프록시. 브라우저는 백엔드를 직접 부르지 않는다 |
| `components/` | MapView, ChatPanel, ParticipantPins(핀 확인 단계), ResultTable, Progress |
| `lib/kakao.ts` | 지도 SDK 로더 |
| `lib/api-types.ts` | 생성물. `backend/app/schemas/`에서 `scripts/gen_types.sh`로 만든다. 손으로 고치지 않는다 |

## 응답 stage에 따라 화면이 갈린다 (docs/SDD.md 2절)

| stage | 화면 |
|---|---|
| `need_confirm` | 참석자 핀을 지도에 찍고 사용자가 끌어서 수정. 확정하면 `confirmed_participants`로 다시 요청 |
| `need_info` | `questions[]`를 채팅에 보여주고 되묻는다 |
| `done` | 후보 핀 + 참석자별 경로선 + ResultTable |
| `out_of_scope` | `message` 표시 |
| `failed` | 후보 핀만 찍고 재시도 버튼 |

## 지킬 것

- `components/` 안에서 백엔드 주소를 직접 fetch하지 않는다. `app/api/agent/route.ts`만 부른다
- 브라우저에 나가는 키는 `NEXT_PUBLIC_KAKAO_JS_KEY` 하나. 숨길 수 없으니 카카오 콘솔 도메인 등록으로 제한한다. 나머지 키는 프론트에 없다
- 환경변수는 `frontend/.env.local` (루트 `.env`와 별개). `NEXT_PUBLIC_API_BASE`로 백엔드 주소
- 즉각 피드백, 오류 안내, 입력 가이드 세 가지가 화면에 있어야 한다 (가이드 8-3). 실패 화면은 데모 영상에 필요하다
- 부대명·고객사명을 예시 문구에 쓰지 않는다

## 실행

`cd frontend && npm run dev` (:3000). 카카오 콘솔에 `localhost:3000`과 Vercel 도메인을 등록한다.
