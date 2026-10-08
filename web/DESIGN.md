# Design direction

1차 개편 2026-10-02(해양 블루, 바탕화면 `Marvia_Claude_구현작업서.md`, `Marvia_Ocean_Mockup.html`을 참고). 2차 개편 2026-10-06(토스형, 아래). 현행화 2026-10-06.

## 방향 (토스형으로 바꿈)

기준: 마누스 시안 `01_공통_스타일과_결정.md`(안A). 처음의 해양 블루 방향은 이 절로 대체했다.

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
| 화면 틀 | `app/page.tsx`, `styles/chat.css` | 대화(왼쪽)와 상세(오른쪽). 결과가 없으면 대화만 가운데 100:0, 결과가 생기면 40:60 (`clamp(380px,40%,720px)`, 선박 표는 `clamp(360px,32%,560px)`). 900px 이하는 상세가 아래 시트, 700px 이하는 사이드바가 위 띠 |
| 홈 헤드라인·입력 | `app/page.tsx`, `ChatBar.tsx` | 예시는 채우기만, 보내기는 사용자가. Enter 전송, Shift+Enter 줄바꿈, 한글 조합 중 Enter 무시, 500자 |
| 기다림 | `ChatBar.tsx` Pending | 서버가 SSE로 보낸 실제 단계만, 경과 시간은 브라우저 실측 (docs/specs/chat-progress.md) |
| 첫 진입 | `ChatBar.tsx` feature-tiles | 실제로 할 수 있는 세 작업만. API 없는 KPI는 만들지 않는다 |
| 입력으로 돌아가기 | `ChatBar.tsx` back-to-composer, `lib/composer.ts` | 입력창이 화면 밖이면 나타난다 |
| 상세 드로어 | `Drawer.tsx` | 서류 사진, 선박 자세히 보기. 포커스 트랩, Esc, 뒤 화면 inert, 닫으면 포커스 복귀 |
| 레일 | `Shell.tsx` | 일반 사용자: 새 대화와 대화 목록(대화 화면 `/`), 화물 묶음(감시 화물 `/watch`, 화물 현황, 조회 이력), Marvia 소개, 계정 메뉴(10-08 "내 화물" 메뉴는 대화 화면과 겹쳐 뺐다). 운영자는 평가 지표와 관리가 더해진다(GET /api/me). 레일은 접을 수 있고 아이콘만 남을 때는 aria-label로 이름 유지. 로그인 사용자에게는 대화 목록 구역 |
| 지도 | `lib/basemap.ts`, `MapPanel`, `ChatMiniMap`, `VesselMap`, `WatchMap` | 바탕 세 단계: WebGL OpenFreeMap → 미리 구운 타일(`public/basemap`) → Natural Earth 해안선. 바다·땅 색은 `--sea`, `--land` 토큰 |

## 움직임

움직임 토큰은 `styles/chat.css` 맨 위의 `--t-fast` 150ms(눌림·hover), `--t-enter` 220ms(나타남), `--t-panel` 320ms(패널·지도)다. 상세 칸은 40:60으로 나뉠 때 오른쪽에서 들어오고(`m-slide-in`), 휴대폰 시트는 아래에서 올라온다(`m-sheet-up`). `prefers-reduced-motion: reduce`이면 `globals.css`가 animation과 transition을 모두 끈다. 지도에 가짜 항적이나 위치 펄스는 없다. 지켜보는 화물의 선은 실제 저장된 위치(`watch_positions`)만 잇는다.

## CSS 관리

`app/globals.css`의 `:root` 토큰이 기준이다. 옛 이름(`--rail`=누를 수 있는 파랑, `--ink`, `--muted`, `--success/--warning/--danger`=판정 색)은 그대로 두고 값만 새 팔레트로 바꿨고, 새 이름(`--brand`, `--text`, `--text-2`, `--grade-*`)을 더했다. 옛 규칙은 지우지 않고 파일 끝 "Marvia 토스형 프레임" 구역이 덮는다. 화면별 CSS는 `app/styles/` 아홉 파일(chat, detail, compare-vessel, document, cargo-sheet, watch, settings, admin, entry)이고 `layout.tsx`가 globals.css 뒤에 이 순서로 불러온다. 뒤에 오는 파일이 앞의 같은 선택자를 덮는다.
