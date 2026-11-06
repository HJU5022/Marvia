# 범용 도구 비교 절차 (done 3.8)

Marvia, Claude Code, Codex CLI에 같은 질문 7개를 주고 답에 통관 단계, 기한 날짜, 근거 조문이 맞게 들어 있는지를 같은 코드로 잰다. 문항은 `eval/set_v1.yaml`에서 `domain` 칸이 있는 R01, R09, R10, R12, R13, R14, R15이고, 기대값은 그 칸에 있다.

## 지키는 것

- 화물 번호는 가공 번호(DEMO·MOCK·TEST)뿐이다. 실제 B/L이나 실제 UNI-PASS 응답은 쓰지 않는다.
- 범용 도구는 저장소 밖 빈 폴더에서 돌린다. 세션 기록과 답 글이 저장소에 남지 않게 한다. 답 글은 저장소에 넣지 않고 맞힌 수만 남긴다.
- 세 도구 모두 같은 질문 글을 받는다. 범용 도구에는 Marvia가 쓰는 가공 화물 파일(`fixtures/unipass/*.json`)을 같은 폴더에 둔다. 사용자가 UNI-PASS 화면을 옮겨 준 경우와 같은 조건이다. 법령 코퍼스는 주지 않는다(범용 도구는 자기 지식과 웹 검색을 쓴다).
- 오늘 날짜는 평가셋 기준일(`as_of`, 2026-11-06)로 질문 글에 적는다.

## 순서

1. 질문 글과 화물 파일 만들기 (키 없음)

   ```bash
   uv run python scripts/run_eval.py domain-prompts --out ~/marvia-domain
   ```

2. Claude Code (구독 사용량이 든다)

   ```bash
   cd ~/marvia-domain && mkdir -p claude-code
   for f in R*.txt; do claude -p "$(cat "$f")" > "claude-code/$f"; done
   ```

3. Codex CLI (OpenAI 로그인이 필요하다. 읽기 전용 샌드박스)

   ```bash
   cd ~/marvia-domain && mkdir -p codex
   for f in R*.txt; do codex exec -s read-only --skip-git-repo-check -C . "$(cat "$f")" > "codex/$f"; done
   ```

4. 채점 (키 없음). Marvia 답은 같은 커밋의 평가 실행 raw 파일에서 읽는다.

   ```bash
   uv run python scripts/run_eval.py domain ~/marvia-domain/claude-code ~/marvia-domain/codex \
     --marvia <평가 실행 폴더>/agent-claude-haiku-5-5.raw.json
   ```

## 재는 것

| 칸 | 맞음 |
|---|---|
| 통관 단계 | 기대한 단계 이름(예: 반입신고)이 답에 있다 |
| 기한 | 기대한 날짜가 2026-11-26, 2026.11.26, 2026년 11월 26일, 11월 26일 가운데 한 꼴로 답에 있다 |
| 조문 | 기대한 법령 이름과 조문 번호(예: 관세법 제241조)가 답에 있다. 제241조의2는 제241조가 아니다 |

글자를 찾는 채점이라 뜻이 맞는지는 보지 않는다. 날짜가 맞아도 다른 날짜를 함께 적었는지, 조문이 맞아도 해석이 틀렸는지는 사람 채점(`eval/human_v1.yaml`)과 따로 읽는다.
