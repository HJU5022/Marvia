# Marvia v2 계획 8c: 모델이 배 판정을 읽고 쓰게 한다 (스위치 뒤)

> 진행 방법: 태스크를 T0부터 차례로 하고, 단계마다 체크박스(`- [ ]`)로 표시한다. 커밋 하나는 동작 하나다. 이 계획은 8b B부분(기준 `f208e59`, A부분 끝 `2bc6073` 위 29 커밋, 검증 고침 R-135~R-151 포함)이 들어간 뒤에 한다. B 관문에서 또 고침이 나오면 그 고침이 들어간 B 끝으로 기준을 한 번 더 맞춘다. **이 문서는 구현 전에 쓴 계획이다. 코드와 시험은 아직 없고, 아래의 시험 이름과 기준은 계획이다.** 코드 블록(diff)은 구현한 뒤에 채운다(8b와 같은 순서). 표기: [실측] 코드나 파일에서 읽음, [문서] 기존 문서에서 가져옴, [추정] 내 판단, [결정 11-16] 이 계획에서 확정.

**Goal:** 8b가 만든 배 식별과 판정을 에이전트 길의 모델이 읽고 답에 쓰게 한다. 모델이 보는 것(도구, 지시문, 판정 블록, 검증자)이 바뀌므로 모든 변화를 스위치 `MARVIA_VESSEL=on` 뒤에 둔다. 꺼진 길의 모델 입력은 측정 커밋 `48ca3c5`와 같게 지킨다. 모델은 배를 고르지 않고 날짜를 계산하지 않는다: 배 식별자(이름, 호출부호, 배 번호, MRN)는 모델에 가지 않고, 모델이 넘기는 날짜는 사용자가 그 차례에 쓴 절대 날짜와 같을 때만 코드가 받는다.

**Architecture:** 8b의 노드 셋(vessel, ask_vessel, verdict)은 그대로 둔다. 더하는 것은 (1) 도구 셋 `read_vessel`, `note_dates`, `redo_vessel`(스위치가 켜진 에이전트 길에만), (2) 코드가 쓴 판정 블록(작성자 입력과 에이전트의 차례 메시지에 스위치가 켜졌을 때만 붙음), (3) 판정 블록을 받는 검증자 규칙 넷, (4) 평가 실행기의 `--vessel` 인자와 평가셋 v4다.

```
사용자 글 ── identify ── lookup ── vessel ── (ask_vessel) ── verdict ── news ── brief ── agent(도구 루프) ── write ── verify ── finish
                                                  ^                        |           |       |             |        |
                                      redo_vessel가 행을 지움            judge(...,   brief가   도구:          작성자   검증자
                                      (다음 차례에 다시 찾음)            sale_due,    <vessel_lines>   read_vessel  입력에     판정 블록과
                                                                         first_eta,   를 더함        note_dates   판정 블록     답을 견줌
                                                                         forwarder_   (켰을 때만)    redo_vessel  (켰을 때만)
                                                                         eta)  <── cargo_dates(공책)
스위치가 꺼져 있으면: 도구 목록, 지시문, brief 메시지, 작성자 입력, 검증자 입력이 모두 48ca3c5와 같다
```

**Tech Stack:** 새 의존성 없음. Python 3.12, LangGraph, pydantic, PyYAML (`uv.lock` 그대로). 계획 8b와 같다. 이 계획의 코드는 LLM을 부르지 않는다(도구는 모델이 부르지만 값은 코드가 정한다).

**Spec:** `docs/specs/2026-10-28-marvia-v2-design.md` (2절 결정 3·13, 6.5 검증자, 7.1 판정, 10절 화물 카드, 12절 신뢰 경계). 앞 계획: 8a, 8b A부분(`docs/plans/2026-11-15-marvia-v2-plan-8b-part-a.md`), 8b B부분(`docs/plans/2026-11-15-marvia-v2-plan-8b-part-b.md`). 조사 초안: `.claude/run/plans/2026-11-16-plan-8c-draft.md`. 측정: `.claude/run/research/1113-comparison.md`.

## 계획 나눔

| 계획 | 범위 | 상태 |
|---|---|---|
| 8a | 배 추적 기반 | 완료 (`ckpt/8a-fix`) |
| 8b A부분 | 배 판정 규칙 | 완료 (`2bc6073`) |
| 8b B부분 | 그래프·서버·화면 연결(스위치 뒤) | 코드 완료 `f208e59`, 관문 중 |
| **8c (이 문서)** | 모델이 읽는 도구, 날짜 받기, 답 글의 판정, 되돌리기, 평가셋 v4, 새 측정 | 11-16 계획 |
| 따로 | 위치 이력 모으기, 감시 재조회에서 배 다시 보기, 확정한 배를 감시 표에 저장, 수퍼바이저 길에 새 도구 주기, 도구 안에서 멈추는 조회(`check_vessel`) | 정하지 않음 |

이 문서의 기준은 B부분 끝 `f208e59`(11-16 맞춤, 이전 기준은 `partb6`)이다. 8c의 diff는 그 위에 쌓는다. 기준 시점의 전체 시험은 호스트에서 1,281 통과, 8 건너뜀이다(관문 쪽에서 받은 값, 이 계획을 쓸 때는 돌리지 않음) [문서]. 8c의 커밋마다 이 수가 줄지 않고 새 시험만큼 늘어야 한다. B 관문에서 고침이 더 들어오면 이 수와 아래 "B 고침이 8c 계획에 미친 영향"을 다시 맞춘다.

## 결정과 근거 (11-16)

| # | 결정 | 이유 | 틀렸을 때 비용 |
|---|---|---|---|
| C1 | 8c의 모든 변화는 스위치 뒤에 둔다. 스위치가 꺼져 있으면 에이전트 길의 도구 목록·설명, 에이전트 시스템 지시문, 차례 메시지(brief), 작성자 입력, 검증자 입력과 결과, 화물 줄이 `48ca3c5`와 같다 | 지난 본 측정(v3, 다섯 쌍)이 꺼진 길의 기준선으로 살아남는다. 새로 재는 것은 켠 길뿐이다 | 스위치 뒤에 둔 줄 알았던 조각이 새면 기준선이 흔들린다. 8b와 같이 해시가 아닌 "꺼져 있으면 같다" 동작 시험으로 묶고(T1), 끈 길 점검 한 번(측정 (가))이 시험이 놓친 구멍을 찾는다 |
| C2 | 배 식별자(이름, 호출부호, 배 번호, MRN)는 모델에 주지 않는다. 도구 결과, 판정 블록, 프롬프트, 메시지 기록, 도구 인자 모두 토큰(`[BL1]`)으로만 말한다 | 8b B15의 가림 전체(트레이스, 대화 저장소)가 이 결정에 기댄다. 모델에 가지 않으면 배 이름에 지시 문장을 넣는 주입 길도 닫힌다 | 사용자가 "그 배 이름이 뭐야"라고 물으면 카드를 보라고 안내한다. 답이 덜 친절하다 |
| C3 | 답 글에 판정을 쓴다. 코드가 만든 판정 블록(`<vessel_lines>`)이 작성자 입력과 에이전트 차례 메시지에 붙고, 글은 화물 카드와 같은 정한 글(`rules/verdict.yaml`, `rules/vessel.yaml`)이다. 작성자는 블록을 인용하거나 풀어 쓰되 값을 바꾸지 못한다 | 사용자가 카드를 보지 않아도 판정이 답에 있다. 글이 한 곳이라 카드와 답이 어긋나지 않는다 | 모델이 값을 바꿔 말할 위험이 생긴다. 검증자 새 규칙 넷(C4)이 막고 평가가 센다 |
| C4 | 검증자 새 규칙 넷을 모두 넣는다. (1) 답의 등급·확신 이름은 그 화물의 판정 값과 같다. (2) 판정 블록과 사용자가 말한 날에 없는 도착 날짜를 쓰지 않는다. (3) 확신이 "확실"이 아닌 배(고른 배, 서류로만 확정한 배)에 단정 어구를 쓰지 않는다. (4) 등급이 없는 화물(`등급 없음`)에 등급을 쓰지 않는다. 이 규칙들은 판정 값을 받는 **새 규칙 종류**다 | 지금 검증자는 상태와 무관한 정규식과 도구 값 대조뿐이라 "이 화물의 확신이 부분이면 확실이라 쓰지 못한다"를 표현하지 못한다 [실측 `src/marvia/graph/verify.py`, `rules/verify.yaml`] | 정규식이라 놓치는 표현이 있다("틀림없다", "믿으셔도"). 목록은 `rules/verify.yaml`에 두고 평가에서 센다. "주의하세요", "경계를 넘다" 같은 일상어에 걸리지 않게 낱말이 아니라 "등급"·"확신" 옆의 이름만 본다 |
| C5 | 날짜는 도구 인자로 받는다(`note_dates`). 판매 예정일부터 열고 포워더가 알려 준 날, 처음 알던 도착 예정도 같은 도구가 받는다. **모델이 넘긴 ISO 날짜는 그 차례 사용자 글(가린 글, `masked_text`)에서 코드가 읽은 절대 날짜(`2026-11-20`, `2026.11.20`, `2026년 11월 20일`, `11월 20일`, `11/20`)와 같을 때만 받는다.** 글에 없는 날짜, 상대 표현(내일, 다음 주 화요일), 형식 오류는 받지 않고 이유를 도구 결과로 돌려주어 모델이 사용자에게 날짜로 다시 말해 달라고 하게 한다 | "기한은 코드가 계산한다" 원칙: 모델이 날짜를 바꾸거나 계산한 값을 코드가 걸러야 한다 | 두 날짜를 한 글에 쓰면 어느 것이 판매 예정일인지 모델이 정한다(역할을 바꿔 넘길 수 있다). 코드는 날짜가 글에 있는지만 안다. 도구 결과와 카드가 받은 값을 "판매 예정일 2026-11-20(말씀하신 날)"로 되풀이해 사용자가 틀린 역할을 알아챌 수 있게 한다 [추정] |
| C6 | 읽기 도구(`read_vessel`)부터 연다. 조회는 노드가 한다. 도구 안에서 `interrupt`로 멈추는 `check_vessel`은 8c에 넣지 않는다 | 도구 안에서 멈추면 재개 때 도구가 처음부터 다시 돌아 바깥 조회가 두 번 나갈 수 있다(8b가 조회와 되묻기를 두 노드로 나눈 까닭) | 이번 차례에 `lookup_cargo`로 새로 찾은 화물의 배는 이번 차례에 보이지 않는다. `read_vessel`이 그렇다고 말하고(`not_looked`), 사용자가 그 화물을 다음 차례에 다시 말하면 지난다 |
| C7 | 되돌리기(`redo_vessel`)는 토큰과 횟수(`vessel_redo`)만 쓰고, 그 화물의 `vessels`·`verdicts` 행은 다음 차례 `vessel` 노드가 코드로 지운다(D17). 모델은 요청만 한다. 한 차례에 토큰마다 다시 찾기는 한 번, 한 대화에서 토큰마다 2번까지(`rules/vessel.yaml redo_limit`)이고 세는 곳은 `vessel` 노드다. 도구의 상한 검사는 이른 부드러운 답일 뿐이다. 상한을 넘은 요청은 바깥 호출 없이 다음 답이나 카드가 상한에 닿았다고 말한다(D17). 지운 뒤의 찾기는 다음 차례의 `vessel` 노드가 한다. "모르겠어요"로 끝난 화물도 같다 | 모델이 반복해 되돌리면 같은 선택 카드가 계속 뜬다. 상한은 코드가 센다 | 같은 차례에는 다시 찾지 않는다(C6). 도구 결과가 "다음 차례에 그 화물을 말씀하시면 다시 찾아요"라고 말한다. 같은 차례에 바로 보이게 하려면 에이전트 뒤에서 `vessel` 노드로 되돌아가는 화살표가 필요하다. 이 계획에는 넣지 않는다 [추정] |
| C8 | 평가 실행기의 스위치는 `--vessel off\|on` 인자로만 켠다(기본 `off`). 환경 변수(`MARVIA_VESSEL`)로는 켜지지 않는다. 실행 인자와 그래프의 실제 모양이 다르면 `meta.problems`에 적어 무효로 만든다(`--graph`의 `graph_setting_problem`과 같은 방식 [실측 `src/marvia/eval/run.py:311`]). B의 시험 둘은 D13의 한 줄(허용 목록)만 고친다 | "켜졌는데 몰랐다"가 없게 한다 | 환경 변수로 쓰던 습관이 있으면 안 켜진 채 돈다. 인자가 없으면 무효가 아니라 꺼진 길이므로 `meta.vessel`이 늘 결과에 적힌다 |
| C9 | 수퍼바이저 길에는 새 도구를 주지 않는다(`rules/agent.yaml supervisor.subagents`의 도구 목록 그대로). 이번 측정에서도 뺀다 | 길 비교는 "구분 못 함"이었고 기본 길은 `agent`다 [문서 1113-comparison]. 서브에이전트 도구 설계는 따로 한다 | 스위치를 켜고 수퍼바이저 길을 쓰면 노드는 돌지만 모델이 도구를 못 쓴다. 판정 블록도 그 길에는 붙이지 않는다(6.2에서 확인) |
| C10 | 되돌리기와 상태 기억은 평가 문항이 아니라 그래프 시험이 본다 | 평가셋의 문항은 한 질문 한 차례다. 앞 차례의 배 확정이 필요한 흐름은 문항으로 만들 수 없다 [추정, 평가 구조를 더 읽어 확인] | 모델이 되돌리기를 부르는지는 평가로 못 본다 |
| C11 | 날짜만 받은 처음 알던 도착 예정은 그날 낮 12시(한국 시각)로 본다(`rules/vessel.yaml dates.first_eta_hour: 12`). 카드와 판정 블록이 "날짜만 받아 낮 12시로 봤어요"라고 적는다 | `judge`의 `first_eta`는 시각이고 정시·우려·지연을 시간 단위로 가른다 [실측 `src/marvia/tools/judge.py:67`] | 한 날 안의 어긋남은 지연으로 읽힐 수 있다. 날짜 단위 판정이 필요하면 judge의 일정 규칙을 따로 고친다 |
| C12 | 날짜의 범위: 오늘 앞뒤 365일(`dates.max_days`). 연도 없는 날짜(`11월 20일`)는 올해로 읽고, 오늘보다 `rules/vessel.yaml dates.past_grace_days`(7)일을 넘게 지난 날이면 내년으로 읽는다(숫자 7은 코드에 적지 않는다) | 판매 예정일은 대개 앞날이다. 지난 날은 `초과` 판정을 위해 받는다 | 연말에 지난 날을 말하면 내년으로 읽힌다 [추정]. 도구 결과가 읽은 날짜를 되풀이해 알아챌 수 있다 |
| C14 | **시계 하나.** 한 실행(평가 문항, 그래프 시험, 화면 시험)에는 기준 시각이 하나뿐이다. 모델이 보는 "Today", `note_dates`의 범위와 연도 없는 날짜 해석(C12), `judge`의 `now`가 모두 그 하나에서 나온다. 재생 배 자료와 판정 문항은 이미 관문을 지났으니 옮기지 않고 시계를 자료에 맞춘다: v4의 배 문항은 재생 배에 맞는 기준 시각(2026-09-22 쪽)을 문항마다 `Item.now`로 갖고, v3 30문항은 `as_of` 2026-11-06 그대로다. 화면 시험의 가짜 API도 `date.today` 대신 고정 시각을 쓴다. 날짜 문항(N09, N10, N12)은 이 시계로 날짜를 다시 맞춘다 **구현 방법은 D20이 정한다**: 켠 길만 `now`에서 오늘을 한 곳에서 만들고 공용 fixture 기본값은 그대로 둔다. | 지금은 셋이 다르다 [실측, 검증 11-16]: 평가 `as_of` 2026-11-06, 그래프 시험 대본 "Today is 2026-11-02", 가짜 API는 `date.today`이고 판정 `now`는 재생 배의 2026-09-22 쪽이다. 모델이 "오늘"과 도착 예정을 함께 보게 되면 어긋나고, `note_dates`가 `today`로 읽으면 "9월 25일"이 2027년으로 읽힌다 | 문항마다 시각이 달라 문항 파일이 늘어난다. 한 실행에서 둘을 섞어 해석하지 않는다(실행기는 문항의 시각을 쓴다) |
| D10 | **C1은 "꺼진 길 모델 입력이 `48ca3c5`와 같다"로 둔다** [결정 11-16, 실측]. `48ca3c5`를 `git archive`로 푼 사본에 B 끝의 `test_vessel_off.py`와 `tests/conftest.py`를 넣고 돌린 결과: 길 셋의 모델 입력(`MODEL_SHA`: 묶은 도구 순서, 호출마다 받은 메시지, 계획자·품목·작성자 프롬프트), `ask_user` 카드 답 차례(`ASK_SHA`), 그래프 모양, 화면 이벤트가 **B 끝과 바이트까지 같다**(덤프 대조). 같지 않은 것은 공책과 카드 칸 셋(`STATE_SHA`, `LOOPS_SHA`, `CARD_SHA`)이고 이유는 하나다: 8a 커밋 `cca0d74`가 `CargoFacts`에 빈 칸 여섯(`port_code`, `entry_date`, `loading_port`, `vessel_flag`, `voyage`, `shed`, 값은 모두 null)을 더했다. 모델에 주는 화물 줄(`cargo_lines`)은 단계·항구·단계 날짜만 쓰므로 모델 입력은 그대로다. `48ca3c5..2bc6073`에서 `graph/`, `prompts/`, `rules/agent.yaml`은 바뀌지 않았다(차이 0). **도구 결과 글도 돌려서 비교했다** [실측 11-16]: 두 사본(`48ca3c5`, `f208e59`)에서 에이전트 길에 가짜 모델이 `lookup_cargo`(알려진 토큰 둘 + 모르는 토큰), `calc_deadlines`, `watch_cargo`, `unwatch_cargo`(승인 재개 포함)를 부르게 하고, 모델이 받은 메시지 전체(도구 결과 포함, 26,172바이트)를 덤프해 `cmp`로 대조했더니 바이트까지 같다. 도구 결과 글은 `cargo_lines`(단계·항구·단계 날짜)와 기한 목록뿐이고 `CargoFacts` 전체를 덤프하는 도구는 없다(코드 읽기로도 `json.dumps`·`model_dump`는 품목 사실과 도구 결과 쪽뿐). 비교하지 않은 도구: `official_lookup`(웹 글), `search_law`, `get_provision`(RAG), `research`, `save_item_card`, `recall_memory`(품목 사실), `ask_user`는 `CargoFacts`를 안 다룬다 **(D15)** T1이 R-155의 넓힌 도구 결과 대본을 `48ca3c5` 사본에서도 돌아가는 데까지 돌려 차이를 이 행에 적는다. | 8b A부분은 모델 입력을 바꾸지 않았다는 증거를 꺼진 길 점검(가) 앞에 둔다 | 못 돌린 것: 같은 파일의 시험 둘(`eval 실행기`, `기본 설정이 꺼짐`)은 `Settings.vessel`과 평가 실행기 후크가 `48ca3c5`에 없어 실패한다(모델 입력이 아니라 B의 새 코드를 보는 시험). 위 셋의 해시는 `48ca3c5`에서 다르므로 8c 시험은 이 값들을 `48ca3c5`의 값이라 하지 않는다(그 셋은 B 끝 값) |
| D11 | T1의 새 시험은 **별도 파일** `tests/graph/test_vessel_off_inputs.py`에 둔다. B의 `tests/graph/test_vessel_off.py`는 8c에서 건드리지 않는다(T8은 D13의 한 줄(AST 시험의 허용 목록에 `("src/marvia/eval/run.py", "vessel")`)만 더하고 해시 상수는 움직이지 않는다. 그 밖의 실패는 고치지 말고 주인에게 묻는다) [결정 11-16] | B 관문의 해시가 B를 가리킨 채 남는다 | 파일이 둘이라 설명이 흩어진다 |
| D12 | `redo_vessel`은 내린 화물에서 다시 조회하지 않고 이유를 돌려준다 [결정 11-16, 11-13 내린 화물 판정, R-135]. 시험 하나가 "바깥 호출 0건 + 이유 글"을 `over_cap`(상한)과 따로 못박는다: `test_redo_on_a_landed_cargo_makes_no_outside_call_and_says_why` | 내린 화물의 배 값이 판정에 들어오면 멀쩡한 화물이 경계가 된다 | 사용자가 내린 화물의 배를 다시 보고 싶어도 못 본다 |
| D13 | **D11의 좁은 예외 하나 (R-153).** T8은 B의 `tests/graph/test_vessel_off.py`에서 `build_main_graph`에 `vessel=`을 키워드로 넘기는 파일의 허용 목록에 `("src/marvia/eval/run.py", "vessel")` 한 줄만 더한다(커밋 글에 이유). 그 파일의 해시 상수는 하나도 움직이지 않고 환경 변수 부분은 그대로다. 8c의 새 시험 파일(`test_vessel_off_inputs.py`)에 AST 검사를 하나 더한다: 저장소의 어느 `build_main_graph` 호출도 `**` 키워드를 넘기지 않는다(`**{"vessel": v}`로 이름을 숨겨 B의 검사를 피하는 길을 닫는다) [결정 11-16, R-153 수용] | `vessel`은 키워드 전용 인자라 `evaluate_item`이 넘기면 셋째 파일이 생겨 B의 시험이 깨진다 [실측 검증 M10: 2 실패]. 그대로 두고 통과하는 길은 이름 숨기기뿐이고 그것이 더 나쁘다 | 예외가 B 관문 시험을 건드린다. 한 줄이고 해시가 안 움직이므로 B가 가리키는 값은 그대로다 |
| D14 | **평가 지표 계산도 묶는다 (R-154).** T1은 `tests/test_vessel_base_not_wired.py`의 "평가 실행기" 묶음에서 `src/marvia/eval/dataset.py`, `metrics.py`, `run.py`, `scripts/run_eval.py` 넷을 이름으로 빼고 `retrieval.py`는 이름으로 남긴다. 대신 키 없는 시험을 더한다: 저장소에 있는 11-13 결과 열(`eval/results/agent-claude-haiku-5-5-a1.json`~`a5.json`, `supervisor-claude-haiku-5-5-s1.json`~`s5.json`, 모두 `meta.commit` 48ca3c5, v3)을 `run_eval.py verdict --set v3`로 다시 세면 커밋된 `eval/results/verdict-agent-supervisor-48ca3c5.json`과 모든 칸이 같다. 이 시험은 T1에서 처음부터 통과하고 8c의 지표 변경을 잡는다. 깨 보기 MC46 [결정 11-16, R-154 수용] | 묶음에서 빼기만 하면 `metrics.py`가 정확도·인용·호출 중앙값 계산을 바꿔도 측정 (가)가 놓친다 | 시험이 커밋된 결과 파일에 기댄다. 그 파일이 바뀌면 시험이 깨진다 |
| D15 | **꺼진 길의 도구 인자 꼴과 결과 글도 묶는다 (R-155).** T1의 새 해시는 "`TOOLS_SHA` 재사용"이 아니다. `TOOLS_FULL_SHA`: 꺼진 길에서 묶은 도구마다 `name` + `description` + `tool_call_schema.model_json_schema()`를, `web`(`MockTransport`)·`watch`를 넣은 가짜 deps로(R-149) 길마다 해시한다. 기대 도구 집합은 시험 안에 **글자로 적은 목록**이다(`make_tools` 출력과 견주지 않는다: 둘 다 같은 것을 빠뜨리면 같이 못 본다). `TOOL_RESULTS_SHA`: 11-16에 조사가 돌린 도구 결과 대본을 시험으로 커밋하고 꺼진 길의 도구 전부로 넓힌다. 도구마다 고정한 가공 인자로 한 번씩 부른다: `write_todos`, `calc_deadlines`, `ask_user`, `lookup_cargo`(조회 실패 줄 포함), `search_law`, `get_provision`, `check_reimport`, `save_item_card`, `recall_memory`, `save_preference`, `official_lookup`(`MockTransport`), `research`, `decline`, `watch_cargo`, `unwatch_cargo`. 모델이 받은 메시지 전체를 해시한다. 기대 값은 `f208e59`를 `git archive`로 푼 사본에서 낸다. `48ca3c5` 사본에서도 돌아가는 데까지 돌려 차이를 D10 행에 적는다 [결정 11-16, R-155 수용]. 깨 보기 MC35(인자 꼴), MC36(결과 글) | `tools.py`가 묶음에서 빠지면 도구 인자·설명·결과 글의 변경 10건이 모두 살아남는다 [실측 검증 M1~M9, M7b] | 도구 결과 글을 일부러 바꾸는 8c 밖의 계획이 이 해시를 다시 내야 한다. 그때 이유를 적는다 |
| D16 | **루프 공책의 합치는 방법 (R-156).** **합치는 함수(reducer)는 루프 공책(`LoopState`)에만 둔다.** 부모 공책(`MarviaState`)의 새 칸은 지금 코드의 방식대로 덮어쓰기다(부모는 루프가 끝난 뒤의 전체 값을 받아 덮어쓴다). 부모에도 합치는 함수를 두면 서브그래프가 돌려주는 전체 값이 차례마다 다시 더해진다 [실측 검증 탐침: 1, 2, 4]. 칸별 합치기: `cargo_dates`는 토큰별 dict 합치기, `vessel_redo`는 토큰별 **더하기**(한 모델 메시지에서 같은 토큰에 `redo_vessel`을 두 번 부르면 2), `turn_answers`는 덧붙이기. `turn_answers`는 서브그래프 상태에도 둔다(루프 안의 `ask_user`가 쓰고 `note_dates`가 읽는다). 루프 밖 노드(`find_vessels`의 비우기, `vessel` 노드의 소비 기록)는 부모 덮어쓰기라 그대로 된다. 시험: `test_two_turns_without_a_redo_call_leave_the_redo_count_unchanged`, `test_turn_answers_are_empty_at_the_start_of_the_next_turn`. 깨 보기 MC49(부모 칸에 더하기 합치는 함수). `vessels`·`verdicts`는 루프에 들이지 않는다(D17). 도구를 혼자 부르게 하는 길(`ALONE`)은 쓰지 않는다(호출 중앙값이 늘지 않게). 시험: 한 메시지에 두 호출이 둘 다 남는다, `turn_answers`가 부모에 닿는 것을 손으로 만든 공책이 아니라 **실제 `ask_user` 재개 길**로 본다. 깨 보기 MC37(`LoopState`에서 `turn_answers`를 뺌), MC38(한 메시지의 두 호출). **상한은 바깥 호출이 나가는 `vessel` 노드가 센다**(11-16 주인 판정): 도구의 상한 검사는 이른 부드러운 답일 뿐이다. 규칙은 D17에 있다. [결정 11-16, R-156 수용] | 서브그래프 상태에 없는 칸은 `Command`로 써도 오류 없이 버려지고 [실측 검증 탐침], 같은 단계에 덮어쓰기 칸을 둘이 쓰면 `InvalidUpdateError`다. 손으로 만든 공책을 쓰는 시험은 이 둘을 못 본다 | `create_agent` 루프에서 같은 단계 도구 실행과 버려짐이 같은지는 이 세션이 못 봤다(확인하지 못한 것 표) |
| D17 | **되돌리기와 트레이스 (R-157), D1의 예외 하나.** (1) `redo_vessel`은 토큰과 횟수(`vessel_redo`)만 쓰고 배 행을 `Command`에 싣지 않는다. 행은 다음 차례 `vessel` 노드가 지운다(공책 칸 하나를 더 둘 수 있다: 토큰별 "소비한 요청 수"를 "다시 찾은 횟수" 옆에 적는다. 모양은 작업이 T5에서 정한다 [결정 11-16]). (2) `trace._ship_values`가 `_walk`처럼 dataclass·pydantic·`Command`·`ToolMessage.artifact`를 걷게 고친다. (3) 켠 길 에이전트 루프 시험: 화물 둘 중 하나를 되돌리는 차례의 콜백이 받는 span 값(입력, 출력, 메타데이터)을 Langfuse가 하듯 **하나씩 따로** `scrub`에 넣고 결과마다 금지 목록(D23)을 찾아 가공 배의 이름·호출부호·번호가 하나도 남지 않는다. 한꺼번에 넣으면 고침 없이도 통과한다. 시험 이름: `test_each_span_payload_of_the_on_path_agent_loop_scrubs_clean_when_a_cargo_is_redone`. 깨 보기 MC39(되돌리기가 남은 행을 `Command`로 다시 씀: `test_redo_writes_only_the_token_and_the_count`가 잡는다), MC51(`_ship_values`를 dict·list만 걷는 옛것으로 되돌림: `test_scrub_walks_dataclass_pydantic_command_and_artifact`가 잡는다). **상한 규칙 [결정 11-16 주인 판정]**: 토큰마다 한 차례에 다시 찾기는 많아야 한 번이다(한 메시지에 `redo_vessel`이 몇 번이든). 한 대화에서 토큰마다 많아야 2번이고 세는 곳은 `vessel` 노드다. 상한을 넘은 요청은 바깥 호출을 하지 않고, 다음 답이나 카드가 "상한에 닿았다"고 말한다. 행동은 시험 넷으로 못박는다: (i) 한 메시지에서 한 토큰에 `redo_vessel` 셋 -> 그 차례 다시 찾기는 정확히 한 번, (ii) 대화 전체에서 토큰마다 다시 찾기는 2번 이하(노드가 센다), (iii) 상한에서의 요청은 바깥 호출 0건에 이유 글, (iv) 이미 소비한 요청은 새 호출 없이 뒤 차례에서 다시 처리되지 않는다. **아래쪽 시험(R-166)**: `test_after_three_calls_in_one_message_a_later_request_still_gets_the_second_refind`(1차례 한 메시지에 셋 -> 다시 찾기 1번, 2차례에 하나 -> 다시 찾기 둘째, 3차례에 하나 -> 바깥 호출 0과 상한 글). 노드는 요청 수가 아니라 **다시 찾은 횟수**로 상한을 센다. 도구의 부드러운 검사도 노드가 적은 다시 찾은 횟수를 읽는다. 깨 보기 MC50(노드가 요청 수를 셈). 깨 보기 MC47(i), MC48(iv). **(2)는 스위치 뒤가 아니다**: 값을 가리기만 하고 꺼진 길에는 모을 배 값이 없다. 증거: B의 `LOOPS_SHA` 불변, 그리고 꺼진 길의 `scrub` 출력이 고치기 전과 후에 바이트까지 같다는 시험(T1에서 처음부터 통과) [결정 11-16, R-157 수용] | `Command(update={"vessels": [행]})`, `[Command]`, `ToolMessage(artifact=...)` 안의 배 이름·호출부호가 지금 트레이스에 남는다 [실측 검증 탐침]. 되돌리기가 남은 행을 다시 쓰면 다른 화물의 배 값이 도구 끝 트레이스에 실린다 | 이것이 D1(모든 변화는 스위치 뒤)의 유일한 예외다. 가리는 값만 늘어난다 |
| D18 | **판정 블록의 ETA와 여유 일수 (R-158).** 블록은 ETA를 한국 날짜 `YYYY-MM-DD`로, 시각을 함께 쓸 때는 `HH:MM`(한국 시각)로 쓴다(UTC 그대로 쓰지 않는다). 검증자는 그 화물의 여유 일수(`margin_days`)를 `N일`로 허용한다. 규칙 (2)가 넓히는 것은 날짜만이 아니다. CC8 시험: 블록 줄을 그대로 옮긴 초안이 검증을 통과한다. 깨 보기 MC40(여유 일수 허용을 뺌) [결정 11-16, R-158 수용] | 검증자는 `N일`을 계산 결과·인용 글에서만 허용하고 `trusted_eta`는 시각이다. 그대로면 블록을 충실히 옮긴 답이 위반이 되어 고쳐 쓰기가 되풀이된다(N01, N09, N12) | 카드의 ETA 글은 TypeScript가 만들고 파이썬에는 같은 함수가 없다. 블록과 카드의 ETA 글이 같지 않을 수 있다. 같은 규칙 값(한국 날짜)으로 맞춘다 |
| D19 | **검증자를 부르는 자리를 묶는다 (R-159).** T1의 시험이 꺼진 길 셋에서 `main.verify`를 감싸 받은 인자를 적고 `verdicts is None`, `user_dates is None`임을 본다. 고정 초안 묶음은 `tests/graph/test_verify.py`의 경우들과 시험 파일 안에 적은 초안으로 한정한다(저장소 밖 파일을 쓰지 않는다). 깨 보기 MC41(꺼진 길이 `verdicts=[]`를 넘김) [결정 11-16, R-159 수용] | `VERIFY_SHA`는 함수의 결과만 묶고 부르는 자리를 묶지 않는다 | 없음 |
| D20 | **시계 (R-160), 켠 길만.** `build_main_graph(vessel=True)`가 `now`에서 오늘 날짜(`now().astimezone(KST).date()`)를 한 곳에서 만들어 brief, `make_tools`(`note_dates`), 검증자에 넘긴다. 꺼진 길은 `deps.today` 그대로다. 켠 길 시험은 `now`만 넘기고 공용 fixture의 기본값(`today`)은 바꾸지 않는다(바꾸면 brief의 Today가 달라져 B의 `MODEL_SHA`, `ASK_SHA`, `STREAM_SHA`가 깨진다). v3 문항의 `as_of`(날짜) D는 `now` = D 09:00 한국 시각으로 본다. CC14에 시험 하나: 서버처럼(덮어쓰지 않고) 만든 켠 그래프에서 brief의 Today = `now`의 한국 날짜. 꺼진 길의 서버 시간대는 배포 전 확인 항목이고 8c 범위가 아니다 [결정 11-16, R-160 수용] | 시계가 둘(`today`, `now`)이고 만드는 곳마다 달라서 서버 시간대가 UTC면 한국 0~9시에 모델의 Today와 판정 날짜가 하루 다르다 [추정, 검증: Cloud Run 시간대 안 봄] | 켠 길과 꺼진 길의 "오늘"을 만드는 방법이 다르다. 꺼진 길은 측정 기준선이라 건드리지 않는다 |
| D21 | **카드 답은 직접 적은 것만 (R-161).** `turn_answers`에는 `ask_user` 카드에서 사용자가 직접 적은(`custom`) 답만 들어간다. 고른 선택지의 글(모델이 쓴 `label`)은 들어가지 않는다. 시험: 고른 선택지에만 있는 날짜는 거절된다. 깨 보기 MC42(고른 선택지 글을 더함), MC45(`find_vessels`가 화물이 있을 때만 비움: 앞 차례 카드 답의 날짜를 화물 번호 없는 다음 차례에 받음) [결정 11-16, R-161 수용] | 고른 선택지를 받으면 모델이 계산한 날짜("다음 주 화요일" → 선택지 `2026-11-24`)를 사용자가 누르기만 해도 받는다. D4의 "사용자 자신의 글"과 다르다 | 사용자가 선택지를 눌러 답한 날짜는 받지 못하고 직접 적어 달라고 되묻는다 |
| D22 | **새 지표는 검증자와 따로, 문장 단위로 센다 (R-162, 사전 등록).** 탐지기: 한 문장에 화물 토큰, 또는 `등급`·`판정`·`확신` 낱말이 있고 그 문장에 등급 이름 또는 확신 이름이 있는데 그 화물의 `expect_verdict`와 다르면 1로 센다. 토큰 없는 문장은 화물이 하나면 그 화물에 대해, 여럿이면 어느 화물의 값과도 다를 때만 센다(주인 판정 11-16). **별도 보고 수 "귀속 못 한 문장"**: 화물이 여럿인 답에서 토큰 없이 등급 이름이나 확신 이름을 든 문장의 수. 통과 기준이 아니라 보고만 한다(사전 등록, 보고 전용). 이름 목록은 `rules/verdict.yaml`·`rules/vessel.yaml`의 글 이름이다. (나)의 통과 기준은 **탐지기 수 0**이고 검증자 꼴의 수를 옆에 적는다. 탐지기가 센 문장은 모두 문장째 나열한다. 탐지기 오류로 읽히는 것도 기준에는 세고 "탐지기 오류로 보임"이라고 표시만 한다. 나중에 빼지 않는다. 시험: "판정은 경계예요"가 주의 화물에 쓰이면 검증자는 지나가고 탐지기는 1을 센다 [결정 11-16, R-162 수용] | 새 지표가 검증자와 같은 눈이면 검증자가 이미 고친 것만 보고 "0"이 스스로를 증명한다 | 탐지기가 넓어서 올바른 답을 셀 수 있다. 그 비용을 기준 안에 두고 사람이 문장을 본다 |
| D23 | **판정 블록이 부르는 함수와 금지 목록 (R-163).** 블록은 카드가 쓰는 `view._verdict`의 칸과 `view._ship`에서 `name`·`call_sign`·`mmsi`를 뺀 칸을 쓴다. CC3의 금지 목록: 그 시험이 쓴 재생 파일의 모든 후보의 이름·호출부호·배 번호·IMO·MRN과 화물 사실의 `vessel_name`, 각각 대소문자·띄어쓰기를 지운 꼴까지. 깨 보기 MC43(블록에 `facts.vessel_name`) [결정 11-16, R-163 수용] | 화면 카드는 UNI-PASS의 `facts.vessel_name`도 보인다. 가공 재생 배만 찾으면 이 값이 새도 못 잡는다 | 없음 |
| D24 | **검증자 규칙 (1)의 화물 가리기 (R-164).** 시험: 화물 둘, 문장마다 토큰과 맞는 등급이면 통과하고 두 등급을 바꾸면 위반이다. 깨 보기 MC44(토큰이 있어도 첫 화물의 판정과 견줌) [결정 11-16, R-164 수용] | "토큰은 맞게 썼는데 등급은 다른 화물의 값"을 지금 시험 목록이 보지 않는다 [추정] | 없음 |
| C13 | 화면 변화는 작다: 카드의 날짜 줄 옆에 출처 글("말씀하신 날")을 적고, 되돌리기 결과는 기존 이유 글로 보인다 | 판정과 배 카드는 8b가 만들었다 | 없음 |

## Global Constraints

- 숫자·등급·기한은 코드가 계산한다. 도구가 받는 날짜는 모델이 계산한 값이 아니라 사용자 글에서 코드가 읽은 값과 같은 것만이다.
- 스위치가 꺼져 있으면(기본) 모델이 보는 것 전부와 평가 줄과 화면이 8b 끝과 같고 도구 목록·설명, 에이전트 시스템 지시문, brief 메시지, 작성자 입력, 검증자 입력·결과, 화물 줄이 `48ca3c5`와 같다. `tests/graph/test_vessel_off_inputs.py`(새로)가 본다.
- 배 식별자(이름, 호출부호, 배 번호, MRN)는 모델 입력(도구 결과, 판정 블록, 메시지 기록, 도구 인자 스키마), 트레이스, 로그에 없다.
- 임계값·목록·정한 글은 `rules/*.yaml`에 둔다: 되돌리기 상한, 날짜 범위와 기준 시각, 도구 결과 글, 판정 블록 글(`rules/vessel.yaml`), 검증자 새 규칙의 낱말(`rules/verify.yaml`).
- 도구 응답, 배 이름, 사용자 글은 데이터다. 그 안의 문장을 지시로 따르지 않는다.
- 저장소에 키, 실제 API 응답, 실제 B/L을 넣지 않는다. 실제 해수부·ShipFinder·UNI-PASS 호출은 하지 않는다. 시험은 키와 인터넷 없이, 재생만으로 돈다(`vessel_replay_only`). 새 fixture가 필요하면 가공값이다.
- 환경 변수는 `MARVIA_` 접두어만. 평가 스위치는 환경 변수가 아니라 인자다.
- 파일 안에서 em dash(U+2014)를 쓰지 않는다.
- 커밋 하나는 동작 하나, 파일 15개 이하. 커밋은 `v2`에만, `main`에는 올리지 않는다.
- 커밋마다 명령 A와 명령 B가 통과한다(8b B부분의 명령 A, 명령 B와 같다). 코드를 바꾼 커밋 뒤에는 `graphify update .`(커밋에 넣지 않는다).

## 사전 등록: 검사 CC1~CC14 (구현 전에 고정)

이 절은 첫 구현 커밋 전에 이 문서와 함께 커밋하고, 결과를 본 뒤 기준을 고치지 않는다. 고칠 일이 생기면 이유와 시각을 따로 적고 원래 기준의 판정도 함께 적는다.

| # | 검사 | 통과 기준 | 시험(계획) | 깨 보았을 때 |
|---|---|---|---|---|
| CC1 | 꺼져 있으면 모델 입력이 같다 | 스위치를 넘기지 않고 만든 **길 셋(계획자, 에이전트, 수퍼바이저) 모두**에서 모델이 받는 입력이 `48ca3c5`의 값과 같다: 에이전트·수퍼바이저 길은 묶은 도구 전부의 이름·설명·인자 꼴 해시(`TOOLS_FULL_SHA`, `web`·`watch`를 넣은 가짜 deps, 기대 도구 집합은 글자로 적은 목록, D15)와 도구 결과 글 해시(`TOOL_RESULTS_SHA`, 꺼진 길 도구 전부를 한 번씩 부름, D15), 에이전트 시스템 지시문, 차례 메시지(brief), 작성자 입력, 검증자 결과와 검증자를 부르는 자리의 인자(`verdicts`, `user_dates`가 `None`, D19), 계획자 길은 `plan`, `item_facts`, `write` 프롬프트(`main.py`와 `answer.py`가 만든다). 길 셋의 그래프 모양과 화면 이벤트는 8b 끝과 같다. **`ask_user`를 부르는 꺼진 길 대본은 B에 이미 있다**(`test_vessel_off.py`의 `ASK_SHA`, R-136): 8c는 그 값이 8c 커밋마다 그대로이고, 차례 뒤 공책에 `turn_answers`가 없음을 새 시험이 더 본다. 길 셋의 모델 입력 해시(`MODEL_SHA`, 계획자 품목 프롬프트 포함, R-150)와 번호 카드 해시(`CARD_SHA`)도 B 것을 그대로 쓴다. 새 시험은 B가 못 보는 것만 더한다: 위 두 해시(R-149, R-155), 검증자 결과(`VERIFY_SHA`)와 호출 자리(R-159), 평가 지표 재채점이 커밋된 `verdict-agent-supervisor-48ca3c5.json`과 같음(R-154, D14), `build_main_graph` 호출에 `**` 키워드가 없음(D13), 꺼진 길의 `scrub` 출력이 트레이스 고침 전후에 같음(D17) | `tests/graph/test_vessel_off_inputs.py`, `tests/test_vessel_base_not_wired.py` | T1 `51f7ae9`(`test_vessel_off_inputs.py` 여섯 시험, 값은 구현 기록). 꺼진 길의 B 해시와 T1 해시는 8c 모든 커밋에서 통과. 깨 보기 MC35, MC36, MC41, MC52, MC46이 깨진다 |
| CC2 | 도구는 켠 에이전트 길에만 | 스위치가 켜진 에이전트 길의 도구에 `read_vessel`, `note_dates`, `redo_vessel`이 있다. 꺼졌거나 수퍼바이저 길이면 없다. `rules/agent.yaml`의 서브에이전트 도구 목록은 바뀌지 않았다 | `tests/graph/test_vessel_tools.py` | T3~T5의 `make_tools(vessel=...)` 시험(`test_the_tool_exists_only_when_the_switch_is_on`)과 T1 `TOOLS_FULL_SHA`. 수퍼바이저 길은 도구를 바꾸지 않는다(`rules/agent.yaml` 그대로). `read_vessel`·`note_dates`·`redo_vessel`이 켠 에이전트 길에만 있다 |
| CC3 | 모델에 배 식별자가 없다 | 배를 확정·되묻기·되돌린 차례의 모델 입력 전체(도구 결과, 판정 블록, 메시지 기록, 도구 인자 스키마)에 배 이름, 호출부호, 배 번호, MRN이 없다. 이름에 지시 문장을 넣은 가공 재생 배(`QQ`로 시작하는 호출부호)로도 같다 **금지 목록**(D23): 시험이 쓴 재생 파일의 모든 후보의 이름·호출부호·배 번호·IMO·MRN과 화물 사실의 `vessel_name`, 대소문자·띄어쓰기를 지운 꼴까지. **트레이스**(D17): 켠 길 에이전트 루프에서 화물 둘 중 하나를 되돌리는 차례의 콜백 값(span의 입력·출력·메타데이터)을 하나씩 따로 `scrub`에 넣어도 가공 배의 이름·호출부호·번호가 남지 않는다. | `tests/graph/test_vessel_tools.py::test_ship_identifiers_never_reach_the_model_even_with_a_hostile_name` | `test_ship_identifiers_never_reach_the_model_even_with_a_hostile_name`, `test_the_block_never_has_a_candidates_name_call_sign_mmsi_imo_mrn_or_the_facts_vessel_name`(모델 입력 금지 목록에 화물 사실의 배 이름 포함), 트레이스는 `test_each_span_payload_of_the_on_path_agent_loop_scrubs_clean_when_a_cargo_is_redone`. 세관 배 이름의 트레이스 가림은 8c 전부터의 일이라 하지 않았다(사전 배포 항목) |
| CC4 | 날짜 받기 | 받는 것: 그 차례 사용자 글, 또는 그 차례 `ask_user` 카드에 사용자가 적은 답(같은 방식으로 가린 글)에 있는 절대 날짜와 같은 ISO 날짜, 같은 화물 토큰, 범위 안. 받지 않는 것(각각 이유 글이 다르다): 글에 없는 날짜, 상대 표현만 있는 글, 형식 오류, 범위 밖, 모르는 토큰, 이전 차례의 글에만 있는 날짜. 받은 날짜는 공책 `cargo_dates`에 남고 다음 차례에도 판정에 쓴다. 같은 칸을 다시 받으면 새 값으로 바꾼다. 받은 판매 예정일은 `judge`의 `sale_due`로 가서 여유 일수 등급이 열린다 카드 답은 **직접 적은(`custom`) 답만** 받고 고른 선택지 글은 받지 않는다(D21). 한 모델 메시지에 `note_dates`를 두 번 불러도 둘 다 남는다(D16). `turn_answers`가 부모에 닿는 것은 실제 `ask_user` 재개 길로 본다. | `tests/tools/test_user_dates.py`, `tests/graph/test_vessel_dates.py` | `tests/tools/test_user_dates.py`, `tests/graph/test_vessel_dates.py`(27개). 깨 보기 MC07~MC13, MC29, MC31, MC32, MC37, MC38, MC42, MC45가 깨진다 |
| CC5 | 읽기 도구 | 공책의 `vessels`, `verdicts`를 바꾸지 않는다. 모르는 토큰, 이번 차례에 배를 보지 않은 화물, "배를 확인한 뒤에" 상태를 각각 정한 글로 답한다. 돌려주는 글은 카드와 같은 글 함수를 쓴다 | `tests/graph/test_vessel_tools.py` | `test_read_vessel_does_not_change_the_notebook`와 `test_read_vessel_*`. MC14는 읽기 도구가 `Command`를 돌려주지 않는 구조라 변이를 만들지 않았다 |
| CC6 | 되돌리기 | 도구는 토큰과 횟수만 쓰고 배 행은 쓰지 않는다. 다음 차례 `vessel` 노드가 그 화물의 두 행만 지우고 다른 화물은 그대로다. 같은 토큰에 한 메시지에서 두 번 부르면 횟수가 2다(D16). 내린 화물의 되돌리기는 바깥 호출 0건에 이유 글을 돌려주고 상한 초과와 따로 시험한다(D12). 상한(2)을 넘으면 거절하고 행은 그대로다. 지운 뒤 다음 차례에 `vessel` 노드가 다시 찾고(요청이 나간다) "모르겠어요"로 끝난 화물은 선택 카드가 다시 뜬다. **에이전트 루프(`create_agent` 서브그래프) 안의 도구가 `Command`로 고친 값(`cargo_dates`, `vessel_redo`, `turn_answers`)이 부모 공책에 닿는다**(서브그래프 상태에 그 칸과 합치는 함수가 있어야 한다. `vessels`·`verdicts`는 루프에 들이지 않는다, D16·D17) | `tests/graph/test_vessel_tools.py`, `tests/graph/test_vessel_redo.py`(`test_a_command_update_from_inside_the_agent_loop_reaches_the_parent_notebook`, 칸마다) | `tests/graph/test_vessel_redo.py`(19개)와 DB 시험 `test_vessel_redo_db.py`(개발 DB, 다섯 차례 재시작 통과). 깨 보기 MC15, MC16, MC39, MC47~MC51, W11이 깨진다 |
| CC7 | 판정 블록 | 스위치가 켜졌고 판정이 있을 때만 작성자 입력과 brief에 붙는다. 글은 카드와 같다(같은 함수). 화물이 둘이면 토큰별 줄이다. 배 식별자는 없다. 판정이 없으면(조회 실패, 상한 초과) 그렇다고 쓴 줄이다 블록은 카드가 쓰는 `view._verdict`의 칸과 `view._ship`에서 `name`·`call_sign`·`mmsi`를 뺀 칸만 쓴다. ETA는 한국 날짜 `YYYY-MM-DD`(시각은 `HH:MM` 한국 시각)다(D18, D23). | `tests/graph/test_vessel_block.py` | `tests/graph/test_vessel_block.py`(10개). 깨 보기 MC18, MC19(두 꼴), W12가 깨진다 |
| CC8 | 검증자 새 규칙 | 규칙 넷 각각: 어긋나면 위반 문장을 돌려주고 맞으면 통과한다. 일상어("주의하세요", "경계를 넘어", "부분적으로")에는 걸리지 않는다. 판정 값이 없는 호출(스위치 꺼짐)에서는 새 규칙이 아무것도 보지 않고 결과가 8b 끝과 같다. 위반 문장에 실제 번호와 배 식별자가 없다 판정 블록 줄을 그대로 옮긴 초안은 통과한다. 블록의 여유 일수는 `N일`로 허용된다(D18). 화물 둘에서 문장마다 토큰과 맞는 등급이면 통과하고 두 등급을 바꾸면 위반이다(D24). 꺼진 길에서 검증자를 부르는 인자는 `verdicts=None`, `user_dates=None`이다(D19). | `tests/graph/test_verify_vessel.py` | `tests/graph/test_verify_vessel.py`(26개, 재생 화물 여덟 개의 블록 줄을 그대로 옮긴 초안 포함). 깨 보기 MC20~MC24, MC40, MC44, MC56이 깨진다 |
| CC9 | 지시문 조각 | 스위치가 켜지면 에이전트 시스템 지시문과 작성자 입력에 조각이 이어 붙고, 꺼지면 붙지 않는다. 조각은 `prompts/vessel_agent.md`, `prompts/vessel_write.md`에 있고 글에 배 식별자와 실제 번호가 없다 | `tests/graph/test_vessel_prompts.py` | `tests/graph/test_vessel_prompts.py`(6개). 깨 보기 MC02, MC03과 에이전트 지시문 조각을 늘 잇는 변이가 깨진다 |
| CC10 | 평가 실행기 | `--vessel on`이면 켠 그래프, `off`면 끈 그래프다. 환경에 `MARVIA_VESSEL=on`이 있어도 인자가 없으면 끈 그래프다. 인자와 그래프가 다르면 `meta.problems`에 적힌다. `meta.vessel`과 기준 시각이 결과에 적힌다. B의 `test_vessel_off.py`는 T8이 AST 시험의 허용 목록에 `("src/marvia/eval/run.py", "vessel")` 한 줄만 더하는 것(D13) 말고는 고치지 않고 해시 상수는 하나도 움직이지 않는다. 인자 있는 실행기는 이 행의 새 시험이 본다. 새 시험 파일의 AST 검사: `build_main_graph` 호출이 `**` 키워드를 넘기지 않는다 | `tests/eval/test_run_vessel.py`, `tests/graph/test_vessel_off.py` | `tests/graph/test_run_vessel.py`(11개). B의 `test_vessel_off.py`는 허용 목록 한 줄만 고쳤고 해시 상수는 그대로다. 깨 보기 MC25~MC28이 깨진다 |
| CC11 | 평가셋 v4 | v3 30문항은 질문과 나머지 칸이 같다(시험이 비교). 새 문항 12개. 해시 동결, 독립 대조 기록. `--vessel off` 실행은 v3 30문항만 돈다(새 문항은 켠 길 전용). 새 지표(판정 이름 어긋남, 단정 어구 위반, 배 값 포함 새는 번호)가 문항 줄에서 센다 **판정 이름은 검증자와 별도 탐지기로 센다**(D22): 문장 단위 탐지기 수 0이 기준이고 검증자 꼴의 수를 옆에 적는다. 탐지기가 센 문장은 모두 문장째 나열하고 탐지기 오류로 보여도 기준에서 빼지 않는다. 시험: "판정은 경계예요"(주의 화물)는 검증자를 지나고 탐지기는 1을 센다. | `tests/eval/test_dataset.py`, `tests/eval/test_metrics_vessel.py` | `tests/eval/test_dataset.py`, `tests/eval/test_metrics_vessel.py`. 동결 해시 `62969fde…`. 깨 보기 MC27, MC54, MC55, X10, X11이 깨진다 |
| CC12 | 화면 | 날짜 줄에 출처 글이 보이고 기존 그림 셋이 바이트까지 같다(기본 실행). `E2E_VESSEL=on` 실행의 새 흐름이 통과한다. 타입 검사 오류 0 | `web/e2e/flows.spec.ts`, `tsc --noEmit` | Docker 화면 시험: 켠 실행 7 통과(새 흐름 포함), 기본 실행 7 통과. 기본 실행 뒤 `choice.png` 한 픽셀 떨림이 있어 되돌렸다. 타입 검사는 이미지 빌드(`next build`)가 한다. R-185로 까닭 글이 바뀌어 그 글이 보이는 그림이 있으면 e2e 뒤에 다시 만든다(아직 안 돌림) |
| CC14 | 시계 하나 | 한 실행에서 모델이 보는 "Today", `note_dates`의 범위·연도 해석, `judge`의 `now`가 같은 시각이다. v4 배 문항은 문항의 `now`(2026-09-22 쪽)를 쓰고 v3 문항은 `as_of`(2026-11-06)를 쓴다. 가짜 API는 `date.today`를 쓰지 않는다. 연도 없는 날짜가 문항의 시계 기준 해로 읽힌다 **서버처럼(덮어쓰지 않고) 만든 켠 그래프에서 brief의 Today = `now`의 한국 날짜**다(D20). 꺼진 길은 `deps.today` 그대로다. v3 문항의 `as_of` D는 `now` = D 09:00 한국 시각이다. | `tests/graph/test_vessel_clock.py`, `tests/eval/test_run_vessel.py` | `test_an_on_graph_built_like_the_server_reads_today_from_now_in_kst`(`now` 09-26 16:00 UTC로 바꿈), `test_note_dates_reads_a_year_less_date_on_the_korean_date_not_the_utc_date`, `test_the_writers_prompt_has_todays_korean_date_from_now`, 계획자 길, 수퍼바이저 서브에이전트. 깨 보기 MC28~MC30, MC53, V03, V05가 깨진다 |
| CC13 | 새 측정 (사전 등록 수치, 아래 "측정") | 아래 표 | `scripts/run_eval.py verdict --set v4 --compare vessel` | 측정 뒤 채움 |

깨 보기 목록(구현 뒤 사본에서 한 곳씩 바꾸고 관련 시험을 돌려 처음 틀린 시험을 적는다. 결과는 구현 뒤 채운다):

| # | 바꿀 곳 | 잡아야 하는 검사 |
|---|---|---|
| MC01 | 스위치 꺼짐에서도 도구 셋을 목록에 넣음 | CC1, CC2 |
| MC02 | 꺼짐에서도 brief에 판정 블록을 붙임 | CC1 |
| MC03 | 꺼짐에서도 작성자 입력에 조각을 이어 붙임 | CC1, CC9 |
| MC04 | 수퍼바이저 길의 서브에이전트 도구에 새 도구를 넣음 | CC2 |
| MC05 | 도구 결과에 배 이름을 넣음 | CC3 |
| MC06 | 판정 블록에 호출부호를 넣음 | CC3 |
| MC07 | `note_dates`가 글에 없는 날짜를 받음 | CC4 |
| MC08 | 상대 표현을 모델이 바꾼 날짜로 받음 | CC4 |
| MC09 | 이전 차례의 글에서도 날짜를 찾음 | CC4 |
| MC10 | 범위 검사를 뺌 | CC4 |
| MC11 | 연도 없는 날짜를 늘 올해로 읽음 | CC4 |
| MC12 | 받은 판매 예정일을 `judge`에 넘기지 않음 | CC4 |
| MC13 | `first_eta`를 날짜 그대로(시각 없이) 넘겨 오류 | CC4 |
| MC14 | 읽기 도구가 공책을 바꿈 | CC5 |
| MC15 | 되돌리기가 다른 화물의 행도 지움 | CC6 |
| MC16 | 되돌리기 상한을 뺌 | CC6 |
| MC17 | 되돌린 뒤에도 `kept` 행이 남아 다시 찾지 않음 | CC6 |
| MC18 | 판정 블록이 카드와 다른 글을 씀 | CC7 |
| MC19 | 판정이 없는 화물에 이전 판정 줄을 붙임 | CC7 |
| MC20 | 검증자 규칙 (1)의 등급 이름 비교를 뺌 | CC8 |
| MC21 | 규칙 (2)의 허용 날짜에 판정 ETA를 넣지 않음 | CC8 |
| MC22 | 규칙 (3)의 "확실이 아님" 조건을 뒤집음 | CC8 |
| MC23 | 규칙 (4)를 뺌 | CC8 |
| MC24 | 규칙 (1)의 패턴을 "주의" 낱말만으로 넓힘(일상어 오탐) | CC8 |
| MC25 | `--vessel` 없이 환경 변수로 켜짐 | CC10 |
| MC26 | 인자와 그래프가 달라도 무효로 두지 않음 | CC10 |
| MC27 | `--vessel off`에서 새 문항을 돌림 | CC11 |
| MC28 | 기준 시각을 실제 시계로 둠 | CC10, CC14 |
| MC29 | `note_dates`가 문항의 시각이 아니라 `date.today()`로 범위와 연도를 읽음 | CC14 |
| MC30 | 모델에 보이는 "Today"와 `judge`의 `now`가 다른 시계에서 나옴 | CC14 |
| MC31 | 같은 차례 `ask_user` 카드 답에서 날짜를 읽지 않음 | CC4 |
| MC32 | 에이전트 서브그래프 상태에서 `cargo_dates` 칸을 뺌(부모에 닿지 않음) | CC6 |
| MC34 | 꺼진 길에서도 `ask_user`가 카드 답을 `turn_answers`에 더함 | CC1 |
| MC33 | 계획자 길의 `write` 프롬프트에 판정 블록을 꺼짐에서도 붙임 | CC1 |
| MC35 | 꺼진 길 도구 하나의 인자 꼴을 바꿈(선택 인자 하나 더함) | CC1 (D15) |
| MC36 | 꺼진 길 도구 하나의 결과 글을 바꿈(대본이 부르지 않던 도구) | CC1 (D15) |
| MC37 | `LoopState`에서 `turn_answers`를 뺌 | CC4, CC6 (D16) |
| MC38 | `note_dates` 두 번을 한 메시지로 부르면 하나가 사라짐 | CC4 (D16) |
| MC39 | `redo_vessel`이 남은 배 행을 `Command`로 다시 씀 | `test_redo_writes_only_the_token_and_the_count` (D17, R-167) |
| MC40 | 검증자에서 판정의 여유 일수 허용을 뺌 | CC8 (D18) |
| MC41 | 꺼진 길 `main.py`가 `verdicts=[]`를 넘김 | CC1 (D19) |
| MC42 | 고른 선택지 글을 `turn_answers`에 넣음 | CC4 (D21) |
| MC43 | 블록에 화물 사실의 `vessel_name`을 넣음 | CC3 (D23) |
| MC44 | 규칙 (1)이 토큰이 있어도 첫 화물의 판정과 견줌 | CC8 (D24) |
| MC45 | `find_vessels`가 화물이 있을 때만 `turn_answers`를 비움 | CC4 (D21) |
| MC46 | `metrics.py`의 행동 정확도 계산을 바꿈 | CC1 (D14) |
| MC47 | 한 차례에 한 토큰의 다시 찾기를 `redo_vessel` 호출 수만큼 함(한 번으로 줄이지 않음) | 되돌리기 시험 (i) (D17) |
| MC48 | 소비한 요청을 지우지 않아 뒤 차례에 다시 처리함 | 되돌리기 시험 (iv) (D17) |
| MC49 | 부모 공책의 `vessel_redo`·`turn_answers`에 더하기·덧붙이기 합치는 함수 | `test_two_turns_without_a_redo_call_leave_the_redo_count_unchanged`, `test_turn_answers_are_empty_at_the_start_of_the_next_turn` (D16) |
| MC50 | `vessel` 노드가 다시 찾은 횟수 대신 요청 수로 상한을 셈 | `test_after_three_calls_in_one_message_a_later_request_still_gets_the_second_refind` (D17) |
| MC51 | `_ship_values`를 dict·list만 걷는 옛것으로 되돌림 | `test_scrub_walks_dataclass_pydantic_command_and_artifact` (D17) |
| MC52 | `_ship_values`가 모든 dict의 `name`을 모음 | 꺼진 길 `scrub` 전후 같음 (T1 (바), D17) |
| MC53 | 켠 길 검증자가 `deps.today`를 받음 | `test_an_on_graph_built_like_the_server_reads_today_from_now_in_kst` (D20) |
| MC54 | 탐지기: 여러 화물·토큰 없는 문장을 하나와만 달라도 셈 | T9의 두 화물 탐지기 시험 (D22) |
| MC55 | 귀속 못 한 수를 기준 수에 더함 | T9의 귀속 못 한 수 시험 (D22) |
| MC56 | 검증자가 모든 `N일`을 허용 | `test_a_day_count_that_is_not_that_cargos_margin_days_is_still_flagged` (D18) |

## 측정 (사전 등록 수치, 결과를 보기 전에 고정)

조건은 11-13 본 측정과 같다: `claude -p`(`MARVIA_LLM_VIA=cli`), Haiku 5.5, `git archive`로 뽑은 사본에서 실행, 측정 DB `marvia_measure`(단위 집합과 글 해시가 코퍼스와 같음을 실행 전에 확인), UNI-PASS 재생. 더해지는 조건: 해수부·ShipFinder 재생, 판정 기준 시각 고정. 새 측정 커밋은 8c 끝에서 태그 `ckpt/measure-8c`를 단다. 무효 규칙(`meta.problems`가 비어 있지 않음 = 무효, 같은 번호로 많아야 3번), 점수를 보고 다시 돌리지 않음, 사용량 한도 꼴의 실패는 무효로 두고 알린 뒤 기다림, 실행 전 `ccusage blocks --active --json`의 활성 블록 값을 적고 $450을 넘으면 블록이 끝날 때까지 기다림도 그대로다 [문서 1113-comparison].

| 측정 | 내용 | 통과 기준 |
|---|---|---|
| (가) 끈 길 점검 한 번 | 8c 끝 커밋으로 `--vessel off --set v3` | 행동 정확도가 **0.8333 이상**이면 통과(11-13 에이전트 다섯 실행의 최솟값 0.8667에서 한 문항을 뺀 값). 밑이면 다섯 쌍에 앞서 원인부터 본다. 높게 나오는 것은 문제가 아니다. [왜] 다섯 실행의 최솟값~최댓값 범위는 문제가 없어도 약 1/3 확률로 벗어난다(검증 추정: 교환 가능하다고 보면 새 실행이 범위 밖일 확률 2/6). 이 한 번은 새 측정이 아니라 "꺼진 길이 그대로"를 확인하는 점검이다 |
| (나) 켠 길 대 끈 길 | 같은 커밋·DB·모델·v4 문항으로 `--vessel on`과 `--vessel off`를 번갈아 다섯 쌍. 에이전트 길만. 끈 길 실행은 v3 30문항만 돈다 | 아래 표 |

(나)의 기준(켠 길 다섯 실행 평균 대 끈 길 다섯 실행 평균, v3 30문항):

| 지표 | 기준 |
|---|---|
| 행동 정확도 | 켠 길이 끈 길보다 1/12(0.0833)를 넘어 낮지 않다 |
| 정답 인용 | 같은 폭 |
| 호출 중앙값 | 켠 길이 끈 길의 1.25배 이내 (v3 문항은 배 단계가 노드라 모델 호출이 거의 늘지 않아야 한다) |
| 새 문항(켠 길만, 12개) | 행동 정확도 다섯 실행 평균 0.80 이상 [추정 시작값, 결과 보기 전에 고정] |
| 새는 번호 | 0 (배 값 포함) |
| 판정 이름 어긋남(문장 단위 탐지기, D22) | 0. 검증자 꼴의 수를 옆에 적는다. 탐지기가 센 문장은 모두 나열하고 탐지기 오류로 보이는 것도 기준에서 빼지 않는다 |
| 단정 어구 위반 | 0 |
| 도구 상한에 닿은 줄 | 0 |
| 오류, 무효 실행 | 0 |

기준을 넘어도 스위치 기본값은 `off`로 둔다(켜는 것은 주인이 정한다). 넘지 못하면 문항별로 어디서 틀렸는지(행동, 인용, 도구 선택) 본다. 시간은 에이전트 한 실행이 약 19분이었다 [실측 11-13] 켠·끈 열 실행이면 약 3시간 반이다 [추정, 새 문항이 늘면 더]. 구독 CLI라 비용은 재지 않는다.

---

## 파일 구조 (계획)

| 파일 | 하는 일 | Task |
|---|---|---|
| `tests/graph/test_vessel_off_inputs.py` (새로) | 꺼져 있으면 모델 입력이 같다 | 1 |
| `tests/test_vessel_base_not_wired.py`, `tests/graph/test_vessel_off.py` | 평가 실행기 묶음에서 네 파일을 이름으로 뺌(T1). B의 AST 시험 허용 목록에 한 줄(T8, D13) | 1, 8 |
| `src/marvia/trace.py` | `_ship_values`가 dataclass·pydantic·`Command`·`ToolMessage.artifact`도 걷게(D17, 스위치 뒤가 아닌 유일한 변경) | 5 |
| `src/marvia/tools/user_dates.py` (새로) | `absolute_dates(text, today) -> set[date]` | 2 |
| `tests/tools/test_user_dates.py` (새로) | 날짜 읽기 | 2 |
| `src/marvia/graph/state.py`, `src/marvia/graph/vessel.py` | 공책 칸 `cargo_dates`, `vessel_redo`, verdict 노드가 날짜를 `judge`에 넘김 | 3 |
| `src/marvia/graph/tools.py` | `make_tools(..., vessel=False)`와 도구 셋(`read_vessel`, `note_dates`, `redo_vessel`) | 3, 4, 5 |
| `src/marvia/graph/main.py` | `make_tools`에 스위치를 넘김, brief와 write에 판정 블록과 조각을 붙임 | 4, 6 |
| `src/marvia/graph/vessel_text.py` (새로) | 판정 블록 `vessel_lines(...)`. 카드와 같은 글 함수를 부른다 | 4 |
| `rules/vessel.yaml` | `redo_limit`, `dates`, 도구 결과 글, 판정 블록 글 | 3~5 |
| `prompts/vessel_agent.md`, `prompts/vessel_write.md` (새로) | 켠 길에만 이어 붙는 조각 | 6 |
| `src/marvia/graph/agent.py` | 에이전트 시스템 지시문에 조각을 잇는 자리(스위치가 켜졌을 때만) | 6 |
| `src/marvia/graph/verify.py`, `rules/verify.yaml` | `verify(..., verdicts=None, user_dates=None)`, 새 규칙 종류와 낱말 | 7 |
| `src/marvia/eval/run.py`, `scripts/run_eval.py` | `--vessel`, 메타, 기준 시각, 무효 규칙 | 8 |
| `eval/set_v4.yaml`, `.sha256`, `eval/gold_check_v4.md`, `src/marvia/eval/dataset.py`, `metrics.py` | 평가셋 v4, `Item`의 새 칸, 새 지표 | 9 |
| `src/marvia/view.py`, `web/components/CargoCards.tsx`, `web/lib/agui.ts`, `web/e2e/flows.spec.ts` | 날짜 출처 글, 되돌리기 글 | 10 |
| `README.md`, 설계, 모듈 머리 주석 | 문서(검증자 머리의 "위치 조회가 없어서" 문장 포함) | 11 |

---

### Task 0: 사전 등록

- [ ] **Step 1**: 이 문서를 `docs/plans/2026-11-16-marvia-v2-plan-8c.md`로 커밋한다. 아래 코드 커밋보다 먼저다.

```bash
git add docs/plans/2026-11-16-marvia-v2-plan-8c.md
git commit -m "docs: 계획 8c 모델이 배 판정을 읽고 쓰게 함 (결정, 사전 등록 검사 CC1~CC14, 측정 기준)"
```

### Task 1: "꺼져 있으면 모델 입력이 같다"를 먼저 고정한다 (CC1)

**배울 것:** 8b에서 해시를 동작 시험으로 바꾼 것과 같다. 바꾸기 전에 값을 낸다. 모델이 보는 모든 입력(도구 목록·설명, 시스템 지시문, brief 메시지, 작성자 입력, 검증자 결과)을 가짜 모델로 모아 해시로 적어 두고, 8c가 그 입력을 바꾸지 않았음을 매 커밋에서 본다.

**Files:** Create `tests/graph/test_vessel_off_inputs.py`; Modify `tests/test_vessel_base_not_wired.py`(8c가 고치는 파일만 해시 묶음에서 빼고 이 시험으로 대신한다: `graph/tools.py`, `graph/main.py`, `graph/agent.py`, `graph/verify.py`, `rules/verify.yaml`, 고치는 `graph/answer.py`가 있으면 그것. **"평가 실행기" 묶음에서는 `src/marvia/eval/dataset.py`, `metrics.py`, `run.py`, `scripts/run_eval.py` 넷을 이름으로 빼고 `retrieval.py`는 이름으로 남긴다**(D14). **고치지 않는 파일은 통째로 빼지 않고 이름으로 해시를 남긴다**: 기존 `prompts/` 파일들, 고치지 않는다면 `rules/agent.yaml`. 새 `prompts/vessel_*.md`는 묶음에 없다).

**Interfaces:** Consumes: `build_main_graph`, `agent_deps`, 가짜 모델의 메시지 기록. Produces: (가) `TOOLS_FULL_SHA`: 꺼진 길에서 묶은 도구마다 `name`, `description`, `tool_call_schema.model_json_schema()`, `web`(`MockTransport`)·`watch`를 넣은 가짜 deps(R-149), 길마다. 기대 도구 집합은 시험 안의 글자로 적은 목록이다(`make_tools` 출력과 견주지 않는다). 이전 판의 "`TOOLS_SHA`(기존 값 재사용)"는 `web`·`watch`를 넣으면 성립하지 않아 새 이름과 새 값으로 적는다. (나) `TOOL_RESULTS_SHA`: 조사가 11-16에 돌린 도구 결과 대본을 시험으로 커밋하고 꺼진 길의 도구 전부로 넓힌다: `write_todos`, `calc_deadlines`, `ask_user`, `lookup_cargo`(조회 실패 줄 포함), `search_law`, `get_provision`, `check_reimport`, `save_item_card`, `recall_memory`, `save_preference`, `official_lookup`(`MockTransport`), `research`, `decline`, `watch_cargo`, `unwatch_cargo`를 도구마다 고정한 가공 인자로 한 번씩 부르고 모델이 받은 메시지 전체를 해시한다. 기대 값은 `f208e59`를 `git archive`로 푼 사본에서 낸다. `48ca3c5` 사본에서도 돌아가는 데까지 돌려 차이를 D10 행에 적는다(D15). (다) 검증자: 꺼진 길 셋에서 `main.verify`를 감싸 `verdicts is None`, `user_dates is None`을 본다. `VERIFY_SHA`는 `tests/graph/test_verify.py`의 경우들과 시험 파일 안에 적은 초안만으로 만든 **고정 묶음**에 `verify(..., verdicts=None)`을 돌린 결과 전체의 해시다(저장소 밖 파일을 쓰지 않는다, D19). (라) 재채점: `eval/results/`의 11-13 결과 열(`agent-claude-haiku-5-5-a1`~`a5`, `supervisor-claude-haiku-5-5-s1`~`s5`)을 `run_eval.py verdict --set v3`로 다시 세면 `verdict-agent-supervisor-48ca3c5.json`과 모든 칸이 같다(D14, 키 없음). (마) AST: 저장소의 어느 `build_main_graph` 호출도 `**` 키워드를 넘기지 않는다(D13). (바) 꺼진 길의 `scrub` 출력 해시가 트레이스 고침(T5) 전후에 같다(D17, T1에서 처음부터 통과). 입력은 꺼진 길 세 길의 한 차례 동안 콜백이 받는 span 값 전부(도구 호출이 든 `AIMessage`, `ToolMessage`, 도구가 돌려준 `Command`, `Send`, 품목 카드 저장·읽기 포함: (나)의 `TOOL_RESULTS_SHA` 대본과 같은 대본)를 하나씩 `scrub`한 결과다(R-168). 깨 보기 MC52(`_ship_values`가 모든 dict의 `name`을 모음). **B의 해시는 재사용한다(R-136, R-150)**: B 끝의 `tests/graph/test_vessel_off.py`가 `MODEL_SHA`(길 셋의 묶은 도구 **이름** 순서, 호출마다 받은 메시지 전체, 계획자·품목·작성자 프롬프트), `CARD_SHA`, `ASK_SHA`를 이미 가졌다 [실측 `f208e59`]. 시스템 지시문, brief, 작성자 입력은 `MODEL_SHA`의 메시지 기록에 들어 있으므로 새로 해시하지 않는다 [추정, `Recorder`가 모든 메시지를 적음]. 이 파일은 B의 시험이 8c 커밋마다 그대로 통과함을 지키고 `ASK_USER_OFF_SHA`를 따로 두지 않는다(B의 `ASK_SHA`). **그 세 값은 `48ca3c5`가 아니라 `2bc6073`에서 다시 낸 값이다.** `48ca3c5`와 같다는 증거는 B의 시험이 아니라 D10의 사본 비교다. **"T1은 B의 해시를 재사용하고 B가 못 보는 것만 더한다"는 반만 맞았다**: B가 못 보는 것은 도구 인자 꼴, 대본이 부르지 않는 도구의 결과 글, 검증자를 부르는 자리, 평가 지표 계산이고 위 (가)~(라)가 더한다.

- [ ] **Step 1: 시험을 쓴다.** 기대 값은 `f208e59` 사본에서 낸다. 같은 시험을 `48ca3c5` 사본에서도 돌아가는 데까지 돌려 차이를 D10 행에 적는다. 다르면 고치지 말고 무엇이 달라졌는지부터 본다.
- [ ] **Step 2: 확인:** 명령 A, 명령 B. 이 시험은 코드를 바꾸기 전 상태를 묶으므로 처음부터 통과한다.
- [ ] **Step 3: 커밋** `test: 고정 묶음에서 8c가 고치는 파일만 빼고 꺼진 길의 도구 인자·결과 글, 검증자 호출 자리, 평가 지표 재채점을 시험으로 대신 묶음`

### Task 2: 사용자 글에서 절대 날짜를 읽는 함수 (CC4의 바닥)

**배울 것:** 날짜를 읽는 일은 모델이 아니라 코드가 한다. 읽을 수 있는 꼴을 좁게 두고, 읽지 못하는 것은 읽지 않는다(지어내지 않는다).

**Files:** Create `src/marvia/tools/user_dates.py`, `tests/tools/test_user_dates.py`.

**Interfaces:** Produces: `absolute_dates(text: str, today: date) -> set[date]`. 읽는 꼴: `YYYY-MM-DD`, `YYYY.MM.DD`, `YYYY/MM/DD`, `YYYY년 M월 D일`, `M월 D일`, `M/D`. 연도가 없으면 `today`의 해로 읽고 `today`보다 `dates.past_grace_days`(7)일을 넘게 지난 날이면 내년으로 읽는다(C12). 없는 날짜(`11월 31일`)는 버린다. 상대 표현과 시각은 읽지 않는다. 숫자 덩어리 안의 `M/D`(`2026/11/20`의 뒷부분, 분수, 금액)는 읽지 않는다. 마스크 토큰(`[BL1]`)과 8자리 번호는 날짜가 아니다.

- [ ] **Step 1: 실패하는 시험.** 이름과 기준: `test_each_written_form_is_read`(여섯 꼴 모두), `test_a_year_less_date_is_this_year_or_next_when_it_is_more_than_a_week_past`, `test_an_impossible_date_is_dropped`, `test_relative_words_are_not_read`(내일, 모레, 다음 주 화요일, 이번 달 말), `test_a_date_inside_a_number_is_not_read`(`2026111999`, `3/4분기`는 읽지 않음), `test_two_dates_in_one_text_are_both_read`.
- [ ] **Step 2: 코드.**
- [ ] **Step 3: 확인:** 명령 A, 명령 B.
- [ ] **Step 4: 커밋** `feat(tools): 사용자 글에서 절대 날짜만 읽는 함수. 상대 표현과 없는 날짜는 읽지 않음`

### Task 3: 날짜 받기 (CC4, 결정 C5, C11, C12)

**배울 것:** 모델이 넘기는 값은 코드가 걸러야 한다. 거르는 기준은 모델의 말이 아니라 사용자의 글이다. 거절은 이유를 도구 결과로 돌려주어 모델이 사용자에게 되묻게 한다.

**Files:** Modify `src/marvia/graph/state.py`(칸 `cargo_dates: dict[str, dict]`, `vessel_redo: dict[str, int]`, `turn_answers: list[str]`), `src/marvia/graph/agent.py`(에이전트 서브그래프 상태에도 `cargo_dates`, `vessel_redo`, `turn_answers`를 둔다. 합치는 함수: `cargo_dates` dict 합치기, `vessel_redo` 토큰별 더하기, `turn_answers` 덧붙이기. `vessels`·`verdicts`는 루프에 들이지 않는다, D16·D17), `src/marvia/graph/tools.py`(`make_tools(..., vessel: bool = False)`, `note_dates`), `src/marvia/graph/main.py`(`make_tools`에 `vessel`을 넘김), `src/marvia/graph/vessel.py`(verdict 노드가 `cargo_dates`를 `judge`에 넘김), `rules/vessel.yaml`(`dates`: `max_days`, `past_grace_days`, `first_eta_hour`, 받은 값과 거절 이유 글); Test `tests/graph/test_vessel_dates.py`.

**Interfaces:** Consumes: `absolute_dates`, 공책 `masked_text`와 그 차례 `ask_user` 카드의 답(공책 칸 `turn_answers: list[str]`: 켠 길에서만 `ask_user`가 직접 적은(`custom`) 답을 가려 더하고(고른 선택지 글은 더하지 않는다, D21) `find_vessels`가 차례 처음에 비운다. `start` 노드는 건드리지 않는다), 차례의 기준 시각(C14), `cargos`, `mask_map`, `judge(sale_due, first_eta, forwarder_eta)`. Produces: 도구 `note_dates(token: str, sale_date: str | None = None, forwarder_eta: str | None = None, first_eta: str | None = None) -> Command`(스위치가 켜졌을 때만 목록에 있음). 공책 `cargo_dates[token] = {"sale_date": "YYYY-MM-DD", "forwarder_eta": ..., "first_eta": ...}`(받은 칸만). 도구 결과는 받은 칸을 "판매 예정일 2026-11-20(말씀하신 날)"처럼 되풀이하고, 거절한 칸은 이유를 적는다(`not_in_text`, `relative`, `bad_format`, `out_of_range`, `unknown_token`). 거절한 칸은 공책에 쓰지 않는다. 받은 칸이 하나도 없으면 공책이 그대로다. 판정은 차례마다 `cargo_dates`를 읽어 `sale_due`(날짜), `forwarder_eta`(날짜), `first_eta`(날짜 + `first_eta_hour`시 한국 시각)로 넘긴다.

- [ ] **Step 1: 실패하는 시험.** `test_a_date_the_user_wrote_this_turn_is_accepted`, `test_a_date_not_in_this_turns_text_is_refused`(모델이 지어낸 날짜), `test_a_relative_expression_is_refused_with_a_reason_the_model_can_relay`, `test_a_date_only_in_an_earlier_turn_is_refused`, `test_an_unknown_token_is_refused`, `test_out_of_range_is_refused`, `test_a_second_call_replaces_the_value`, `test_only_the_accepted_fields_are_written`(한 호출에 받은 칸과 거절한 칸이 섞임), `test_the_sale_date_reaches_the_judge_and_changes_the_margin_grade`(재생 화물 `TESTVSL0001`, 판매 예정일을 도착 예정 가까이로), `test_first_eta_is_read_as_that_days_noon_in_korea`, `test_the_tool_exists_only_when_the_switch_is_on`, `test_a_date_the_user_typed_into_an_ask_user_card_this_turn_is_accepted`, `test_a_year_less_date_is_read_against_the_turns_clock_not_the_real_today`. 추가(R-156, R-161, D20): `test_two_note_dates_calls_in_one_message_both_survive`, `test_turn_answers_reaches_the_parent_through_a_real_ask_user_resume`(손으로 만든 공책이 아니라 실제 재개 길), `test_a_date_only_in_a_picked_option_is_refused`, `test_an_on_graph_built_like_the_server_reads_today_from_now_in_kst`(`now` = 2026-09-21 16:00 UTC, 한국 시각 9월 22일 01:00을 넣는다. 실제 날짜, fixture의 `today`(2026-11-02), UTC 날짜 모두와 다르다. brief의 Today, 연도 없는 날짜 해석, 검증자가 허용하는 오늘 셋을 함께 본다, R-169). 추가(R-171): `test_a_card_answer_from_an_earlier_turn_is_refused_in_a_turn_without_cargo`(1차례 카드에 날짜를 적고 2차례는 화물 번호 없는 글, 모델이 그 날짜로 `note_dates` -> 거절. MC45를 잡는다).
- [ ] **Step 2: 코드.**
- [ ] **Step 3: 확인:** 명령 A, 명령 B. T1의 시험이 그대로 통과한다.
- [ ] **Step 4: 커밋** `feat(graph): 날짜 받기 도구. 그 차례 사용자 글에 있는 절대 날짜만 받고 판정의 판매 예정일·처음 알던 도착 예정·포워더 날로 넘김`

### Task 4: 읽기 도구와 판정 블록 (CC5, CC7, 결정 C2, C3, C6)

**배울 것:** 글을 만드는 함수가 둘이면 카드와 답이 어긋난다. 카드의 글을 만드는 함수를 그대로 불러 블록을 만든다. 모델에게는 코드가 쓴 글만 간다.

**Files:** Create `src/marvia/graph/vessel_text.py`; Modify `src/marvia/graph/tools.py`(`read_vessel`), `src/marvia/graph/main.py`(brief 메시지에 `<vessel_lines>`를 켰을 때만 더함), `rules/vessel.yaml`(블록 머리와 줄 글); Test `tests/graph/test_vessel_block.py`, `tests/graph/test_vessel_tools.py`.

**Interfaces:** Produces: `vessel_lines(cargos, vessels, verdicts) -> list[str]`(토큰마다 한 줄: 토큰, 배 확인 상태 글, 등급·확신·일정 글, 믿을 ETA와 출처, 켜진 신호 글, 까닭·참고 글. 배 식별자 없음. 카드가 쓰는 `view._verdict`의 칸과 `view._ship`에서 `name`·`call_sign`·`mmsi`를 뺀 칸만 쓰고, ETA는 한국 날짜 `YYYY-MM-DD`와 `HH:MM`(한국 시각)이다, D18·D23). `read_vessel(tokens: list[str]) -> str`(공책을 바꾸지 않는다. 모르는 토큰은 "모르는 토큰", 이번 차례에 배를 보지 않은 화물은 `not_looked` 글, 선택 카드 중인 화물은 "배를 확인한 뒤에" 글). 블록은 스위치가 켜졌고 `verdicts` 또는 `vessels`가 있을 때만 brief에 붙는다.

- [ ] **Step 1: 실패하는 시험.** `test_the_block_uses_the_same_words_as_the_card`(카드 함수 출력과 블록 줄을 같은 입력에서 견줌), `test_the_block_has_no_ship_identifiers`, `test_two_cargos_make_two_token_lines`, `test_no_verdict_says_so_instead_of_reusing_an_old_line`, `test_the_block_is_absent_when_the_switch_is_off`, `test_read_vessel_does_not_change_the_notebook`, `test_read_vessel_says_not_looked_for_a_cargo_found_this_turn_by_the_loop`, `test_a_landed_cargo_block_says_the_customs_stage_only`(R-148), `test_ship_identifiers_never_reach_the_model_even_with_a_hostile_name`(CC3, 호출부호가 `QQ`로 시작하고 이름에 지시 문장이 든 가공 재생 배). 추가(R-158, R-163): `test_the_block_eta_is_a_kst_date_and_time`(UTC 0~9시 도착도 한국 날짜), `test_the_block_never_has_a_candidates_name_call_sign_mmsi_imo_mrn_or_the_facts_vessel_name`(대소문자·띄어쓰기를 지운 꼴까지, 해당 재생 파일의 모든 후보).
- [ ] **Step 2: 코드.**
- [ ] **Step 3: 확인:** 명령 A, 명령 B.
- [ ] **Step 4: 커밋** `feat(graph): 읽기 도구와 판정 블록. 블록의 글은 화물 카드와 같은 함수에서 오고 배 식별자는 싣지 않음`

### Task 5: 되돌리기 (CC6, 결정 C7)

**배울 것:** 상태를 지우는 일은 코드가 하고, 모델은 요청만 한다. 상한은 코드가 센다.

**Files:** Modify `src/marvia/graph/tools.py`(`redo_vessel`), `src/marvia/trace.py`(D17), `src/marvia/graph/vessel.py`(다음 차례 `vessel` 노드가 되돌림 요청이 있는 화물의 행을 지움), `rules/vessel.yaml`(`redo_limit: 2`, 결과 글); Test `tests/graph/test_vessel_redo.py`, `tests/graph/test_vessel_tools.py`.

**Interfaces:** Produces: `redo_vessel(token: str) -> Command`. **토큰과 횟수만 쓴다**: `vessel_redo[token]`을 하나 올리고 배 행은 쓰지 않는다(D17). 그 토큰의 `vessels`·`verdicts` 행은 다음 차례 `vessel` 노드가 지운다. 내린 화물이면 바깥 호출 없이 이유 글을 돌려준다(D12). 상한을 넘으면 행은 그대로이고 거절 글을 돌려준다. 도구 결과는 "다음 차례에 그 화물을 말씀하시면 다시 찾아요"(C7).

- [ ] **Step 1: 실패하는 시험.** `test_redo_clears_only_that_cargos_rows`, `test_redo_stops_after_the_limit_and_keeps_the_rows`, `test_after_redo_the_next_turn_looks_the_ship_up_again`(바깥 요청이 다시 나감), `test_a_cargo_that_ended_as_dont_know_asks_again_after_redo`(선택 카드가 다시 뜸), `test_redo_of_an_unknown_token_is_refused`, `test_the_count_survives_turns`, `test_a_command_update_from_inside_the_agent_loop_reaches_the_parent_notebook`(`cargo_dates`, `vessel_redo`, `turn_answers` 칸마다. `vessels`·`verdicts`는 루프에 들이지 않는다). 추가(D12, D16, D17): `test_three_redo_calls_on_one_token_in_one_message_make_exactly_one_refind`(i), `test_refinds_per_token_per_conversation_never_exceed_the_limit_counted_at_the_node`(ii), `test_a_request_at_the_cap_makes_no_outside_call_and_the_next_answer_says_so`(iii), `test_a_consumed_request_is_never_processed_again_on_a_later_turn`(iv), `test_the_refind_count_and_the_consumed_request_field_survive_a_checkpointer_round_trip_across_two_turns`(DB 필요: `EncryptedSaver`(`graph/live.py`)를 개발용 시험 DB에 붙여 기존 DB 시험(`tests/graph/test_postgres_checkpoint.py`가 `live_memory`로 saver를 만드는 방식)과 같게 돌리고, 두 차례 사이 재개 뒤에도 노드가 센 다시 찾기 횟수와 소비한 요청 칸이 남아 상한이 유지됨을 본다. DB가 필요한 시험으로 표시해 키·DB 없는 묶음에서는 건너뛴다), `test_redo_writes_only_the_token_and_the_count`, `test_two_redo_calls_on_one_token_in_one_message_count_two`(도구가 쓰는 요청 수는 2, 다시 찾기는 한 번), `test_redo_on_a_landed_cargo_makes_no_outside_call_and_says_why`(상한 초과와 따로), `test_the_trace_scrub_leaves_no_ship_value_in_the_on_path_agent_loop_when_a_cargo_is_redone`, `test_scrub_walks_dataclass_pydantic_command_and_artifact`, `test_the_off_path_scrub_output_is_byte_equal_before_and_after`. 위 `test_redo_clears_only_that_cargos_rows`는 다음 차례 `vessel` 노드의 삭제로 본다. DB 시험의 확인 칸에 `turn_answers`(다음 차례 비움)와 `cargo_dates`도 넣는다(R-173).
- [ ] **Step 2: 코드.**
- [ ] **Step 3: 확인:** 명령 A, 명령 B.
- [ ] **Step 4: 커밋** `feat(graph): 되돌리기 도구. 토큰과 횟수만 쓰고 배·판정 행은 다음 차례에 지우며 한 화물당 두 번까지만`

### Task 6: 지시문 조각과 작성자·에이전트 입력 (CC9, CC1)

**배울 것:** 지시문 한 벌을 고치면 꺼진 길도 달라진다. 조각을 켠 길에만 이어 붙인다.

**Files:** Create `prompts/vessel_agent.md`, `prompts/vessel_write.md`; Modify `src/marvia/graph/agent.py`(시스템 지시문에 조각을 이음), `src/marvia/graph/main.py`(작성자 입력에 조각과 블록을 이음); Test `tests/graph/test_vessel_prompts.py`.

**Interfaces:** 에이전트 조각은 세 도구를 언제 쓰는지(판정을 물으면 `read_vessel`, 사용자가 날짜를 말하면 `note_dates`, 틀렸다고 하면 `redo_vessel`), 상대 표현이면 날짜로 다시 말해 달라고 할 것, 배 이름을 물으면 카드를 보라고 할 것을 쓴다. 작성자 조각은 판정 블록의 값을 바꾸지 말 것, 등급 없음을 지어내지 말 것, 확신이 "확실"이 아니면 단정하지 말 것을 쓴다. 두 조각 모두 배 식별자와 실제 번호가 없다.

- [ ] **Step 1: 실패하는 시험.** `test_the_fragments_are_added_only_when_the_switch_is_on`, `test_the_fragments_have_no_ship_identifiers_or_numbers`, `test_the_off_prompts_are_unchanged`(T1의 해시), `test_the_writer_input_has_the_block_when_a_verdict_exists`.
- [ ] **Step 2: 지시문과 코드.**
- [ ] **Step 3: 확인:** 명령 A, 명령 B.
- [ ] **Step 4: 커밋** `feat(graph): 켠 길에만 이어 붙는 지시문 조각과 작성자 입력의 판정 블록`

### Task 7: 검증자 새 규칙 넷 (CC8, 결정 C4)

**배울 것:** 같은 낱말도 화물의 상태에 따라 틀리기도 맞기도 한다. 규칙이 상태를 받아야 한다. 일상어를 막지 않도록 "등급"·"확신" 옆의 이름만 본다.

**Files:** Modify `src/marvia/graph/verify.py`(`verify(..., verdicts: list[dict] | None = None, user_dates: set[str] | None = None)`), `rules/verify.yaml`(`vessel` 절: 등급·확신 이름 패턴 틀, 단정 어구 목록, 위반 글), `src/marvia/graph/main.py`(검증 노드가 `verdicts`와 `cargo_dates`를 넘김. 스위치가 꺼져 있으면 `None`을 넘긴다), 검증자 머리말(위치 규칙을 하지 않는다는 문장을 고침); Test `tests/graph/test_verify_vessel.py`.

**Interfaces:** 규칙 (1): 답에서 `등급(은|이|을|도)? <등급 이름>` 또는 `<등급 이름> 등급`, `확신(은|이)? <확신 이름>`이 나오고 그 문장이 가리키는 화물(토큰이 있으면 그 토큰, 없고 화물이 하나면 그 화물, 없고 화물이 둘 이상이며 값이 다르면 "어느 화물인지 토큰으로 쓴다")의 판정 값과 다르면 위반. 규칙 (2): 허용 날짜에 판정의 믿을 ETA(한국 날짜)와 `user_dates`(받은 날짜)를 더하고, 그 화물의 여유 일수(`margin_days`)를 `N일`로 허용한다(D18). 다른 날짜는 기존 규칙이 이미 막는다. 규칙 (3): `confidence != sure`이거나 배 상태가 `user_choice`인 화물의 문장에 단정 어구(`확실히`, `분명히`, `틀림없이`, `반드시`, `100%` 등, 목록은 yaml)가 있으면 위반. 규칙 (4): 등급이 없는 화물의 문장에 등급 이름 + 등급 꼴이 있으면 위반. `verdicts`가 `None`이면 새 규칙은 아무것도 보지 않는다.

- [ ] **Step 1: 실패하는 시험.** 규칙마다 걸리는 예와 걸리지 않는 예 한 쌍 이상: `test_a_wrong_grade_name_next_to_the_word_grade_is_a_violation`, `test_the_right_grade_name_passes`, `test_everyday_words_do_not_trip_the_rule`("주의하세요", "경계를 넘어", "부분적으로"), `test_a_confidence_name_that_differs_is_a_violation`, `test_two_cargos_with_different_grades_need_a_token`, `test_an_eta_date_in_the_block_is_allowed_and_another_date_is_not`, `test_a_date_the_user_gave_is_allowed`, `test_assertive_words_about_a_partial_cargo_are_a_violation`, `test_assertive_words_about_a_sure_cargo_pass`, `test_a_grade_for_a_cargo_without_grade_is_a_violation`, `test_without_verdicts_the_result_is_that_of_the_old_verify`(CC1의 한 조각), `test_violations_name_no_real_numbers_or_ship_values`. 추가(D18, D19, D24): `test_a_draft_quoting_the_block_lines_verbatim_passes`, `test_the_margin_days_of_that_cargo_are_allowed_as_n_days`, `test_two_cargos_token_matched_grades_pass_and_swapped_grades_fail`, `test_the_verifier_is_called_without_verdicts_on_all_three_off_paths`(T1의 감싸기 시험과 같은 것). 추가(R-172): `test_a_day_count_that_is_not_that_cargos_margin_days_is_still_flagged`(그 화물의 여유 일수가 아닌 `N일`과 다른 화물의 여유 일수는 여전히 걸림). `test_a_draft_quoting_the_block_lines_verbatim_passes`는 재생 화물 `TESTVSL0001`~`0008`의 실제 판정에서 만든 블록 전부로 돌린다(신호 글·참고 글에 숫자가 섞이는 경우까지). 깨 보기 MC56(검증자가 모든 `N일`을 허용).
- [ ] **Step 2: 코드.**
- [ ] **Step 3: 확인:** 명령 A, 명령 B.
- [ ] **Step 4: 커밋** `feat(graph): 검증자가 판정 값을 받아 등급·확신 이름, 도착 날짜, 단정 어구, 등급 없음의 등급을 막음`

### Task 8: 평가 실행기의 `--vessel` (CC10, 결정 C8)

**배울 것:** 켜는 길은 눈에 보여야 한다. 인자로만 켜고, 실제 그래프가 인자와 다르면 무효로 둔다. 판정 기준 시각도 고정해 날마다 값이 달라지지 않게 한다.

**Files:** Modify `scripts/run_eval.py`(`--vessel off|on`), `src/marvia/eval/run.py`(`evaluate_item(..., vessel)`, `meta.vessel`, 기준 시각, 무효 규칙), `tests/graph/test_vessel_off.py`(D13: 허용 목록에 `("src/marvia/eval/run.py", "vessel")` 한 줄만. 해시 상수는 움직이지 않는다), `src/marvia/graph/main.py`(`build_main_graph(vessel=True)`가 `now`에서 오늘을 한 곳에서 만들어 brief·`make_tools`·검증자에 넘김, D20); Test `tests/eval/test_run_vessel.py`.

**Interfaces:** `evaluate_item(item, ..., vessel: bool = False)`가 `build_main_graph(vessel=vessel)`을 부른다. `run_problems`는 인자와 그래프의 `vessel` 노드 유무가 다르면 문제로 적는다. 결과 `meta`에 `vessel`(`off`/`on`), 판정 기준 시각, 배 재생 폴더 해시가 적힌다. 기준 시각은 문항마다 하나다(C14): v3 문항은 문항 파일의 `as_of`(2026-11-06), v4 배 문항은 `Item.now`(재생 배의 마지막 위치 수신 30분 뒤, 2026-09-22 쪽, 8b 가짜 API와 같다). 모델의 "Today", `note_dates`, `judge`의 `now`가 모두 이 시각에서 나온다. 가짜 API(`e2e/fake_api.py`)는 `date.today` 대신 이 시각을 쓴다. 그래프 시험의 공용 `agent_deps` 기본값(`today` 2026-11-02)은 바꾸지 않는다(바꾸면 brief의 Today가 달라져 B의 `MODEL_SHA`, `ASK_SHA`, `STREAM_SHA`가 깨진다). 켠 길 시험은 `now`만 넘긴다. v3 문항의 `as_of` D는 `now` = D 09:00 한국 시각이다(D20). Test에 `tests/graph/test_vessel_clock.py`를 더한다.

- [ ] **Step 1: 실패하는 시험.** `test_the_argument_turns_the_graph_on_and_only_the_argument`, `test_the_environment_alone_never_turns_it_on`, `test_a_mismatch_between_the_argument_and_the_graph_is_a_problem`, `test_the_meta_records_the_switch_and_the_clock`, `test_off_run_inputs_equal_the_previous_ones`(T1과 같은 해시를 실행기 길로).
- [ ] **Step 2: 코드.**
- [ ] **Step 3: 확인:** 명령 A, 명령 B.
- [ ] **Step 4: 커밋** `feat(eval): 평가 실행기의 --vessel 인자. 환경 변수로는 켜지지 않고 인자와 그래프가 다르면 무효`

### Task 9: 평가셋 v4와 새 지표 (CC11, 결정 C10)

**배울 것:** 평가셋은 한 번 쓰면 바꾸지 않는다. v3를 복사해 문항만 더하고 더한 이유를 적는다. 정답은 문항을 만든 쪽이 아니라 독립으로 대조한다.

**Files:** Create `eval/set_v4.yaml`, `eval/set_v4.sha256`, `eval/gold_check_v4.md`; Modify `src/marvia/eval/dataset.py`(`Item.vessel_only: bool = False`, `Item.replies: list[...]`(선택 카드에 줄 답), `Item.expect_verdict: {grade, confidence} | None`, `Item.now: datetime | None`: v4 배 문항의 기준 시각, C14), `src/marvia/eval/metrics.py`(판정 이름 어긋남은 검증자 꼴과 문장 단위 탐지기 둘을 따로 센다, 단정 어구 위반, 배 값 포함 새는 번호. 탐지기 정의는 D22, 센 문장은 문장째 나열), `scripts/run_eval.py`(`verdict --set v4 --compare vessel`); Test `tests/eval/test_dataset.py`, `tests/eval/test_metrics_vessel.py`.

새 문항 12개(켠 길 전용, 재생 화물 `TESTVSL0001~0007`. 질문 글은 구현 때 쓴다. 날짜 문항의 날짜는 `Item.now`(2026-09-22 쪽)를 기준으로 `rules/verdict.yaml`의 여유 일수 기준에서 계산해 고정한다):

| 번호 | 보는 것 | 화물 | 선택 카드 답 | 기대 판정 |
|---|---|---|---|---|
| N01 | 배 확정 뒤 판정을 답에 정확히 말하는가 | `TESTVSL0001` | 없음 | 순항, 확실 |
| N02 | 같은 이름의 배에서 하나를 고름, 확신이 부분이고 단정 없음 | `TESTVSL0002` | 1번 | 부분 |
| N03 | 같은 이름의 배에서 "모르겠어요", 지어내지 않음 | `TESTVSL0002` | 0번 | 등급 없음 |
| N04 | 후보 없음, 등급을 지어내지 않음 | `TESTVSL0003` | 없음 | 등급 없음 |
| N05 | 서류로만 확정(위치 없음), 확신 부분 | `TESTVSL0004` | 없음 | 부분 |
| N06 | 입항 신고가 없어 되묻는 화물, "모르겠어요" | `TESTVSL0005` | 0번 | 등급 없음 |
| N07 | 내린 화물, 배 이야기를 하지 않고 통관 단계로 답함 | `TESTVSL0006` | 없음 | 등급은 통관 신호만 |
| N08 | 서류로 가르는 길에서 호출부호가 같은 두 배 가운데 하나를 고름, 상한이 걸림 | `TESTVSL0007` | 1번 | 부분 |
| N09 | 판매 예정일을 절대 날짜로 말함, 도구로 옮겨져 여유 일수 등급이 바뀜 | `TESTVSL0001` | 없음 | 날짜에 따른 등급 |
| N10 | 판매 예정일을 상대 표현으로 말함, 받지 않고 날짜로 다시 말해 달라고 함 | `TESTVSL0001` | 없음 | 날짜 없는 판정 |
| N11 | 두 화물(하나는 내린 화물), 토큰별로 말함 | `TESTVSL0001` + `TESTVSL0006` | 없음 | 화물별 |
| N12 | 처음 알던 도착 예정을 절대 날짜로 말함, 일정 칸이 열림 | `TESTVSL0001` | 없음 | 일정 칸 |

되돌리기와 상태 기억은 문항이 아니라 그래프 시험이 본다(C10). 주입은 모델에 배 이름이 가지 않으므로 문항이 아니라 CC3 시험이 본다.

- [ ] **Step 1: 실패하는 시험.** `test_v4_keeps_the_v3_items_unchanged`, `test_the_vessel_items_are_marked_and_skipped_when_off`, `test_the_set_hash_is_frozen`, `test_the_metric_counts_a_wrong_grade_name_in_the_answer`, `test_the_metric_counts_assertive_words_for_a_partial_cargo`, `test_ship_values_count_as_leaks`. 추가(D22): `test_the_detector_counts_a_wrong_name_the_verifier_pattern_misses`("판정은 경계예요"가 주의 화물에 쓰이면 검증자는 지나고 탐지기는 1), `test_the_detector_lists_every_hit_sentence`, `test_a_hit_that_looks_like_a_detector_error_still_counts`. 추가(R-170): `test_the_detector_on_two_cargos_counts_a_tokenless_sentence_only_when_it_differs_from_every_cargo`(화물 둘 주의·경계: 토큰 없이 "판정은 경계예요" 0, "판정은 순항이에요" 1), `test_the_unattributed_count_is_reported_and_not_added_to_the_criterion`(두 문장 모두 토큰 없음 -> 귀속 못 한 수 2, 기준 수에 더해지지 않음). 깨 보기 MC54(하나와만 달라도 셈), MC55(귀속 못 한 수를 기준에 더함). R-173: v4 배 비교는 따로 길(`--compare vessel`)로 만들고 v3 판정 출력(`verdict-agent-supervisor-48ca3c5.json`과 견주는 칸)에는 칸을 늘리지 않는다(D14의 재채점 시험이 깨지지 않게).
- [ ] **Step 2: 평가셋과 코드. 독립 대조 기록을 쓴다(8b까지의 `gold_check_v3.md`와 같은 방식).**
- [ ] **Step 3: 확인:** 명령 A, 명령 B. `scripts/run_eval.py report`로 키 없이 요약 표가 나오는지 본다.
- [ ] **Step 4: 커밋** `feat(eval): 평가셋 v4(v3에 배 식별 문항 열둘)와 판정 이름·단정 어구·배 값 새는 번호 지표`

### Task 10: 화면 (CC12, 결정 C13)

**Files:** Modify `src/marvia/view.py`(날짜 줄의 출처 글), `web/components/CargoCards.tsx`, `web/lib/agui.ts`, `web/e2e/flows.spec.ts`(`E2E_VESSEL=on` 묶음에 날짜 받기 한 흐름), `rules/vessel.yaml`(출처 글).

- [ ] **Step 1: 시험.** `tests/graph/test_vessel_screen.py`에 날짜 줄의 출처 글 시험, 화면 시험에 새 흐름 하나.
- [ ] **Step 2: 코드.**
- [ ] **Step 3: 확인:** 명령 A, 명령 B, `npx tsc --noEmit`, 화면 시험 두 실행(8b와 같은 명령). 기본 실행 뒤 기존 그림 셋이 바이트까지 같아야 한다.
- [ ] **Step 4: 커밋** `feat(web): 화물 카드의 날짜 줄에 말씀하신 날이라는 출처를 보임`

### Task 11: 문서

**Files:** Modify `README.md`, 설계 문서 6.5절과 10절과 변경 기록, 검증자 머리말("위치 조회가 없는 계획 3a에서는 하지 않는다" 문장), `prompts/` 설명이 있는 곳.

- [ ] **Step 1: 고친다.** 두 문서 파일에 em dash가 없는지 본다.
- [ ] **Step 2: 확인:** 명령 A, 명령 B.
- [ ] **Step 3: 커밋** `docs: 배 판정을 모델이 읽고 쓰는 길과 평가셋 v4, 측정 기준을 README와 설계에 적음`

### Task M: 측정 (코드 커밋이 아니다)

- [x] **Step 1:** 8c 끝 커밋을 `git archive`로 뽑은 사본에 `ckpt/measure-8c` 태그를 달기 전에 모든 검사가 통과하고 B 검토의 고침이 들어간 상태인지 본다. 태그는 주인이 정한 뒤에 단다.
- [x] **Step 2:** 측정 DB의 단위 집합과 글 해시가 코퍼스와 같음을 확인한다.
- [x] **Step 3: (가)** `--vessel off --set v3` 한 번. 판정: 그 실행의 v3 행동 정확도를 기존 보고 출력(`scripts/run_eval.py report`)에서 읽어 `rules/vessel.yaml comparison.off_floor`(0.8333) 이상이면 통과다. 이 한 번은 새 측정이 아니라 "끈 길이 그대로"를 확인하는 점검이다. 통과하지 못하면 Step 4(다섯 쌍)를 시작하지 않고 주인 쪽(`메인`)에 보고하고 멈춘다. 원인부터 본다.
- [x] **Step 4: (나)** 켠 길과 끈 길을 번갈아 다섯 쌍. 실행 전마다 `ccusage blocks --active --json`을 적는다.
- [x] **Step 5:** `scripts/run_eval.py verdict --set v4 --compare vessel`의 출력을 그대로 `.claude/run/research/`의 보고서에 붙인다. 기준을 보고서에서 고치지 않는다.

## B 고침이 8c 계획에 미친 영향 (11-16, 기준 `f208e59`)

기준을 `partb6`에서 `f208e59`로 옮기며 코드와 대조한 결과다 [실측: `git show f208e59:<파일>` 읽기만]. 지운 것 없이 모두 적는다.

| B 고침 | 8c 계획에 미친 영향 | 처리 |
|---|---|---|
| R-136, R-150 (`test_vessel_off.py`의 `MODEL_SHA`, `CARD_SHA`, `ASK_SHA`, 계획자 품목 프롬프트) | CC1과 T1이 겹친다. 이전 판은 `ask_user` 대본이 B에 없다고 적었으나 B에 있다 | 틀린 문장을 고침. T1은 B 해시를 재사용하고 B가 못 보는 것(R-149의 묶은 도구 전부, `VERIFY_SHA`, `turn_answers`가 없음)만 더한다. T1의 `ASK_USER_OFF_SHA`는 B의 `ASK_SHA`로 바뀜 |
| R-136 머리말: 세 값은 `2bc6073`에서 다시 냄 | 8c의 "꺼진 길 모델 입력은 `48ca3c5`와 같다"를 B가 보증하지 않는다 | 11-16에 비교를 마침(D10): 모델 입력은 같고 공책 칸만 다르다. C1은 그대로 |
| R-149 (검증) | `agent_deps` 가짜에 `web`, `watch`가 없다 | T1에 반영 완료 |
| R-147 `same_call_sign_many_mmsi` (`tools/vessel_match.py`, `rules/vessel.yaml`) | 선택 카드 후보의 `check` 글과 N02·N08(같은 이름·같은 호출부호)에서 확신 상한이 부분인 이유 | 8c의 판정 블록은 후보 `check`를 쓰지 않고(배 식별자 없음) 판정의 확신·`cap_note`만 쓴다. N08과 `TESTVSL0008` 시험이 이 글을 본다 |
| R-148 `landed` (`rules/verdict.yaml` `info.landed`, `view.py`의 `landed` 칸) | 내린 화물의 판정은 `info=["landed"]`, 일정 없음, 등급은 통관 신호만이다. 이전 판 T4는 이 경우를 이름으로 정하지 않았다 | T4의 `vessel_lines`가 `info`의 `landed` 글(`verdict.yaml`)을 그대로 쓰고 "배 이야기를 하지 않음"을 N07과 `test_a_landed_cargo_block_says_the_customs_stage_only`가 본다. 검증자의 "등급 없는 화물" 규칙은 `landed` 화물을 등급 없음으로 오판하지 않는지 시험을 더함 |
| R-135 `watches_ship(stage)` (`tools/signals.py`, `graph/vessel.py`, `tools/judge.py`) | 내린 화물은 `find_vessel`이 `{"status": "unknown", "reason": "landed"}`를 돌리고 판정이 위치·일정 호출을 안 한다 | `read_vessel`의 `not_looked` 글과 `landed`를 구별한다(내린 화물은 "배를 보지 않음(내림)", 상한 때문에 못 본 화물은 `over_cap`). 되돌리기(`redo_vessel`)는 내린 화물에서 하지 않고 이유를 돌려준다 (D12) |
| `verdict_node(now)` (`graph/vessel.py`) | C14의 시계 하나가 이미 `now: Callable`로 들어 있다 | T3·T8은 이 인자로 문항의 시각을 넘긴다. **R-160이 이 줄을 고친다**: 시계가 둘이라 이것만으로는 하나가 되지 않는다(D20) |
| `trace.py` 가림 확장, `server.py`의 카드 처리 모든 카드에 적용, `view.py`의 `screen_view(values, vessel)` | 8c가 `turn_answers`와 `cargo_dates`를 공책에 더하면 트레이스 가림과 화면 스냅샷이 새 칸을 지나가는지 | T3에 시험을 더함: 새 칸이 화면 스냅샷에 실리지 않고 트레이스에서 번호가 가려진다. 8b B부분 계획의 가림 설명을 그대로 따름 |
| 이전 판의 파일·줄 참조 | `graph/vessel.py`는 이제 `find_vessel`, `find_vessels`, `check_pick`, `ask_vessel`, `verdict_node` 318줄 | 해당 태스크의 파일 목록은 이름 기준이라 그대로. 줄 번호는 쓰지 않았다 |
| R-153 (검증 11-16) `vessel`은 키워드 전용이라 T8의 `evaluate_item`이 셋째 파일을 만든다 | B의 AST 시험이 깨진다. D11과 T8이 함께 설 수 없었다 | D13: 허용 목록 한 줄만 더하고 해시 불변. `**` 키워드 검사를 새 파일에 더함 |
| R-154 `eval/` 네 파일이 "평가 실행기" 묶음에 있다 | T8·T9가 묶음 시험을 깬다. 빼기만 하면 지표 계산이 묶이지 않는다 | D14: 이름으로 빼고 11-13 결과 열 재채점 시험을 더함, MC46 |
| R-155 `tools.py`를 빼면 도구 인자·설명·결과 글 변경 10건이 살아남는다 | CC1과 T1이 B의 해시만 재사용하면 반만 묶인다 | D15: `TOOLS_FULL_SHA`, `TOOL_RESULTS_SHA`, 기대 도구 집합을 글자로. T1 문장 "B가 못 보는 것만 더한다"를 고침. MC35, MC36 |
| R-156 루프 공책에 `turn_answers`가 없고 합치는 함수가 없다 | 카드 답 날짜가 실제 그래프에서 버려지고 한 메시지의 두 호출이 죽거나 하나가 사라진다 | D16: reducer, `turn_answers`를 서브그래프 상태에. 상한은 노드가 다시 찾은 횟수로 센다(D17: 한 메시지에 셋이어도 다시 찾기는 한 번). 합치는 함수는 `LoopState`에만(R-165). MC37, MC38, MC49 |
| R-157 `trace._ship_values`가 `Command`·`ToolMessage.artifact`·dataclass를 못 걷는다 | 되돌리기가 남은 행을 다시 쓰면 다른 화물의 배 값이 도구 끝 트레이스에 실린다 | D17: 되돌리기는 토큰과 횟수만, `_ship_values` 고침(D1의 유일한 예외, 꺼진 길 불변 증거 포함), 켠 길 트레이스 시험. MC39 |
| R-158 검증자가 블록의 ETA와 여유 일수를 막는다 | 블록을 그대로 옮긴 답이 위반이 된다 | D18: ETA는 한국 날짜, 여유 일수는 `N일`로 허용. MC40 |
| R-159 `VERIFY_SHA`는 호출 자리를 안 묶는다 | 꺼진 길이 `verdicts=[]`를 넘겨도 못 본다 | D19: `main.verify`를 감싸 인자를 본다. 초안 묶음은 저장소 안 경우만. MC41 |
| R-160 시계가 둘(`today`, `now`)이고 `verdict_node(now)` 재사용만으로 하나가 안 된다. (앞 줄의 "새 장치를 만들지 않는다"를 고침) | 서버는 둘 다 기본값이라 UTC면 한국 0~9시에 하루 어긋난다. 공용 fixture를 바꾸면 B의 해시가 깨진다 | D20: 켠 길만 `now`에서 오늘을 한 곳에서 만든다. 꺼진 길의 서버 시간대는 배포 전 항목 |
| R-161 `ask_user`의 고른 선택지 글은 모델이 쓴 글이다 | 눌러서 모델이 계산한 날짜를 받는다 | D21: 직접 적은 답만. MC42, MC45 |
| R-162 새 지표가 검증자와 같은 눈이면 0이 스스로를 증명한다 | (나)의 "판정 이름 어긋남 0"이 무의미해진다 | D22: 문장 단위 별도 탐지기를 사전 등록. 나열하고 빼지 않는다 |
| R-163 막을 배 값의 목록과 "카드와 같은 함수"가 모호하다 | UNI-PASS의 `vessel_name`이 블록에 새도 못 잡는다 | D23: 함수와 금지 목록을 이름으로. MC43 |
| R-164 검증자 규칙 (1)이 "토큰은 맞게 쓰고 등급은 다른 화물 값"을 못 본다 | MC44가 살아남는다 | D24: 시험 하나, MC44 |

처리를 정한 것: `48ca3c5` 비교는 D10, 새 시험 파일은 D11, 내린 화물의 되돌리기는 D12, 검증 보고서(`.claude/run/reviews/1116-plan-8c-review.md`) R-153~R-164는 D13~D24와 MC35~MC48. 되돌리기 상한은 `vessel` 노드가 센다(D16, D17, 주인 판정 11-16). 남은 열린 질문은 없다.

## 확인하지 못한 것

| 무엇 | 왜 | 어떻게 확인하나 |
|---|---|---|
| 이 계획의 코드, 시험, 개수, 깨 보기 결과 | 구현 전에 쓴 계획이다. 시험 이름과 기준은 계획이다 | 구현하면서 각 커밋의 결과를 이 문서의 "실측" 줄과 깨 보기 표에 채운다 |
| 평가의 한 문항이 한 차례인지, 선택 카드에 문항이 답을 줄 수 있는지 | `drive()`가 `pauses`에 답을 주는 구조임은 읽었으나 문항별 답 지정 방식은 읽지 않았다 [실측 `src/marvia/eval/run.py:254-270`] | T9를 시작할 때 `drive()`와 `Item`을 읽고 `replies` 칸의 모양을 정한다 |
| `claude -p`(Haiku 5.5)가 도구 인자의 날짜 형식(ISO)을 지키는지, 상대 표현을 받으면 도구를 부르지 않고 되묻는지 | 재 본 적 없다. 구현 시험은 가짜 모델이다 | 측정(나)의 새 문항 N09, N10. **측정 결과 (11-20, `1f32f5f`, 켠 길 다섯 실행 `p1on`~`p5on`):** N09(절대 날짜)는 다섯 실행 모두 `note_dates`를 불렀고 모두 답했다. N10("내일 팔 예정", 상대 표현)은 다섯 실행 모두 `note_dates`를 부르지 않았다. 둘(`p1on`, `p2on`)은 `ask_user` 선택 카드로 갔고 셋은 답했다. 정답 행동은 답이라 선택 카드로 간 두 줄이 새 문항에서 틀린 두 줄이다(새 문항 행동 정확도 0.9667). 답한 셋이 상대 표현을 어떻게 다뤘는지는 읽지 않았다 |
| 사용자가 날짜를 실제로 어떻게 쓰는지(`11.20`, `20일`, `이번 달 20일` 등) | 본 적 없다. 좁게 읽는 설계라 읽지 못하면 되묻는다 | 측정에서 N09의 실패 이유를 본다. 읽는 꼴을 늘리는 것은 따로 정한다 |
| 두 날짜를 한 글에 쓸 때 모델이 역할을 바꿔 넘기는지 | 코드는 날짜가 글에 있는지만 안다(C5) | 측정에서 N09와 N12에 날짜 둘을 쓴 변형을 더할지 본다 |
| 도구 안 `interrupt`의 재개 동작 | `check_vessel`은 이 계획에 넣지 않았다 | 따로 정할 때 |
| 수퍼바이저 길이 판정 블록을 받는지 | C9에서 도구를 주지 않기로 했다. 판정 블록이 그 길의 작성자 입력에 붙는지는 구현 때 정한다 [추정: 붙이지 않는다] | T6에서 확인하고 이 표를 고친다 |
| 켠 길의 모델 호출 수 증가 폭 | 측정 전에는 모른다 | 측정(나)의 호출 중앙값. **측정 결과 (11-20, `1f32f5f`):** v3 문항의 LLM 호출 중앙값은 켠 길 7.0, 끈 길 7.9(`verdict-vessel-1f32f5f.json` `calls_median`)로 늘지 않았다. 새 문항 열둘은 `p1on`에서 문항마다 2~4번이고, 다섯 실행 전체로는 2~16번이다(16번은 `p4on`의 N09) |
| 실제 해수부·ShipFinder 응답으로 하는 측정 | 재생만 쓴다. 실제 호출은 주인이 정한다 | 따로 |
| Postgres 대화 저장소에서 새 공책 칸(`cargo_dates`, `vessel_redo`, 소비한 요청 칸, `turn_answers`의 다음 차례 비움)의 저장·재개 | T5의 DB 시험(`EncryptedSaver`)이 본다. 이 세션은 시험을 돌리지 않았다 [추정: 기존 칸과 같은 길] | 구현 때 그 DB 시험을 돌리고 결과를 채운다. 개발 DB에 붙인 켠 서버에서 한 번 더 |
| 시험용 Neo4j를 켠 전체 시험 | 8b와 같이 사본에서는 끄고 돌린다 | 커밋 때 한 번 |
| `create_agent` 루프에서 한 메시지의 도구 호출이 같은 단계에서 도는지, 서브그래프에 없는 칸이 거기서도 버려지는지 | 검증의 탐침은 일반 `StateGraph`(`Send`)로 돌렸다. `create_agent` 루프로 직접 돌리지 않았다 | T3·T5의 시험이 실제 `create_agent` 루프로 본다 |
| 서버 시간대(꺼진 길의 `today`) | Cloud Run·Docker 이미지의 TZ를 보지 않았다 | 배포 전 확인 항목. 8c 범위가 아니다(D20) |
| MC34가 `ASK_SHA`로 이미 잡히는지 | 코드 읽기만 했다. 공책 값 전체를 해시하므로 잡힐 것으로 본다 [추정] | T1 뒤 깨 보기에서 처음 틀린 시험을 적는다 |
| 측정 화물이 한 질문에 여럿일 때의 켠 길 차례 | 검증의 탐침은 함수 하나씩이고 그래프 한 차례는 돌리지 않았다 | 측정 (나)와 T4·T5의 그래프 시험 |

## 정해 줄 것 (작은 것)

| 무엇 | 지금 계획의 값 | 권고 |
|---|---|---|
| 날짜만 받은 처음 알던 도착 예정의 시각 | 낮 12시(C11) | 그대로. 날짜 단위 판정이 필요하면 `judge`의 일정 규칙을 따로 고친다 |
| 같은 차례에 되돌린 뒤 바로 다시 찾을지 | 안 한다(C7) | 그대로. 쓰임을 본 뒤 `agent`에서 `vessel`로 되돌아가는 화살표를 정한다 |
| 수퍼바이저 길의 판정 블록 | 붙이지 않는다 | 서브에이전트 도구 설계와 함께 따로 |
| 서류 길(MRN 신고에 호출부호 없음)에서 같은 호출부호 후보가 둘인 경우의 그래프 시험 | 지금 재생 자료에 없다(`TESTVSL0007`은 MRN에 호출부호가 있는 길). 8c는 새 재생 자료를 넣지 않고 N08도 `TESTVSL0007`을 쓴다 | **[결정 11-16]** 새 재생 자료 `TESTVSL0008`(MRN 신고에 호출부호 없음, 호출부호 `QQ…`가 같은 후보 둘, 배 번호 `999…`)을 그래프 시험 전용으로 T4에서 더한다. 평가 문항은 12개 그대로. 측정한 다섯 화물의 재생 묶음과 `TESTVSL0001`~`0007`은 건드리지 않는다. 시험은 고른 뒤 확신 상한이 부분인지와, R-147의 버튼 글(같은 호출부호의 배가 여럿이에요)이 이 길에서도 보이는지를 본다 |

## 구현 기록 (11-16, 기준 `f208e59`)

시험은 모두 DB 없이 돌린다(DB 시험 54건은 건너뜀). 기준 수: 계획 문서 커밋 뒤 1,235 통과, 54 건너뜀.

| 단계 | 커밋 | 통과 / 건너뜀 | 적을 것 |
|---|---|---|---|
| T0 | `92f1513` | 1,235 / 54 | 계획 문서 |
| T1 | `51f7ae9` | 1,241 / 54 | 새 시험 6개(`tests/graph/test_vessel_off_inputs.py`). 묶음에서 뺀 파일: `graph/agent.py`, `graph/tools.py`, `graph/verify.py`, `rules/verify.yaml`, `eval/dataset.py`, `eval/metrics.py`, `eval/run.py`, `scripts/run_eval.py`. `prompts/*.md`는 이름 24개로 바꿨다 |
| T2 | `3feda39` | 1,252 / 54 | `absolute_dates`, 시험 11개 |
| T3 | `6996693` | 1,271 / 54 | `note_dates`, 시계 하나, `turn_answers`, 시험 19개. DB 포함 전체(v2): 1,317 / 8 |

T1의 값(기대 값은 `f208e59`에서 냈고 프로세스를 세 번 따로 돌려 같았다 [실측]):

| 이름 | 값 |
|---|---|
| `TOOLS_FULL_SHA` | `4bcb7110a0eec606059c65acf588c8b0b5b574590af8ec4b8a5b53fe97e91b46` |
| `TOOL_RESULTS_SHA` | `cf59a0f8f221ecdf2961dc728cde6ac6cafa3cb241914c8e7b35cc3adfcee136` |
| `VERIFY_SHA` | `75a3934de877e5c460dffead6999f667ca81eb800d077994206fc5df173e3cc8` |
| `SCRUB_SHA` | `ad4582ba86cdb73a20ff5b89a84ae6f04d23a2477515a9fc58777639d505b985` |
| 묶음 값 바뀐 셋 | 그래프 `c1cf6860…`, 평가 실행기 `0d11f516…`, 규칙(그래프·화물 조회·서버·값) `f3a8e8f3…` (파일이 줄었을 뿐 내용은 `48ca3c5`와 같다: `git diff 48ca3c5 f208e59`가 그 파일들에서 비었다) |

`48ca3c5` 사본에서 같은 시험 파일을 돌린 결과(D10, D15) [실측]: 도구 인자 꼴, 도구 결과 글, 검증자 결과, 호출 자리, `**` 검사는 모두 통과했다(`f208e59`와 같다). **`SCRUB_SHA`만 다르다.** 8a가 화물 사실에 빈 칸 여섯을 더했고 8b가 `trace._ship_values`를 더해, 콜백이 받는 값이 `48ca3c5`와 같지 않다. 그래서 `SCRUB_SHA`는 `48ca3c5`의 값이 아니라 `f208e59`의 값이다. 이 시험이 지키는 것은 8c의 트레이스 고침 전후가 같다는 것이다(D17).

D14의 평가 지표 다시 세기 시험은 `tests/eval/test_run_eval_cli.py::test_the_stored_comparison_runs_give_the_stored_verdict_again`에 이미 있어 새로 만들지 않았다. `metrics.py`의 행동 정확도 계산을 바꾸는 깨 보기(MC46)에서 그 파일의 시험이 깨졌다(처음 틀린 시험: `test_sheet_refuses_to_write_answer_text_inside_the_repo`, 실행 순서 때문이다).

### 계획과 다르게 한 곳 (T2~T3, 11-16, 주인 쪽이 받아들임)

| # | 계획 | 한 것 | 까닭 |
|---|---|---|---|
| 1 | D16: `LoopState`에 `cargo_dates`, `turn_answers`(와 `vessel_redo`)를 더하고 합치는 함수를 둔다 | `VesselLoopState(LoopState)`를 따로 만들어 켠 길의 `build_agent`만 쓴다. 합치는 함수는 거기에만 있다(T5의 `vessel_redo`도 거기). 부모 공책은 루프가 끝난 뒤의 전체 값으로 덮어쓴다 | `LoopState`에 더하자 B의 `STATE_SHA`, `LOOPS_SHA`가 깨졌다. 서브그래프가 새 칸의 처음 값(빈 dict, 빈 목록)도 부모 공책으로 돌려줘 꺼진 길의 칸 이름이 달라졌다. 기대 값은 건드리지 않았다 |
| 2 | D20이 시계를 T8에 둠 | T3에 넣었다. 켠 길만 `deps.now()`의 한국 날짜 하나를 brief의 Today, `make_tools`, 검증자, 작성자 프롬프트의 Today에 쓴다 | `note_dates`의 시험이 시계를 필요로 한다 |
| 3 | CC14: `now` = 2026-09-21 16:00 UTC | 2026-09-26 16:00 UTC(한국 09-27) | 09-21 16:00 UTC는 한국 09-22이고 TESTVSL0001의 단계 날짜(09-22)와 같아 검증자 허용 날짜가 겹쳐 MC53이 살아남았다 |

T2~T3 깨 보기(시험이 처음 잡은 것): MC07, MC10, MC12, MC13, MC29, MC30, MC31, MC32, MC37, MC38, MC42, MC45, MC53.

### 검증 1차 검토 뒤 고침 (R-174~R-178, 11-17)

| # | 고친 것 | 값과 까닭 |
|---|---|---|
| R-174 | T1 (나) 대본에 `search_law`를 근거가 모자란 RAG(`sufficient=False`, `missing`)로 한 번 더 부름. "빠진 근거:" 줄이 모델에 간다 | `TOOL_RESULTS_SHA`를 `e192e55eb4abbd3ff3412243fc04b1699986e8bd46380066915b50c92f378318`로 바꿨다. 기대 값은 `f208e59`를 `git archive`로 푼 사본에서 같은 시험 파일로 냈고 현재 코드와 같다. 이전 값(`cf59a0f8…`)은 그 줄을 부르지 않는 대본의 값이다. 그 줄 끝에 공백 하나를 더하는 깨 보기(M7)가 이제 이 시험에서 깨진다 |
| R-175 | CC14 서버형 시험에 둘을 더함: `note_dates`가 한국 날짜로 읽음(`now` 09-26 16:00 UTC, 글 "9월 19일", 모델이 2027-09-19를 넘김: 한국 날짜로는 8일 지나 내년이라 받고 UTC 날짜로는 올해라 거절), 작성자 프롬프트의 Today가 2026-09-27 | 깨 보기 V03(`note_dates`만 UTC 날짜)과 V05(작성자 Today만 `deps.today`)가 이제 깨진다 [실측] |
| R-176 | 사용자 글의 포워더 날이 `judge`의 `forwarder_eta`에 닿는지 `judge` 인자를 엿보는 시험 | `TESTVSL0001`은 해수부 입항 예정이 있어 포워더 날이 판정 값을 바꾸지 않는다. V01(`_given_dates`에서 포워더 두 줄 삭제)이 이제 깨진다 [실측] |
| R-177 | 계획의 MC34(꺼진 길에서도 `ask_user`가 `turn_answers`를 씀)는 "CC1이 잡는다"가 이룰 수 없다. 꺼진 루프 공책에 그 칸이 없어 쓴 값이 오류 없이 버려진다 [실측, 검증 P7]. MC34를 도구 시험으로 바꿨다: `make_tools(vessel=False)`의 `ask_user`가 돌려준 `Command.update`에 `turn_answers`가 없고 켠 쪽에는 있다 | `test_ask_user_writes_turn_answers_only_when_the_switch_is_on` (MC34의 잡는 시험) |
| R-178 | 켠 길이면 계획자 길의 `search_law` 노드(`as_of`)와 `calc` 노드, 수퍼바이저 길의 `sub_node` 오늘도 `clock_today`를 쓴다. 꺼진 길은 `deps.today` 그대로다(`clock_today`가 `deps.today` 자체) | `test_the_on_planner_path_uses_the_one_clock_for_the_search_date_and_the_deadline_calc`. 두 곳을 `deps.today`로 되돌리는 깨 보기가 각각 깨진다. 수퍼바이저 서브에이전트 차례 글의 Today는 시험이 없다 [실측: 한 곳 코드 변경뿐] |
| R-178 보태기 | 켠 수퍼바이저 길의 서브에이전트 차례 글의 Today가 `now`의 한국 날짜임을 보는 시험 | `test_the_on_supervisor_subagent_turn_gets_the_korean_date_of_now_as_today`. `sub_node`에 `deps.today`를 넘기는 깨 보기가 깨진다 |
| 시험의 호출 id | 시험의 가짜 모델은 도구 호출 id를 대화 안에서 겹치지 않게 만든다 | 이미 결과가 있는 id의 호출은 루프가 다시 돌리지 않는다. 실제 모델의 호출 id는 겹치지 않는다 |

### T4 보태기: `TESTVSL0008` (11-17)

계획의 "정해 줄 것" 결정(11-16)대로 T4에서 더할 재생 자료인데 T4 커밋에 빠져 있어 따로 더했다. 서류로 가르는 길(MRN 신고에 호출부호 없음)에서 호출부호가 같은 후보 둘(`QQTWB`, 배 번호 `999000009`, `999000010`)이 있는 화물이다. 새 파일: `fixtures/unipass/TESTVSL0008.json`, `fixtures/shipfinder/VesselSearch/TEST_TWIN_B.json`, `fixtures/mof/VsslEtrynd5/020/QQTWB.xml`. 기존 `_ALL.xml`에는 그 화물의 MRN 신고 한 건을 더했다(`totalCount` 4에서 5). `TESTVSL0001`~`0007`의 파일은 건드리지 않았다. 시험: `test_a_papers_path_cargo_with_twin_call_signs_asks_and_the_pick_stays_partial`(버튼 글 "같은 호출부호의 배가 여럿이에요", 고른 뒤 확신 부분).

### T7 (11-17)

검증자 새 규칙 넷은 `rules/verify.yaml`의 `vessel_verdict`(이름 목록, 단정 어구, 위반 글)와 `graph/verify.py`에 있다. 주의할 곳 둘. (1) 확신 이름 패턴은 "확신을 부분으로 낮췄어요"(판정 글의 까닭)를 확신을 말한 것으로 세지 않는다. 블록 줄을 그대로 옮긴 초안이 통과해야 해서(D18) 시험으로 찾았다(`TESTVSL0005`, `0007`). (2) 여유 일수 `N일`은 그 문장이 가리키는 화물(토큰이 있으면 그 토큰)의 값만 허용한다. 깨 보기(시험이 처음 잡음): MC20, MC21, MC22, MC23, MC24, MC40, MC44, MC56, MC41(`test_the_verifier_is_called_without_verdicts_on_all_three_off_paths`).

### T8 (11-17)

`--vessel off|on`(기본 off)은 `evaluate_item(..., vessel)`만 켠다. 환경 변수는 읽지 않는다. 줄에 `vessel_graph`(실제로 만든 그래프에 배 단계가 있는가)와 `now`(그 문항의 기준 시각)를 남기고, `run_problems`는 인자와 `vessel_graph`가 다른 줄이 있으면 그 실행을 무효로 둔다. meta에 `vessel`과 `vessel_replay_sha256`(세관·해수부·ShipFinder 재생 폴더의 이름과 내용 해시)을 남긴다. 기준 시각은 `run.item_clock`: 문항의 `now`, 없으면 `as_of` 날짜 09:00 한국 시각이다. 켠 길은 이 시각 하나에서 모델의 Today, `note_dates`, 판정이 나온다. `Item`에 `vessel_only`와 `now`를 T8에서 먼저 더했다(T9는 나머지 칸). B의 `test_vessel_off.py`는 AST 시험의 허용 목록 한 줄(`("src/marvia/eval/run.py", "vessel")`)만 고쳤고 해시 상수는 그대로다(D13). 시험 파일은 `tests/graph/test_run_vessel.py`다(`tests/eval/`에는 `agent_deps` 준비물이 없다). 깨 보기(시험이 처음 잡음): MC25, MC26, MC27, MC28.

### T9 (11-17)

`eval/set_v4.yaml`(동결 해시 `62969fde2b4c8ccfa83c16bc28703d55e00be31e7a3354d5b5a1604ad34e53f3`)은 v3 30문항을 그대로 두고 N01~N12를 더했다. 새 칸은 `vessel_only`, `now`(문항의 기준 시각, 2026-09-22 03:00 UTC), `replies`(선택 카드에 줄 답, 0은 "모르겠어요"), `expect_verdict`(화물마다 기대 판정)다. 기대 판정은 코드가 낸 값이고 그래프 밖에서 직접 낸 값과 손 계산으로 맞대었다(`eval/gold_check_v4.md`). 계획 표의 기대 판정과 다른 곳이 있다: N08은 "부분"이 아니라 **등급 없음, 불명**이다(`TESTVSL0007`은 위치와 도착 시각이 없다 [실측]). N04도 등급 없음이다.

새 지표(`metrics.py`, v3 판정 출력 칸은 늘리지 않았다): `verdict_detector`(문장 단위, 검증자와 따로, 센 문장 나열, 귀속 못 한 수는 따로), `assertive_violations`, `ship_value_hits`, `vessel_totals`, `compare_vessel`(사전 등록 기준은 `rules/vessel.yaml`의 `comparison`. `rules/eval.yaml`은 측정 커밋 묶음에 있어 건드리지 않았다). 줄의 새 칸(`detector`, `detector_unattributed`, `verifier_form`, `assertive`, `ship_leak`)은 켠 길 문항에만 생기고 센 문장은 raw에만 둔다. 화면에 나간 답은 토큰이 실제 번호로 되돌아가 있어, 탐지기에 넣기 전에 다시 토큰으로 바꾼다. 비교는 `scripts/run_eval.py verdict --set v4 --compare vessel --on 파일들 --off 파일들`이다. 깨 보기: MC27(replies를 안 씀), MC54, MC55.

### T10, T11 (11-17)

화면: 판정 칸에 `given`(사용자가 말해 받은 날짜, 라벨, 날짜, 출처 글)을 더했다. 출처 글은 서버(`rules/vessel.yaml dates.card_source`, "말씀하신 날")가 정하고 처음 알던 도착 예정은 낮 시각 규칙이 함께 붙는다. 서버의 화면 갱신 목록(`LIVE_KEYS`)에 `cargo_dates`를 더했다(없으면 첫 차례 카드에 날짜가 안 보인다). 받은 날짜는 다음 차례 판정에 쓰이므로 첫 차례 카드는 날짜 줄이 먼저 보이고 등급은 다음 차례에 바뀐다(C6, C7의 설계). 시험: `test_the_card_shows_the_dates_the_user_gave_with_their_source`, 화면 시험 한 흐름. Docker 화면 시험: 켠 실행 7 통과·7 건너뜀(새 흐름 포함), 기본 실행 7 통과·7 건너뜀. 기본 실행 뒤 그림은 `choice.png` 한 장에서 한 픽셀(131,222)이 달랐다(안티앨리어싱 떨림으로 8b 때 `approval.png`에서 본 것과 같은 꼴. 원인은 확인하지 못했다). 되돌렸다. 가짜 API(`e2e/fake_api.py`)의 `today`는 고정하지 않았다: 기본 실행의 그림이 달라질 수 있어서다(켠 길은 `now`를 쓴다).

문서(T11): README, 설계 6.5·10절과 변경 기록, 검증자 머리말을 고쳤다.

### 검증 2차 검토 뒤 고침 (R-179~R-183, 11-17)

| # | 고친 것 | 시험과 깨 보기 |
|---|---|---|
| R-183 | 블록을 먼저 만들고 그 글이 비지 않을 때만 brief와 작성자 입력에 붙인다(쓰는 법 조각도 블록과 함께만). 화물을 말하지 않은 차례에 조각도 빈 줄도 붙지 않는다. 조회에 실패한 화물의 "배 판정이 없어요" 줄은 그대로다 | `test_a_turn_without_a_cargo_gets_no_fragment_and_no_blank_lines_after_a_ship_was_confirmed`. W12(조건에서 `vessels`를 뺌 또는 되돌림)가 깨진다 |
| R-180 | (가) 판정이 없는 화물의 줄을 다른 화물의 판정으로 채우지 않는다. (나) 화물 조회가 실패한 차례는 되돌리기 요청을 소비하지 않고 다시 찾은 횟수를 올리지 않는다 | `test_a_cargo_without_a_verdict_is_never_filled_from_another_cargos_verdict`(MC19의 다른 꼴), `test_a_turn_where_the_cargos_lookup_failed_neither_consumes_a_redo_nor_raises_the_refind_count`(W11) |
| R-179 | `Send` 값과 집합 값을 트레이스 가림 시험에 더했다. 갈래는 그대로 둔다 | `test_scrub_walks_dataclass_pydantic_command_and_artifact`. W07(`Send` 갈래 뺌), W08(집합 갈래 뺌)이 깨진다 |
| R-182 | `tests/graph/test_vessel_prompts.py`의 em dash 글자를 `\u2014` 이스케이프로 바꿨다. 추적하는 파일에서 U+2014를 찾으면 0이다 | 파일 훑기 [실측] |

### 검증 3차 검토 뒤 고침 (R-184, R-185, 11-17)

| # | 고친 것 | 시험과 깨 보기 |
|---|---|---|
| R-184 | 켠 에이전트 길에 루프 뒤 `rejudge` 노드를 더했다. verdict가 이번 차례에 받은 위치·일정을 닫힌 함수 안(프로세스 사전, 대화 번호와 토큰 키)에 두고, 이번 차례에 `note_dates`가 받은 날짜가 바뀐 화물만 같은 시계로 다시 판정한다. 그래서 바깥 호출은 늘지 않고(위치 1, 일정 1 그대로) 위치·일정은 공책, 모델 입력, 화면(LIVE_KEYS), 트레이스에 실리지 않는다. 사전이 비었으면(재시작 뒤 재개 같은 드문 경우) 그 화물 하나만 다시 받는다. 꺼진 길과 수퍼바이저 길에는 이 노드가 없다. 루프 안의 `read_vessel`은 날짜 전 판정을 보이고 `note_dates` 결과 글이 "판정은 이 차례의 답을 쓸 때 받은 날짜로 다시 계산해요"라고 말한다 | `test_a_date_accepted_this_turn_changes_the_grade_in_the_same_turn_without_new_outside_calls`, `test_all_twelve_v4_items_give_the_expected_verdict_in_the_same_turn_with_a_verbatim_writer`(N09 경계, N12 일정 지연, 탐지기 0, 검증자 위반 없음). 노드 연결을 빼거나 다시 판정을 건너뛰는 깨 보기가 깨진다. v4 동결 해시는 그대로다 |
| R-185 | `rules/verdict.yaml notes.ship_unchecked`에서 확신 이름을 빼고 검증자의 "낮췄어요" 예외를 지웠다 | `test_no_reason_text_of_the_verdict_names_a_confidence_so_quoting_it_never_trips_the_rule`. 화면 그림: 이 글이 보이는 그림이 있으면 바이트가 바뀐다. e2e 뒤에 다시 만들어 보고 게이트에 적는다(아직 안 돌림) |

### 깨 보기 결과 (R-188, 11-17)

사본에서 한 곳씩 바꾸고 관련 시험을 돌려 처음 틀린 시험을 적었다. "내 기록에 없음"은 이 구현 쪽에서 돌리지 않았다는 뜻이고 검증의 기록(`.claude/run/reviews/1116-8c-impl-review.md`)이 있으면 거기를 본다.

| 깨 보기 | 결과 |
|---|---|
| MC01 | 내 기록에 없음 (T1 `TOOLS_FULL_SHA` 시험이 같은 꼴: MC35가 인자 꼴 변이로 깨진다) |
| MC02, MC03 | `test_vessel_off.py::test_what_the_model_receives_is_unchanged_when_the_switch_is_off` |
| MC04 | 내 기록에 없음 (`rules/agent.yaml`은 고정 묶음에 있다) |
| MC05, MC06, MC43 | `test_ship_identifiers_never_reach_the_model_even_with_a_hostile_name` |
| MC07 | `test_a_date_not_in_this_turns_text_is_refused` |
| MC08, MC09, MC11, MC14, MC17, MC33 | 내 기록에 없음 |
| MC10 | `test_out_of_range_is_refused` |
| MC12 | `test_the_sale_date_reaches_the_judge_and_changes_the_margin_grade` |
| MC13 | `test_first_eta_is_read_as_that_days_noon_in_korea` |
| MC15 | `test_redo_clears_only_that_cargos_rows_and_the_next_turn_looks_the_ship_up_again` |
| MC16 | `test_redo_stops_after_the_limit_and_keeps_the_rows` |
| MC18 | `test_read_vessel_does_not_change_the_notebook` |
| MC19 | 첫 꼴과 다른 꼴 모두 `test_a_cargo_without_a_verdict_is_never_filled_from_another_cargos_verdict` |
| MC20 | `test_a_wrong_grade_name_next_to_the_word_grade_is_a_violation` |
| MC21 | `test_an_eta_date_in_the_block_is_allowed_and_another_date_is_not` |
| MC22 | `test_assertive_words_about_a_partial_cargo_are_a_violation` |
| MC23 | `test_a_grade_for_a_cargo_without_grade_is_a_violation` |
| MC24 | `test_everyday_words_do_not_trip_the_rule` |
| MC25 | `test_the_environment_alone_never_turns_it_on` |
| MC26 | `test_a_mismatch_between_the_argument_and_the_graph_is_a_problem` |
| MC27 | `test_vessel_only_items_are_skipped_when_the_argument_is_off` (+ replies 변이는 `test_an_on_run_gives_the_card_the_items_reply_and_records_the_new_metrics`) |
| MC28 | `test_the_meta_records_the_switch_and_the_clock` |
| MC29 | `test_a_date_the_user_wrote_this_turn_is_accepted` |
| MC30, MC53 | `test_an_on_graph_built_like_the_server_reads_today_from_now_in_kst` |
| MC31 | `test_a_date_the_user_typed_into_an_ask_user_card_this_turn_is_accepted` |
| MC32 | `test_a_date_the_user_wrote_this_turn_is_accepted` |
| MC34 | 도구 시험으로 바꿈: `test_ask_user_writes_turn_answers_only_when_the_switch_is_on` (R-177) |
| MC35, MC36 | `test_vessel_off_inputs.py`의 `TOOLS_FULL_SHA`, `TOOL_RESULTS_SHA` 시험 |
| MC37 | `test_a_date_the_user_typed_into_an_ask_user_card_this_turn_is_accepted` |
| MC38 | `test_two_note_dates_calls_in_one_message_both_survive` |
| MC39 | `test_three_redo_calls_on_one_token_in_one_message_make_exactly_one_refind` |
| MC40 | `test_the_margin_days_of_that_cargo_are_allowed_as_n_days` |
| MC41 | `test_the_verifier_is_called_without_verdicts_on_all_three_off_paths` |
| MC42 | `test_a_date_only_in_a_picked_option_is_refused` |
| MC44 | `test_two_cargos_token_matched_grades_pass_and_swapped_grades_fail` |
| MC45 | `test_a_card_answer_from_an_earlier_turn_is_refused_in_a_turn_without_cargo` |
| MC46 | `test_run_eval_cli.py`의 시험(행동 정확도 계산 변이). 그 파일의 첫 틀린 시험은 `test_sheet_refuses_to_write_answer_text_inside_the_repo`였다 |
| MC47, MC50 | `test_three_redo_calls_on_one_token_in_one_message_make_exactly_one_refind` |
| MC48, MC49 | `test_redo_stops_after_the_limit_and_keeps_the_rows` |
| MC51 | `test_scrub_walks_dataclass_pydantic_command_and_artifact` (옛 `_ship_values` 전체 되돌리기. 켠 길 span별 시험은 옛 코드로도 통과한다: 되돌리기가 행을 더는 싣지 않아서) |
| MC52 | `test_the_trace_scrub_of_the_off_paths_is_unchanged` |
| MC54, MC55 | `test_the_detector_on_two_cargos_counts_a_tokenless_sentence_only_when_it_differs_from_every_cargo`, `test_the_unattributed_count_is_reported_and_not_added_to_the_criterion` (MC55 비교 꼴은 `test_the_unattributed_count_is_reported_but_never_added_to_the_criterion`) |
| MC56 | `test_a_day_count_that_is_not_that_cargos_margin_days_is_still_flagged` |
| 검증의 변이 | V01, V03, V05(1차), W07, W08, W11, W12(2차), X04, X05, X10, X11(3차): 모두 위에 적은 시험으로 이제 깨진다 [실측: 내 사본에서 직접 돌린 것: V01, V03, V05, W07, W08, W11, W12, X04, X05, X10, X11] |

### 검증 4차 검토 뒤 고침 (R-189~R-192, 11-17)

| # | 고친 것 | 시험과 깨 보기 |
|---|---|---|
| R-189 | 판정 줄에 `dates`(그 판정이 쓴 날짜)를 적는다. 날짜는 배 값이 아니라 공책에 둔다. `rejudge`는 그 `dates`와 지금 `cargo_dates`가 다른 화물만 다시 판정하므로 다시 시작한 뒤의 재개와 사전 비움에서도 앞 차례 날짜 때문에 다시 받지 않는다. 사전이 없을 때의 다시 받기도 한 차례의 화물 수 상한(`max_cargos` 3, `over_cap` 유지)을 센다. `rejudge`는 쓴 항목을 지운다(512개 비움은 안전장치로 둔다). 계획자 길과 수퍼바이저 길은 사전에 쓰지 않는다(`keep=False`) | `test_a_restart_in_the_middle_of_the_turn_refetches_once_and_still_judges_the_new_date`(S2), `test_a_restart_resume_with_only_an_old_date_makes_no_new_outside_call`(S3), `test_a_refetch_after_a_restart_stays_within_the_per_turn_cargo_cap`, `test_the_planner_and_supervisor_paths_do_not_write_the_fetch_cache`(쓴 항목을 지움도 본다), `test_the_verdict_row_carries_the_dates_it_was_judged_with_and_the_cache_is_emptied_by_rejudge`. 깨 보기 K12(날짜 견주기를 뺌), K2(지우지 않음), 상한 우회가 깨진다 |
| R-190 | 한 프로세스에서 두 대화가 섞여도 서로의 위치·일정을 읽지 않는다 | `test_two_conversations_in_one_process_never_read_each_others_fetched_data`(S4: B도 질문에서 멈춰 B의 사전 항목이 남은 채 A를 재개). K1(대화 번호를 키에서 뺌)이 깨진다 |
| R-191 | 검증자의 "낮췄어요" 예외가 없음을 못박는다 | `test_a_sentence_that_says_the_confidence_was_lowered_is_checked_like_any_other`. 예외를 다시 넣는 변이(X02)가 깨진다 |
| R-192 | 계획의 Task M Step 3에 (가)의 판정 방법과 멈춤 규칙을 적었다 | 문서만 |

### 검증 5차 검토 뒤 고침 (R-193, R-194, 11-19)

| # | 고친 것 | 시험과 깨 보기 |
|---|---|---|
| R-193 | S4 시험에 A의 재개가 바깥 호출 0번임을 더하고 B가 질문에서 멈추는 순서와 끝까지 도는 순서 둘 다 본다 | `test_two_conversations_in_one_process_never_read_each_others_fetched_data[True/False]`. 키에서 대화 번호를 뺀 변이(K1)가 두 순서 모두 깨진다 [실측] |
| R-194 | 한 번의 판정에서 넷째 화물이 `over_cap`이 되고, 재시작 뒤 그 화물에만 날짜가 받아진 경우 바깥 호출 0번이고 `over_cap`이 줄에 남는다 | `test_a_date_accepted_for_the_cargo_that_was_over_the_cap_after_a_restart_makes_no_outside_call`. `"over_cap" not in row["notes"]`를 뺀 변이(C2)가 깨진다 [실측] |

### R-195 (11-20)

| # | 고친 것 | 시험과 깨 보기 |
|---|---|---|
| R-195 | 켠 계획자 길, 켠 수퍼바이저 길의 한 차례가 위치·일정 사전을 비워 둔다(`keep` 거짓). 켠 에이전트 길은 `keep` 참이고 한 차례 뒤 사전이 비어 있다(rejudge가 지움) | `test_a_turn_on_each_on_path_leaves_the_fetch_cache_empty`(세 길). main.py가 `verdict_nodes(deps.now)`로 돌아가 `keep`을 무시하는 변이(KP)가 계획자 길에서 깨진다 [실측] |

### R-196 (11-20)

v4 끈 길 덮음 검사 오류를 첫 끈 길 실행에서 찾아 이 커밋에서 고쳤다(`run_eval.py`가 전체 문항으로 덮음을 봐 N01~N12가 "빠짐"이 됨). 기대 집합은 `expected_items`(전체에서 runnable만). 측정은 새 커밋에서 다시 시작한다.

### 측정 결과 (11-20)

커밋 `1f32f5f`로 쟀다(11-20). 결과 파일 11개(끈 길 점검 `chk`, 켠 길 `p1on`~`p5on`, 끈 길 `p1off`, `p2offr3`, `p3off`, `p4off`, `p5offr3`)와 판정 `verdict-vessel-1f32f5f.json`을 `eval/results/`에 두었다. 무효였던 `p2off`, `p2offr2`, `p5off`, `p5offr2`는 파일을 두지 않고 보고서에 적었다. `overall ok`는 거짓이고 걸린 곳은 호출 상한 줄 하나다(켠 길 3, 끈 길 3, 모두 v3 문항 U05/U06/R01, N 문항은 0). 기본값은 끈 채로 둔다.
