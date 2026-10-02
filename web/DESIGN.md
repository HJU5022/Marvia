# Design direction

개편일 2026-10-02. 기준: 바탕화면 `Marvia_Claude_구현작업서.md`, `Marvia_Ocean_Mockup.html`(픽셀 참고용, 값은 가져오지 않음).

## 방향

- **AI 입력창이 주 기능이다.** 강사 피드백("AI 입력이 소외되어 보이면 안 됨")을 반영해 홈 맨 위 가운데에 큰 질문형 헤드라인과 최대 880px 입력창을 둔다. 챗봇 위젯이나 모달로 옮기지 않는다
- 흰 레일 + 시원한 해양 블루. 캔버스 `#F5F9FE`, 카드 흰색, 주요 동작 `#1765ED`, hover `#174DC4`, 물빛 `#58C9F0`은 장식 그라데이션에만 쓴다
- 결과는 입력 아래로 펼친다: 판정과 지금 할 일 → 지도·ETA 비교 → 통관·선박 식별 → 신호·근거
- 상태 색(정상 `#087867` / 주의 `#8B5609` / 조치 `#B63B49`)은 브랜드 블루와 구분하고, 늘 글자·아이콘을 같이 쓴다
- 폰트는 기존 로컬 번들(Manrope Variable, Noto Sans KR Variable, IBM Plex Mono). 본문 14px

## 구조

| 자리 | 컴포넌트 | 비고 |
|---|---|---|
| 홈 헤드라인·입력 | `app/page.tsx`, `ChatBar.tsx` | 예시는 채우기만, 보내기는 사용자가. Enter 전송, Shift+Enter 줄바꿈, 한글 조합 중 Enter 무시, 500자 |
| 기다림 | `ChatBar.tsx` Pending | 서버가 SSE로 보낸 실제 단계만, 경과 시간은 브라우저 실측 (docs/specs/chat-progress.md) |
| 첫 진입 | `ChatBar.tsx` feature-tiles | 실제로 할 수 있는 세 작업만. API 없는 KPI는 만들지 않는다 |
| 입력으로 돌아가기 | `ChatBar.tsx` back-to-composer, `lib/composer.ts` | 입력창이 화면 밖이면 나타난다 |
| 상세 드로어 | `Drawer.tsx` | 서류 사진, 선박 자세히 보기. 포커스 트랩, Esc, 뒤 화면 inert, 닫으면 포커스 복귀 |
| 레일 | `Shell.tsx` | 일반 사용자 3개 / 운영자 5개 메뉴(GET /api/me). 태블릿 아이콘 레일은 aria-label로 이름 유지 |

## 움직임

구현작업서 5절 효과 표만 쓴다: 입력창 포커스(블루 링 + 2px 위로, 240ms), 결과 등장(opacity·y 12→0, 420ms, 새 결과일 때만), 드로어(x 24→0, 280ms), 예시 hover(2px 위로), 대기 점·선(실제 대기 중에만), 페이지 전환 fade(200ms). `prefers-reduced-motion: reduce`이면 모두 끈다. 지도에 가짜 항적이나 위치 펄스는 없다.

## CSS 관리

`app/globals.css`의 `:root` 토큰을 해양 팔레트로 바꿨고 이름은 그대로 두었다(`--rail`은 이제 주요 동작 블루). 새 배치와 덮어쓰기는 파일 끝 "Ocean workspace" 구역에 있고, 그 구역이 다시 정의한 것은 자기 breakpoint(1190/900/700px)를 따로 갖는다.
