# 디자인 규칙

화면을 고칠 때 지키는 규칙과 그 이유다. 실행, 페이지 목록, 지도 바탕 단계는 [README.md](README.md), 글꼴·지도 출처는 [THIRD_PARTY.md](THIRD_PARTY.md)에 있다. 값은 모두 `app/globals.css`의 `:root` 토큰이 기준이다.

## 원칙

| 규칙 | 값 (토큰) |
| --- | --- |
| 바탕은 흰색, 구분은 가는 선. 그림자·그라데이션·빛·유리 효과·다크 모드·이모지를 쓰지 않는다 | `--bg`, `--surface` `#ffffff`, `--border` `#e8e8e8`, `--shadow: none`, `--glow: none` |
| 모서리는 각지게 둔다 (원형 점만 예외) | `--radius`, `--small-radius` `0` |
| 파랑은 누를 수 있는 것(버튼, 링크, 선택된 메뉴)에만 쓴다 | `--brand` `#2962f5`, hover `--brand-hover` `#1d4fd7` |
| 신호등 색은 판정 등급(순항·주의·긴급) 표시에만 쓴다. 성공 알림·사용량 안내·정지 배지에는 회색이나 파랑을 쓴다 | `--grade-fine`, `--grade-watch`, `--grade-act`와 각 `-bg`(바탕), `-solid`(점·지도 핀·테두리) |
| 글자 색은 세 단계 | `--text` `#1f1f1f`, `--text-2` `#4a4a4a`, `--muted` `#6b6b6b` |
| 글꼴은 레포에 번들한 것만 쓴다. 영문·숫자는 Manrope, 한글은 Noto Sans KR, 고정폭 IBM Plex Mono는 B/L·컨테이너 번호에만 | `--font`, `--mono` (`app/layout.tsx`가 `@fontsource` 패키지를 불러온다) |
| 글자 크기는 토큰으로만 고른다. 본문은 14px | `--text-xs` 12, `--text-sm` 13, `--text-base` 14, `--text-lg` 18, `--text-xl` 22 (px). 공용 `--fs-*`는 15, 28을 더 갖는다 |
| 제목은 굵게: h1 700, h2·h3 600. 첫 화면 제목은 26px | `app/styles/brand.css` |
| 주 버튼은 파랑 채움, 보조 버튼은 회색 외곽선 | `.button.primary`, `.button.secondary` |
| 아이콘은 lucide 선 아이콘만 쓴다 | `lucide-react` |
| 사이드바와 상단 줄에 영어 보조 글자, 홍보 문구를 넣지 않는다 | |

## 화면 틀

대화 화면 `/` (`app/page.tsx`, `app/styles/chat.css`):

| 상태 | 배치 |
| --- | --- |
| 결과 없음 | 대화만 가운데 (100:0) |
| 결과 있음 | 대화(왼쪽)와 상세(오른쪽) 40:60. 대화 칸 `clamp(380px, 40%, 720px)` |
| 선박 표를 볼 때 | 열이 많아 대화 칸을 `clamp(360px, 32%, 560px)`로 좁힌다 |
| 900px 이하 | 상세가 아래에서 올라오는 시트가 된다. 접으면 손잡이 줄만 보인다. 입력창을 누르면 시트가 접혀 키보드와 입력창이 가려지지 않는다 |
| 700px 이하 | 사이드바가 위 띠로 바뀌고 틀을 세로로 쌓는다 |

- 이 화면에서만 페이지 전체가 아니라 안쪽 칸이 스크롤한다 (`body[data-fit]`).
- 사이드바를 접었거나 좁은 화면이면 대화 칸 왼쪽 위 단추가 대화 목록 패널을 연다.

## 상호작용

| 자리 | 컴포넌트 | 규칙 |
| --- | --- | --- |
| 입력 | `ChatBar.tsx` | 예시는 입력창을 채우기만 하고 보내기는 사용자가 한다. Enter 전송, Shift+Enter 줄바꿈, 한글 조합 중 Enter 무시, 500자까지 (`MAX`, 서버 `ChatRequest.message`와 같다) |
| 기다림 | `ChatBar.tsx` | 서버가 SSE로 보낸 실제 단계만 보이고 경과 시간은 브라우저가 잰다 ([docs/specs/chat-progress.md](../docs/specs/chat-progress.md)) |
| 첫 화면 | `ChatBar.tsx` `feature-tiles` | 실제로 할 수 있는 세 작업(B/L 조회, 입항 예정 선박 찾기, 서류 사진 올리기)만 둔다. API가 없는 숫자 지표는 만들지 않는다 |
| 입력으로 돌아가기 | `ChatBar.tsx` `back-to-composer`, `lib/composer.ts` | 입력창이 화면 밖으로 나가면 나타난다 |
| 상세 드로어 | `Drawer.tsx` | 포커스를 안에 가두고, Esc로 닫고, 뒤 화면은 `inert`, 닫으면 연 단추로 포커스를 돌려준다 |
| 사이드바 | `Shell.tsx` | 접으면 아이콘만 남고 `aria-label`로 이름을 유지한다 |

## 움직임

| 토큰 (`app/styles/chat.css`) | 값 | 쓰는 곳 |
| --- | --- | --- |
| `--t-fast` | 150ms | 눌림, hover |
| `--t-enter` | 220ms | 나타남 |
| `--t-panel` | 320ms | 패널, 지도. 상세 칸이 오른쪽에서 들어오고(`m-slide-in`) 휴대폰 시트가 아래에서 올라온다(`m-sheet-up`) |

- `prefers-reduced-motion: reduce`이면 `globals.css`가 animation과 transition을 모두 끈다.
- 지도에 가짜 항적이나 위치 펄스를 그리지 않는다. 감시 화물 지도의 선은 서버가 준 위치 이력(`track`)만 잇는다 (`components/WatchMap.tsx`).
- 지도의 땅·바다 색은 `--land`, `--sea` 토큰이다. 바탕 단계는 README [지도 바탕](README.md#지도-바탕).

## CSS 관리

- 불러오는 순서: `app/globals.css` → `app/styles/` 14개 (`app/layout.tsx` 순서: chat, detail, compare-vessel, document, cargo-sheet, watch, settings, admin, entry, landing, sidebar, metrics, evidence, brand). 뒤 파일이 앞의 같은 선택자를 덮는다.
- `brand.css`는 마지막 덮개다. 로그인한 뒤 화면을 소개 랜딩(`landing.css`)과 같은 톤으로 맞춘다.
- `globals.css` 안에서는 맨 끝 "Marvia 토스형 프레임" 구역이 위쪽 옛 규칙을 같은 선택자로 덮는다. 옛 규칙은 지우지 않았다.
- 새 화면 코드는 새 토큰 이름을 쓴다. 옛 이름은 값만 새 토큰을 가리키게 남겨 두어 아직 안 고친 화면도 같은 색을 따라온다.

| 옛 이름 | 가리키는 새 토큰 |
| --- | --- |
| `--canvas`, `--ink`, `--body`, `--quiet` | `--bg`, `--text`, `--text-2`, `--muted` |
| `--rail`, `--rail-deep`, `--blue`, `--blue-dark` | `--brand`, `--brand-hover` |
| `--success`, `--warning`, `--danger` (와 `-bg`) | `--grade-fine`, `--grade-watch`, `--grade-act` (와 `-bg`) |

## 바뀐 과정

처음엔 해양 블루 방향이었다가, 연회색 바탕에 둥근 흰 카드를 쓰는 토스형으로 바꿨고, 지금은 흰 바탕, 각진 모서리, 가는 선으로 정리했다. 마지막으로 로그인한 뒤 화면을 소개 랜딩과 같은 톤(굵은 제목, 파랑 채움 주 버튼)으로 맞췄다 (`app/styles/brand.css`). "토스형 프레임"이라는 구역 이름과 옛 토큰 이름은 이 과정에서 남은 것이다.
