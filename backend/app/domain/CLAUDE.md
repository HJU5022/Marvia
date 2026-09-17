# domain/ 에서 지킬 것

이 폴더는 계산만 한다.

- 네트워크 호출 금지. `httpx`, `requests`, `openai`, `supabase`를 import하지 않는다
- LLM 호출 금지
- 규칙값을 숫자로 적지 않는다. `rules.py`가 `skills/converge/rules/*.md` 프론트매터에서 읽는다
- 모든 함수는 API 키 없이 pytest가 돌아야 한다
- 외부 데이터가 필요하면 인자로 받는다. 직접 가져오지 않는다

여기 있는 것: `rules.py` (규칙 로드, 절차 소요·여유·역산·전환 조건), `router.py` (소형/대형 선택, docs/SDD.md 5절 라우팅)
