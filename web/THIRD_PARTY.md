# 번들한 글꼴과 라이브러리

화면에 싣는 글꼴과 아이콘은 모두 npm 패키지로 번들한다. 바깥 글꼴 서버나 CDN에 요청하지 않는다(화면 시험이 바깥 요청 0건을 본다).

- **Manrope** (`@fontsource-variable/manrope` 5.3.0): SIL Open Font License 1.1. 영문과 숫자. https://fontsource.org
- **Noto Sans KR** (`@fontsource-variable/noto-sans-kr` 5.3.1): SIL Open Font License 1.1. 한글. https://fontsource.org
- **IBM Plex Mono** (`@fontsource/ibm-plex-mono` 5.3.0): SIL Open Font License 1.1. B/L과 컨테이너 번호에만. https://fontsource.org
- **Lucide** (`lucide-react` 1.71.0): ISC. 선 아이콘. https://lucide.dev/license
- **Next.js, React**: MIT. https://nextjs.org / https://react.dev
- **Supabase JS** (`@supabase/supabase-js`): MIT. 로그인. https://github.com/supabase/supabase-js

디자인 규칙은 v1(`v1-final:web/DESIGN.md`)을 따른다: 흰 바탕, 가는 선, 각진 모서리, 파랑은 누를 수 있는 것에만, 신호등 색은 판정 등급에만(계획 9). 지도 라이브러리는 쓰지 않는다.
