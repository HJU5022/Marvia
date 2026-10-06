# Design direction

개편일 2026-10-02. 기준: 바탕화면 `Marvia_Claude_구현작업서.md`, `Marvia_Ocean_Mockup.html`(픽셀 참고용, 값은 가져오지 않음).

## 방향 (10-06 토스형으로 바꿈)

기준: 바탕화면 마누스 시안 `01_공통_스타일과_결정.md`(안A). 10-02 해양 블루 방향은 이 절로 대체했다.

- **토스처럼 크고 친근하게.** 본문 16px, 글자 크기는 네 단계(14·16·20·26), 둥글기 8~12px, 여백 넉넉히
- **바탕 연회색 `#F2F4F6`, 카드 흰색**, 테두리·그림자는 거의 없음. 그라데이션·빛·유리·다크 모드·이모지 없음
- **파랑 `#2962F5`(hover `#1D4FD7`)는 누를 수 있는 것에만**: 버튼, 링크, 선택된 메뉴. 글자 `#191F28`, 보조 글자 `#6B7684`
- **신호등 색은 판정 등급(순항·주의·긴급)에만.** 부드러운 톤(`--grade-fine/-watch/-act`와 `-bg`), 긴급은 배지와 글자를 굵게. 성공 알림·사용량 안내·정지 배지에는 쓰지 않고 회색/파랑을 쓴다
- 글꼴 스택 `'Pretendard','Noto Sans KR Variable',-apple-system,sans-serif`. Pretendard는 설치돼 있지 않아 번들된 Noto Sans KR이 쓰인다. 고정폭(IBM Plex Mono)은 번호용
- 아이콘은 lucide 선 아이콘만. 왼쪽 메뉴·위쪽 바에서 영어 보조 글자, 홍보 문구, 영문 푸터는 뺐다
- 상세 패널의 일정·통관 줄만 한 단계 작게(14px). 판정 배지와 할 일 한 줄은 크게

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

`app/globals.css`의 `:root` 토큰이 기준이다. 옛 이름(`--rail`=누를 수 있는 파랑, `--ink`, `--muted`, `--success/--warning/--danger`=판정 색)은 그대로 두고 값만 새 팔레트로 바꿨고, 새 이름(`--brand`, `--text`, `--text-2`, `--grade-*`)을 더했다. 옛 규칙은 지우지 않고 파일 끝 "Marvia 토스형 프레임" 구역이 덮는다. 화면별 CSS는 `app/styles/` 아홉 파일(chat, detail, compare-vessel, document, cargo-sheet, watch, settings, admin, entry)이고 `layout.tsx`가 globals.css 뒤에 불러온다.
