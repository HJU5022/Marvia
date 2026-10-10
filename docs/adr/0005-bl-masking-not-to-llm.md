# 0005. B/L 번호는 LLM에 넘기지 않고 트레이스에는 가려서 남긴다

상태: 채택

## 맥락
B/L 번호는 UNI-PASS 조회 키이고 사용자 화물을 가리킨다. 프롬프트, Langfuse 트레이스, 로그에 원문이 남으면 외부로 나간다. UNI-PASS 약관 15조③은 조회 정보의 복제와 타인 제공을 금지한다 ([SDD 7절](../Marvia_SDD.md)).

## 결정
- UNI-PASS는 코드가 직접 부른다. B/L은 LLM에 넘기지 않는다. 채팅 문장은 코드가 `[BL1]` 번호표로 가린 뒤 보낸다.
- 트레이스, 로그, 조회 이력에는 가운데 절반을 `*`로 가린 값만 남긴다 (`schemas/customs.py mask_bl`, 예 `TE****01`).
- 컨테이너 번호도 `[CNTR1]` 번호표로만 준다. 중량, 세관명, 화주 정보는 LLM에도 DB에도 넣지 않는다.
- 저장하는 B/L 원본은 `BL_ENCRYPTION_KEY`로 잠근다. 회원 정보는 따로 `PII_ENCRYPTION_KEY`를 쓴다. 한쪽 열쇠가 새도 다른 쪽은 안전하다 ([specs/user-profile.md](../specs/user-profile.md)).

## 대안
- 품명도 LLM에서 빼기: 처음 계획이다. 화면이 품명으로 화물을 구분하고 "고추 화물 어디야?"를 알아들어야 해서, 채팅 에이전트에만 주고 판정 LLM에는 주지 않도록 바꿨다 ([SDD](../Marvia_SDD.md) "부록. 계획 대비 변경" 표 품명 행).

## 결과
- 좋아진 것: 트레이스와 LLM 입력에 원본 B/L이 없다.
- 대가: 본인 화물 엑셀 내려받기만 원본을 풀어 쓰는 예외가 있다 ([SDD 3.5절](../Marvia_SDD.md)).

## 근거
- [SDD](../Marvia_SDD.md) 3.5절, 7절
- [CLAUDE.md](../../CLAUDE.md) "하지 말 것": "B/L 번호를 LLM에 넘기지 않는다", "UNI-PASS 응답의 중량, 세관명, 화주 정보를 LLM에 넘기거나 DB에 저장하지 않는다", "컨테이너 번호는 B/L처럼 LLM에 원문을 넘기지 않는다"
- [specs/user-profile.md](../specs/user-profile.md)
