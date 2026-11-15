# Marvia v2 계획 8b B부분: 배 식별 단계와 화물 카드의 판정 칸 (스위치 뒤)

> 진행 방법: 태스크를 T0부터 차례로 하고, 단계마다 체크박스(`- [ ]`)로 표시한다. 커밋 하나는 동작 하나다. 이 부분은 A부분(배 판정 규칙)이 들어간 뒤에 한다. 계획 8a가 지은 배 추적 기반을 그래프와 화면에 잇되, 스위치 `MARVIA_VESSEL`(기본 `off`) 뒤에 둔다. 꺼져 있으면 그래프, 평가 줄, 화면 스트림이 지금과 같다.

**Goal:** 화물을 식별한 뒤 그 화물을 실은 배를 코드가 찾아 확정하거나 되묻고(재고 과제 9), 판정 네 칸과 믿을 ETA, 등급이 없을 때의 까닭을 화물 카드에 보인다(재고 과제 11). 모델은 배를 고르지 않고, 배 이름·호출부호·배 번호와 판정 칸은 모델을 거치지 않고 화면 허용 목록으로만 간다. 틀린 것을 확실한 것처럼 보이지 않는다: 이름이 닮은 한 척, 사용자가 고른 배, 배에서 내린 화물의 배 신호를 모두 막는다.

**Architecture:** 메인 그래프에서 "화물 조회가 끝난 자리"와 "첫 일" 사이에 노드 셋을 끼운다. 세 노드는 새 파일 `src/marvia/graph/vessel.py` 하나에 있고, 8a의 조회·판정 모듈과 A부분이 고친 규칙을 부르는 것은 그래프에서 이 파일뿐이다.

```
START → start → identify ─(번호가 애매하면 ask → lookup)─┐
                                                          ▼            MARVIA_VESSEL=on일 때만 있는 노드
                                    vessel ──(가르지 못한 화물이 있으면)── ask_vessel
                                       │                                      │  선택 카드: 0번 "모르겠어요"(권장), 1~2번 후보(자리표)
                                       └──────────────► verdict ◄─────────────┘
                                                          │
                                                          ▼
                                    첫 일 (에이전트·수퍼바이저 길: news, 계획자 길: plan) → ... (지금과 같다)

vessel      화물마다: 배를 보는 단계가 아니면 건너뜀(바깥 호출 0) → 양륙항 코드 → 항만 표 → 해수부 입항 신고에서 MRN이 같은 줄
              → 호출부호 → ShipFinder 후보(호출부호, 없으면 세관이 준 배 이름)
              → (MRN 호출부호와 같은 후보가 없으면 후보마다 그 배의 해수부 입항 신고)
              → tools/vessel_match.match_vessel → confirmed | ask | none, 조회 실패와 한도 닿음은 unknown
              ask이면 후보마다 "그 후보 하나만 있다고 보고" 맞춘 이유(check)를 카드용으로 붙이고(check_candidate는 부르지 않는다),
              MRN 조회 결과(lookup), MRN 호출부호, 검색 결과 전체(hits)를 질문 공책에 둔다
ask_vessel  선택 카드로 묻는다. 고른 배는 check_pick이 check_candidate에 건다: 검색 결과 전체(hits)와 견주어 같은 호출부호의 배가 있으면 상한을 걸고,
              서류로 맞추는 길이면 고른 배의 입항 신고를 한 번 받는다(받지 못하면 조회 실패, 상한 부분). 결과는 상태 user_choice로 남는다
verdict     화물마다: 배를 본 화물(confirmed, user_choice)만 ShipFinder 위치와 해수부 입항 일정(세관 입항일을 넘김)을 받아 tools/judge.judge → 판정 네 칸.
              호출부호를 맞추지 못한 배의 상한(cap)은 judge로 넘긴다
view        서버가 스위치를 켠 그래프를 띄웠을 때만 화물 카드에 ship, verdict 칸을 더한다 (rules/vessel.yaml, rules/verdict.yaml의 정한 글)
서버        선택 카드의 자리표를 후보의 이름·호출부호로 바꿔 화면에 보내고, 직접 적은 글은 후보와 맞춰 번호로 바꿔 그래프에 넘긴다
```

**Tech Stack:** 새 의존성 없음. Python 3.12, LangGraph(`interrupt`), pydantic, PyYAML, Next.js 16 / React 19, Playwright (`uv.lock`, `web/package-lock.json` 그대로). 이 계획의 코드는 LLM을 부르지 않는다.

**Spec:** `docs/specs/2026-10-28-marvia-v2-design.md` (2절 결정 3·4·13, 4.1 ② 후보 제시, 4.2 MRN, 6.3 질문 통로, 7.1, 7.2, 10절 화물 카드, 12절 신뢰 경계). 재고: `.claude/run/research/1113-vessel-tracking-inventory.md` 과제 9, 11. 앞 계획: `docs/plans/2026-11-13-marvia-v2-plan-8a-vessel-base.md`, 8b A부분(`docs/plans/2026-11-15-marvia-v2-plan-8b-part-a.md`). 검토: `.claude/run/reviews/1113-plan-8b-review.md`(B1·B2·F1~F8·D1~D4).

## 계획 나눔

| 계획 | 범위 | 상태 |
|---|---|---|
| 8a | 배 추적 기반: 신호, 판정 묶음, 배 확정, 해수부·ShipFinder 클라이언트, 항만 표, 판정 평가 문항 | 완료 (`48ca3c5..ad17004`, 태그 `ckpt/8a-fix`) |
| 8b A부분 | 배 판정 규칙 고침과 문항 | 앞에 들어감 (이 문서의 기준 `2bc6073`) |
| **8b B부분 (이 문서)** | 재고 과제 9(배 식별을 그래프에 잇기, 선택 카드)와 11(화물 카드의 판정 칸). 스위치 뒤 | 11-16 |
| 8c (다음) | 조회 도구를 에이전트 도구 목록에 더하고 지시문·화물 줄·작성자·검증자를 바꿈, 판매 예정일·처음 알던 도착 예정 받기, 틀린 확정 되돌리기, 평가셋 새 판 | 평가 조건이 바뀐다 |
| 따로 | 위치 이력 모으기, 감시 재조회(recheck_watch)에서 배 다시 보기, 확정한 배를 감시 표에 저장 | 정하지 않음 |

이 문서의 diff는 모두 A부분이 들어간 `2bc6073` 위에서 만든 것이다. 그 위에 새 커밋 열 개를 쌓는다. 본 측정은 끝났고 판정은 "구분 못 함"이며 기본 길은 `agent`다. 이 부분은 에이전트 길 기준으로 간다.

## 정해 둔 것 (11-13, 11-15, 11-16)

판정 규칙(배를 보는 단계, 일정 칸, 입항한 배, 항차 가드, 배 확정 근거와 확신 상한)은 A부분의 결정 A1~A12다. 아래는 그래프, 서버, 화면의 결정이다.

| # | 결정 | 이유 | 틀렸을 때 비용 |
|---|---|---|---|
| B1 | 스위치는 `MARVIA_VESSEL=off\|on`, 기본 `off`. 읽는 곳은 서버 진입점(`marvia.server.main`) 하나다. 평가 실행기, CLI, 길 비교 스크립트, 감시 재조회는 스위치를 넘기지 않아 늘 꺼진 그래프를 만든다. 가짜 API(`e2e/fake_api.py`)만 화면 시험을 위해 같은 설정을 읽는다 | 평가 줄이 이 계획과 무관해야 한다. 켜는 길이 하나면 "어디서 켜졌나"를 찾을 일이 없다. 시험은 글자 찾기가 아니라 동작으로 본다: 환경에 `MARVIA_VESSEL=on`을 넣고 평가 실행기가 만든 그래프에 `vessel` 노드가 없음을 보고, 코드 문법 트리(AST)로 `build_main_graph`에 `vessel=`을 넘기는 파일을 센다 | 평가에서 배 식별을 보려면 평가 실행기에 따로 넘겨야 한다(8c) |
| B2 | 꺼짐의 뜻은 "노드를 만들지 않는다"다. 측정 커밋(`48ca3c5`)의 해시 고정은 이 부분이 고치는 다섯 파일만 뺀다: `graph/main.py`, `graph/state.py`, `server.py`, `view.py`, `trace.py`. 나머지는 해시 묶음에 그대로 남는다. 뺀 다섯의 "꺼져 있으면 같다"는 동작 시험으로 묶는다: 길 셋의 그래프 모양, 에이전트 길 한 차례의 화면 이벤트 전체, 길 셋의 한 차례와 그 이벤트·공책을 트레이스 가림에 넣은 결과 | 본 측정은 끝났다. 이 고정의 목적은 이제 "배 식별 스위치가 꺼진 길이 그대로"를 지키는 것이다. 폴더 전체를 내리면 그 파일들의 변화를 못 잡는다 | 해시로 묶은 대본 한 차례가 보지 않는 길의 답은 모양(노드와 화살표)과 이벤트만 본다 |
| B3 | 자리는 식별 서브그래프 안이 아니라 메인 그래프의 "화물 조회 뒤, 첫 일 앞"이다 | 식별 서브그래프(`graph/identify.py`)는 건드리지 않는다. 되묻기는 메인 그래프의 노드에서만 한다(기존 `ask`와 같다). 감시 목록의 재조회도 같은 조회 서브그래프를 쓰는데 거기에 배 조회가 딸려 가면 안 된다 | 에이전트가 루프 안에서 `lookup_cargo` 도구로 새로 찾은 화물은 그 차례에 이 단계를 지나지 않는다. 카드는 "이번 차례에는 배를 보지 않았어요"라고 사실대로 말한다 |
| B4 | **찾는 쪽(`find_vessel`)은 `check_candidate`를 부르지 않는다.** 되묻기로 가는 화물에는 후보마다 "그 후보 하나만 있다고 보고" `match_vessel`로 맞춘 이유(`check`)만 카드용으로 붙이고, MRN 조회 결과(`lookup`), MRN 호출부호, 검색 결과 전체(`hits`)를 질문 공책에 둔다. 고른 뒤의 검사(`check_pick`)만 `check_candidate`를 부른다 | 고르기 전에는 고른 배가 없다. 후보마다 `check_candidate`를 부르면 고르지도 않은 배의 입항 신고를 받아 요청 수가 늘고 한 척 상한이 카드 글에 섞인다. 호출 시험과 문법 트리 시험이 이 구분을 지킨다 | 카드의 "서류로 본 결과"는 고른 뒤의 검사와 같은 말이 아니다(한 척만 있다고 본 결과다) |
| B5 | **고른 배는 검색 결과 전체와 견준다(R-132).** `check_pick`은 `check_candidate`에 카드에 보인 후보가 아니라 `question["hits"]`(검색 결과 전체)를 넘긴다. 카드에는 둘만 보이므로(`max_choices`) 같은 호출부호의 배 셋 가운데 보이는 둘 중 하나를 골라도 셋째 배가 있어 상한(부분)이 걸린다 | 보이는 후보만 넘기면 잘린 쪽의 같은 호출부호의 배를 놓쳐 상한이 빠지고 틀린 배가 "확실"까지 나온다 | 검색 결과 전체를 공책에 두어 공책이 커진다(배 번호와 호출부호만) |
| B6 | **고른 배의 결과는 자동 확정과 구분한다.** 행의 상태는 `user_choice`이고 이유(`reason`), 맞춰 본 칸(`basis`), 확신 상한(`cap`)이 함께 남는다. 화면의 이유 글은 "고르신 배로 봤어요"이고 맞춰 본 결과 글은 그 행의 이유 글이다. 카드 글은 상태가 아니라 이유와 근거에서 만들고 고른 배에는 "확실"이 읽히지 않는다 | A6·A7에서 사용자가 고른 배의 확신은 상한이 걸린다. 상태를 `confirmed`로 두면 화면이 자동 확정과 구분하지 못한다 | 없음 |
| B7 | **서류로 맞추는 길(MRN 조회가 성공했고 그 신고에 호출부호가 없을 때)에서만 고른 배의 입항 신고를 한 번 받는다**(`mof.plans_for`, 규칙 `pick_calls` 1). 받지 못하면 조회 실패로 본다(상한 부분, 이유 `mrn_lookup_failed`). 입항 신고는 공책에 두지 않는다 | 후보마다의 입항 신고는 고르기 전에 받지 않는다(B4). 고른 뒤에 한 번이면 요청 수가 한 척분이다 | 한 화물의 요청 수 상한이 17에서 18이 된다(결정 B12) |
| B8 | 되묻기는 기존 선택 카드 모양 그대로다(`kind`, `question`, `options`, `recommended`). 0번은 "모르겠어요"(배 정보 없이 진행)이고 권장이다. 후보는 둘까지 보인다(합쳐 셋, 설계 6.3의 2~3개). 끼어들기 값(체크포인트와 트레이스로 간다)에는 배 이름·호출부호·배 번호 대신 자리표(`{ship1}`, `{ship1_info}`)를 싣고, 서버가 화면으로 보낼 때 공책의 후보로 바꾼다(화물 번호의 가림과 같은 방식). 직접 적은 글은 서버가 후보와 맞춰 번호로 바꿔 그래프에 넘긴다(호출부호나 배 번호가 후보 한 척에만 들어 있으면 그 번호, 아니면 0번). 그래프는 번호만 받는다 | 11-13 판정(F6). 이름이 끼어들기 값과 재개 값으로 트레이스에 실리는 길을 막는다. 근거 없이 한 척을 권하면 사용자가 권장을 누르는 순간 틀린 배를 확정한다 | 후보가 셋 이상이면 카드에 안 보이는 배가 있다. 직접 입력으로만 고를 수 있다 |
| B9 | 시간 초과와 취소는 권장안(배 없이 진행)으로 가고 가정(`assumptions`)에 한 줄 남긴다. "모르겠어요"를 직접 고른 것은 가정이 아니다. 가정 글과 질문 머리에는 배 이름을 넣지 않고 화물은 가린 이름표(`[BL1]`)로만 적는다. 한 차례에 한 화물만 묻는다: 가르지 못한 둘째 화물은 묻지 않고 배 없이 진행하며 그렇다고 적는다(`another_question`) | 설계 결정 4의 ②. 가정은 답 아래에 보이고 대화 기록에 남아 모델이 읽는다. 카드가 연달아 뜨면 다른 화물의 답이 막힌다 | 둘째 화물은 다음 차례에 다시 말해야 묻는다 |
| B10 | 조회 상한은 코드가 세어 막고 값은 `rules/vessel.yaml`에 둔다. 한 화물의 바깥 요청은 배 찾기 `max_find_calls` 14 = MRN 입항 신고 목록 쪽 수 8 + 배 검색 1 + 후보별 입항 신고 5, 판정 `verdict_calls` 3 = 위치 1 + 입항 실적 1 + 입항 예정 1, 고른 뒤 `pick_calls` 1, 합 `max_calls` 18이다(재시도는 세지 않고 실패한 요청은 두 번 더 부른다). 한 차례에 한 화물 18 × 화물 수 상한 3 = 많아야 54다. 같은 항만·같은 날의 입항 신고 목록은 한 차례에 한 번만 받는다. 한 차례의 배 찾기 시간 상한은 30초(`max_seconds`)이고 넘으면 남은 화물은 찾지 않는다. 상한에 닿으면 배를 지어내지 않고 "조회 한도에 닿아 배를 확인하지 못했어요"(`call_limit`)나 "조회 시간이 길어져 이 화물은 찾지 않았어요"(`time_limit`)를 보인다. 화물 수 상한(3)을 넘은 화물은 찾지 않고 등급을 내지 않으며 까닭(`over_cap`)을 보인다. 확정한 배의 위치·일정 조회도 같은 화물 수 상한을 센다 | 11-13 검토 F4: 해수부 입항 신고 목록은 쪽을 넘기고(v1 실측: 부산 5일치 12쪽, 쪽당 50건) MRN 창이 3일이라 약 7쪽이다 [추정]. 쪽 상한을 채우면 8a 규칙대로 `too_many` 오류라 MRN 길이 막히므로 쪽 상한을 8로 둔다 | 실제 응답으로 쪽 수를 재 보지 못했다. 많으면 MRN 길이 `too_many`로 끝나고 배 이름 검색으로 떨어져 되묻는다. 요청 하나가 15초까지 기다릴 수 있어 시간 상한은 요청 사이에서만 걸린다 |
| B11 | 확정한 배와 "모르겠어요" 답은 그 대화의 공책(`vessels`)에 남겨 다시 찾거나 다시 묻지 않는다. 화물을 말하지 않은 차례를 지나도 잊지 않는다. 위치와 입항 일정은 차례마다 새로 받는다. 장기 기억과 감시 표에는 넣지 않는다. 틀린 확정과 "모르겠어요"를 그 대화에서 되돌리는 길은 8c로 미룬다 | 같은 화물을 물을 때마다 카드가 뜨면 쓸 수 없다. 대화 밖 저장은 암호화 칸과 지우기(계정 삭제)를 함께 지어야 한다 | 새 대화에서는 다시 찾는다. 틀린 확정은 되돌릴 길이 8c까지 없다 |
| B12 | 이번 차례의 화물 조회가 실패했으면 지난 차례에 배를 확정했어도 판정하지 않는다(화물 사실이 없다). 배를 확정하지 못했거나 조회에 실패하면 위치와 일정을 부르지 않고 화물 사실만으로 판정한다. 도착 시각을 모르면 8a의 규칙대로 등급 칸이 비고 확신이 "불명"이다. 화면은 "등급 없음"과 까닭을 보인다 | 자료가 모자랄수록 등급이 좋아지면 안 된다(8a 결정 6) | 없음 |
| B13 | 판정에 판매 예정일, 처음 알던 도착 예정, 포워더가 알려 준 날, 지난 위치를 넘기지 않는다. 카드의 참고 글이 그렇다고 말한다("판매 예정일을 받지 않아 여유 일수는 세지 않았어요", "처음 알던 도착 예정이 없어 지연은 보지 못했어요"). 글은 `rules/verdict.yaml info`에 한 곳만 둔다 | 받는 통로가 아직 없다(품목 사실 뽑기와 지시문을 바꾸는 일이라 8c) | 여유 일수로 오르는 등급(경계, 긴급)과 "지연"은 이 부분에서 나오지 않는다 |
| B14 | 화면으로 가는 값은 `view.screen_view`가 고른 칸뿐이다: 배(상태, 까닭 글, 조회 오류의 정한 글, 서류로 본 결과, 이름, 호출부호, 배 번호)와 판정(등급 이름과 글, 확신, 일정, 믿을 ETA와 출처, 여유 일수, 켜진 신호의 글, 까닭 글, 참고 글). 칸을 붙일지는 공책이 아니라 서버의 스위치(그래프에 `vessel` 노드가 있는지)가 정한다: 켰다가 끈 대화의 옛 칸은 꺼진 서버에서 보이지 않는다. "배를 확인한 뒤에 보여 드려요"는 선택 카드로 묻는 중일 때만 쓰고, 이번 차례에 배를 보지 않은 화물에는 "이번 차례에는 배를 보지 않았어요"를 쓴다. ShipFinder 한도 소진과 일시 실패는 클라이언트의 정한 오류 글(`rules/shipfinder.yaml`)을 그대로 보여 갈린다. 실제 배 이름과 식별자를 주인에게 보인다 | 주인이 "이 배가 맞나"를 눈으로 확인할 수 있어야 한다. 화물 번호를 주인에게 되돌려 보이는 것과 같다 | 가리기로 정하면 `view._ship`의 세 칸을 빼면 된다 |
| B15 | 가림: 배 이름·호출부호·배 번호·IMO는 가림 표(`mask_map`)에 넣지 않는다(모델에 가지 않는다). MRN은 화물 번호처럼 다루어 공책의 새 칸과 선택 카드에 넣지 않는다. 배 번호는 공책에 글로 둔다(숫자는 가림을 지난다). 트레이스 가림(`trace.scrub`)은 받은 값 안의 `vessels`·`candidates`·`hits`와 MRN 호출부호(`mrn_call_sign`)에서 이름·호출부호·배 번호(세 글자 이상)를 모아 그 값 안에서 값으로 가린다. 상태를 두지 않는다: 한 번 부른 값이 다음 호출에 남지 않는다 | 프로세스 기억(전역 집합)은 다시 띄우거나 프로세스가 여럿이면 빈다. Langfuse는 span마다 값을 따로 가림에 넣으므로 시험도 값마다 따로 넣는다 | 남는 구멍: 세관이 준 화물 사실의 `vessel_name`은 그 옆에 배 값이 없어 지금도 남는다(8b 전부터의 동작). 사용자 글에 직접 적은 배 이름에는 가릴 근거 값이 없다. 대화 저장소의 공책에는 이름이 평문으로 있다(암호화 직렬화기를 지난다고 본다 [추정]) |
| B16 | 배 신호의 목적지 원문은 공책, 화면, 트레이스 어디에도 없다 | 8a 결정 12. 위치 값(`Position`)은 공책에 넣지 않고 판정 결과만 넣는다. 판정의 신호 값은 항구 코드나 정한 낱말이다 | 없음 |
| B17 | 기존 재생 화물 다섯 건(`DEMO0001~3`, `MOCK12345678`, `TEST87654321`)은 고치지 않는다. 배로 이어지는 화물은 새 재생 화물 일곱(`TESTVSL0001~7`)이다: 1은 MRN으로 호출부호에 닿아 확정, 2는 같은 이름 셋(되묻기), 3은 인천·후보 없음, 4는 한 척이고 서류는 맞지만 위치 파일이 없음, 5는 한 척인데 입항 신고가 없음(되묻기), 6은 반입신고 단계(내린 화물), 7은 서명 없는 MRN 신고와 호출부호가 같은 두 배(서류로 가르는 길과 R-132) | 다섯 건은 평가 문항과 기존 화면 그림이 쓴다. 기존 다섯의 단계는 모두 반입신고라 스위치를 켜면 "배에서 내린 화물"로 보인다 | 없음 |
| B18 | 화면 시험은 실행을 둘로 나눈다: 기본(`E2E_VESSEL` 없음)은 기존 흐름만 돌아 그림 셋이 그대로이고, `E2E_VESSEL=on`은 배 식별 흐름만 돈다. 가짜 API는 판정의 기준 시각을 재생 배의 마지막 위치 수신 30분 뒤로 고정한다. 통과 기준: 기본 실행 뒤 기존 그림 셋(`answer.png`, `choice.png`, `approval.png`)이 바이트까지 같다 | 켜면 화물 카드에 칸이 늘어 기존 그림이 달라진다. 기준 시각이 실제 시계면 재생 배가 "위치 끊김"으로 보이고 그림이 날마다 달라진다 | 화면 시험을 두 번 돌려야 한다 |
| B19 | 재생 응답(`fixtures/mof`, `fixtures/shipfinder`)은 e2e 이미지에만 복사한다. 운영 이미지에는 넣지 않는다 | 운영은 실제 조회(`live`)로 쓴다. 가공값을 운영 이미지에 실을 까닭이 없다 | 운영 이미지에서 스위치만 켜고 조회를 재생으로 두면 배를 하나도 찾지 못한다 |
| B20 | 감시 재조회(`scripts/recheck_watch.py`, `src/marvia/watch.py`)는 배를 조회하지 않는다 | 주기 실행이 ShipFinder 하루 한도를 쓴다. 고정 시험이 `watch.py`가 새 모듈을 가져다 쓰지 않음을 본다 | 감시 중인 화물의 배 변화(도착 예정이 밀림)는 알리지 못한다 |
| B21 | 후보의 국적은 조회하지 않는다(모르는 값으로 넘긴다) | 후보마다 ShipFinder를 한 번 더 불러야 하고 8a는 국적 조회의 편의 함수를 두지 않았다. `match_vessel`은 국적을 모르면 "다르지 않다"로 본다 | 후보가 한 척인데 국적이 세관 기록과 다른 경우를 걸러 내지 못한다. MRN 호출부호가 있으면 그 대조는 그대로 걸린다 |
| B22 | 후보 수·화물 수·쪽 수의 값은 모두 `rules/vessel.yaml`이고 코드에 숫자로 적지 않는다 | 설계 1절 | 없음 |

## Global Constraints

- 숫자·등급·기한은 코드(`src/marvia/tools`)가 계산한다. 이 계획의 코드는 LLM을 부르지 않고, 모델이 낸 값으로 배를 고르거나 등급을 바꾸지 않는다.
- 임계값·목록·정한 글은 `rules/*.yaml`에 둔다. 이 부분의 값과 글은 새 파일 `rules/vessel.yaml`(상한, 질문·선택지·가정 글, 까닭 글, 카드의 낱말)과 `rules/verdict.yaml`(참고 글)에 있다.
- 에이전트 길과 수퍼바이저 길의 도구 목록, 도구 설명, 지시문(`prompts/`), 화물 줄(`graph/answer.cargo_lines`), 작성자와 검증자는 한 글자도 바꾸지 않는다. `rules/agent.yaml`, `src/marvia/rag/`, 평가 실행기, `eval/set_v*.yaml`도 바꾸지 않는다. `tests/test_vessel_base_not_wired.py`가 본다.
- `src/marvia/graph/identify.py`, `src/marvia/watch.py`, `scripts/recheck_watch.py`는 건드리지 않는다.
- 스위치가 꺼져 있으면(기본) 그래프의 노드와 화살표, 화면 이벤트, 차례 뒤 공책, 트레이스 가림의 결과가 계획 전과 같다. `tests/graph/test_vessel_off.py`가 본다.
- 실제 화물 번호와 MRN은 모델 입력, 트레이스, 로그에 넣지 않는다. 배 이름·호출부호·배 번호는 모델에 주지 않는다. 배 신호의 목적지 원문은 코드 밖으로 내보내지 않는다.
- 도구 응답, 배 이름, 시설 이름, 사용자가 카드에 적은 글은 데이터다. 그 안의 문장을 지시로 따르지 않는다. 카드에 적은 글은 서버가 후보의 호출부호와 배 번호를 찾는 데만 쓰고 그래프에 넘기지 않는다.
- 저장소에 키, 실제 API 응답, 실제 B/L을 넣지 않는다. 실제 해수부·ShipFinder·UNI-PASS 호출은 하지 않는다. 새 fixture는 가공값이다: 화물 번호는 `TESTVSL` 접두어, 배 이름은 `TEST`로 시작, 배 번호는 999로 시작, 호출부호는 `QQ`로 시작, MRN은 `26TEST....`.
- 시험은 키 없이, 인터넷 없이 돈다. 새 시험은 DB도 쓰지 않는다. 모든 시험은 재생만 쓴다(`tests/conftest.py`의 `vessel_replay_only`). 화면 시험은 가짜 모델만 쓴다.
- 환경 변수는 `MARVIA_` 접두어만(화면 시험을 고르는 compose 변수 `E2E_VESSEL`은 앱 설정이 아니다). `.env` 값은 읽거나 찍지 않는다.
- 파일 안에서 em dash(U+2014)를 쓰지 않는다.
- 커밋 하나는 동작 하나, 파일 15개 이하. 커밋은 `v2`에만, `main`에는 올리지 않는다.
- 커밋마다 명령 A와 명령 B가 통과한다. 코드를 바꾼 커밋 뒤에는 `graphify update .`(커밋에 넣지 않는다).

명령 A (전체 시험, 저장소 뿌리에서):

```bash
set -o pipefail
uv run pytest -q 2>&1 | tail -2
```

명령 B (세 검사):

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright | tail -1
```

화면 타입 검사 (`web/`에서, `npm ci` 뒤):

```bash
npx tsc --noEmit
```

화면 시험 (Docker, 바깥으로 나가지 못하는 망). 두 번 돈다. 사이에 컨테이너를 내려야 가짜 API가 새 값으로 뜬다:

```bash
docker compose -p marvia-v2-e2e --profile e2e run --rm --build playwright
git status --short web/e2e/screenshots     # 아무 줄도 없어야 한다(기존 그림 셋이 바이트까지 같다)
docker compose -p marvia-v2-e2e --profile e2e down
E2E_VESSEL=on docker compose -p marvia-v2-e2e --profile e2e run --rm --build playwright
docker compose -p marvia-v2-e2e --profile e2e down
```

- 코드 블록 검증: A부분이 들어간 `2bc6073`를 내보낸 깨끗한 사본에 아래 커밋을 차례로 쌓고, 커밋마다 명령 A와 명령 B를 돌렸다. 사본의 시험은 개발 DB가 아니라 검증용 DB(`marvia_verify`)에 붙였고 시험 스키마는 실행마다 무작위 이름이다. 시험용 Neo4j는 꺼 둔 상태라 8개가 건너뛰어졌다. 기준(`2bc6073`)은 1205 passed, 8 skipped이고 커밋마다의 수는 아래 표다. 커밋마다 ruff, 형식, pyright 오류 0이었다. 한 커밋의 파일은 14개 이하다 [실측 11-16]. 이 문서의 diff 블록 55개만으로 `2bc6073`을 내보낸 새 사본에 다시 깔아 보았다: 쌓은 사본과 파일이 모두 같았고, 그 새 사본에서 전체 시험은 1271 passed, 8 skipped였다 [실측 11-16].

| 커밋 (Task) | 제목 | 파일 수 | 전체 시험 (명령 A) |
|---|---|---|---|
| 1 | `test: 고정 묶음에서 계획 8b가 고치는 다섯 파일만 빼고 '스위치가 꺼져 있으면 동작이 같다'로 대신함` | 2 | 1209 passed, 8 skipped |
| 2 | `feat(tools): 배 식별 규칙 파일과 스위치 MARVIA_VESSEL(기본 off), 배 한 척의 입항 신고 조회를 둠` | 7 | 1213 passed, 8 skipped |
| 3 | `test(tools): 배로 이어지는 재생 화물 일곱(TESTVSL0001~7)과 배 검색 재생 셋, 입항 신고 재생 둘. 측정한 다섯 화물의 묶음은 그대로 둠` | 14 | 1214 passed, 8 skipped |
| 4 | `feat(graph): 화물 한 건의 배를 찾는 함수. MRN 호출부호나 MRN 조회가 성공한 서류로 맞춰 본 칸이 있을 때만 확정하고 요청 수 상한을 지킴` | 5 | 1227 passed, 8 skipped |
| 5 | `feat(graph): 배 식별 단계(vessel, ask_vessel, verdict)를 스위치 뒤에 붙임. 고른 배는 고른 뒤에 같은 검사에 걸고 확신 상한은 판정이 건다` | 5 | 1251 passed, 8 skipped |
| 6 | `feat(server): 스위치가 켜져 있으면 화물 카드에 배와 판정 칸을 보임. 선택 카드는 자리표를 후보로 바꾸고 직접 적은 글은 번호로 바꿔 넘김` | 4 | 1266 passed, 8 skipped |
| 7 | `feat(trace): 받은 값 안의 vessels·candidates에서 배의 이름·호출부호·배 번호를 모아 그 값 안에서 값으로 가림` | 2 | 1268 passed, 8 skipped |
| 8 | `test(server): 환경에 스위치를 켜도 평가 실행기의 그래프에는 배 식별 단계가 없고, 스위치를 넘기는 곳은 서버와 가짜 API뿐임을 동작으로 고정` | 2 | 1270 passed, 8 skipped |
| 9 | `feat(web): 화물 카드에 배와 판정 칸. 화면 시험은 E2E_VESSEL=on일 때 배 식별 흐름 다섯을 돌림` | 7 | 1271 passed, 8 skipped |
| 10 | `docs: 배 추적 모듈의 '아직 연결 전' 주석을 배 식별 단계 연결로 고치고 README와 설계에 스위치 뒤의 화물 카드 칸을 적음` | 7 | 1271 passed, 8 skipped |

- 아래 Task의 Expected는 이 표의 수(건너뜀 8 기준)다. 시험용 Neo4j를 켜고 돌리면 통과 수가 8만큼 많다.
- 새 시험만 키와 DB 없이 돌린 것: `MARVIA_DATABASE_URL`을 닿지 않는 주소로 두고 키 환경 변수 다섯을 지운 채 `uv run pytest -q tests/graph/test_vessel_off.py tests/graph/test_vessel_step.py tests/graph/test_vessel_screen.py tests/tools/test_vessel_rules.py tests/tools/test_mof.py tests/tools/test_judge.py tests/tools/test_vessel_match.py tests/test_vessel_base_not_wired.py tests/test_docker.py` → `143 passed, 1 skipped` [실측 11-16, 마지막 커밋].
- 판정 평가 문항: `uv run python scripts/verdict_check.py` → `ported: 20/20`, `port: 5/5`, `conflict: 33/33`, `nodata: 13/13`, `failure: 6/6`, `stage: 7/7`, `edge: 34/34`, `배 확정: 22/22` [실측 11-16, 마지막 커밋]. 파일의 sha256은 `eval/verdict_set_v1.sha256`이다(이 부분은 문항 파일을 바꾸지 않는다).
- 화면: `web/`에서 `npx tsc --noEmit`은 출력 없이 끝났다(오류 0) [실측 11-16, 마지막 커밋]. **화면 시험(Playwright)과 `next build`는 돌리지 않았다.** 대신 가짜 API의 그래프를 프로세스 안에서 스위치를 켜고 꺼서 돌려, 화면 시험이 기대하는 글(배 이름과 식별자, "순항", "일정 모름", "등급 없음", 선택 카드의 질문과 선택지, 서류로 본 결과, 까닭 글)이 화면 스냅샷에 그대로 나오고 꺼진 서버에는 새 칸이 없는 것까지 봤다 [실측 11-15]. 그림 넷(`vessel-*.png`)은 실행 때 처음 생긴다.

---

## 사전 등록: 검사 CB1~CB14 (구현 전에 고정)

이 절은 첫 구현 커밋 전에 이 문서와 함께 커밋하고, 결과를 본 뒤 기준을 고치지 않는다. 고칠 일이 생기면 이유와 시각을 따로 적고 원래 기준의 판정도 함께 적는다.

| # | 검사 | 통과 기준 | 시험 | 깨 보았을 때 (사본, 실측 11-16) |
|---|---|---|---|---|
| CB1 | 꺼져 있으면 같다 | 스위치를 넘기지 않고 만든 그래프에서: 길 셋(계획자, 에이전트, 수퍼바이저)의 노드와 화살표, 가짜 모델 대본 한 차례(재생 화물 둘, 할 일 쓰기와 기한 계산)의 화면 이벤트 전체, 그 차례 뒤 공책의 칸 이름·화물 칸·화면 보기, 길 셋의 한 차례와 그 이벤트·공책을 트레이스 가림에 넣은 결과의 sha256이 계획 전 값과 같다. 조회 시각만 뺀다. 화물 카드의 칸은 기존 여덟 개뿐이고 공책에 `vessels`, `verdicts`, `vessel_question` 칸이 없다 | `tests/graph/test_vessel_off.py`의 앞 넷 | 스위치 기본값을 켬: 잡음 |
| CB2 | 켜는 길은 서버 하나 | 환경에 `MARVIA_VESSEL=on`을 넣고 평가 실행기가 만든 그래프(계획자 길과 에이전트 길)에 `vessel` 노드가 없다. `src/`, `scripts/`, `e2e/`에서 `build_main_graph`에 `vessel=` 키워드를 넘기는 곳은 서버 진입점과 가짜 API뿐이고 값은 둘 다 `settings.vessel == 'on'`이다. 설정의 기본은 `off`이고 compose의 운영 서비스(`api`, `prepare`)는 스위치를 주지 않는다 | `test_vessel_off.py`의 켜는 길 시험 둘, `test_vessel_rules.py::test_the_switch_is_off_unless_asked`, `test_docker.py` | 서버가 스위치를 늘 켬: 잡음; 서버가 켜진 그래프인지 보지 않고 늘 칸을 붙임: 잡음 |
| CB3 | 측정이 지나는 길은 그대로 | 8a의 고정 시험에서 그래프 묶음은 열한 파일(`main.py`, `state.py` 제외)로, 서버·화면·감시·추적 묶음은 다섯 파일(`server.py`, `view.py`, `trace.py` 제외)로 줄고 값을 `48ca3c5`에서 다시 셌다. 나머지 묶음과 도구 이름·설명, 화물 줄은 그대로 통과한다. 조회·판정 모듈을 부르는 그래프 쪽 파일은 `graph/vessel.py` 하나다 | `tests/test_vessel_base_not_wired.py` | 측정한 재생 화물을 고침: 잡음 |
| CB4 | 찾는 쪽은 `check_candidate`를 부르지 않는다 | 되묻기로 가는 화물에서 찾는 쪽은 `check_candidate`를 한 번도 부르지 않고, 후보의 `check`는 `match_vessel`의 이유만이다. 코드 문법 트리로 `graph/vessel.py`에서 `check_candidate`를 부르는 함수는 `check_pick` 하나다 | `test_vessel_step.py::test_the_finder_never_calls_check_candidate_only_the_pick_step_does` | 찾는 쪽이 후보마다 check_candidate를 부름(고르기 전 서류 조회와 한 척 상한): 잡음 |
| CB5 | 배는 코드가 정한다 | MRN 호출부호와 후보가 글자까지 같으면 확정. 그 밖에는 한 척이어도 되묻는다. MRN 호출부호가 없을 때(조회가 성공했고 신고에 호출부호가 없을 때)만 서류가 맞아야 확정한다. 같은 이름의 후보가 여럿이고 서류로 가르지 못하면 고르지 않는다. 후보 없음, 단서 없음(바깥을 부르지 않는다), 조회 실패는 배를 지어내지 않는다. 후보가 상한을 넘으면 후보마다의 해수부 조회를 하지 않고 되묻는다 | `tests/graph/test_vessel_step.py`의 찾기 시험, 배 확정 문항 22개 | 내린 단계에서도 배를 찾음: 잡음; MRN 조회 결과를 배 확정에 넘기지 않음: 잡음; 조회 오류 글을 카드에 싣지 않음: 잡음; 권고를 첫 후보로: 잡음 |
| CB6 | 배를 보는 단계 | 내린 단계의 화물은 찾기와 위치·일정 조회에서 바깥 호출이 0번이고 판정은 통관 단계만으로 낸다. 배를 보는 단계, 통관이 멈춘 단계, 모르는 단계는 배 신호를 그대로 쓴다 | `test_vessel_step.py`의 내린 화물 시험 둘 | 내린 단계에서도 배를 찾음: 잡음 |
| CB7 | 선택 카드와 답 처리 | 멈춘 값의 칸은 `kind`, `options`, `question`, `recommended` 넷뿐이고 후보 이름·호출부호·배 번호가 없다(자리표만). 질문에는 가린 이름표만 있다. 권장은 0번 "모르겠어요"이고 선택지는 셋이다. 화면으로 갈 때 자리표가 후보의 이름과 설명(호출부호, 배 번호, 서류로 본 결과)으로 바뀌고 질문의 이름표는 실제 번호로 돌아온다. 1번·2번은 그 배(`user_choice`), 0번은 `user_skipped`, 시간 초과와 취소는 `no_answer`이고 가정이 정확히 한 줄 생기며 그 글에 이름표가 있고 배 이름이 없다. 직접 적은 글은 서버가 번호로 바꿔 넘기고(후보 한 척에만 맞을 때만, 아니면 0번) 그래프는 번호만 받는다. 어느 답이든 판정은 난다 | `test_vessel_step.py`의 선택 카드·답 시험, `test_vessel_screen.py`의 선택 카드 시험 | 선택 카드 끼어들기 값에 이름을 실음: 잡음; 자리표를 이름으로 바꾸지 않음: 잡음; 직접 입력을 번호로 바꾸지 않고 그대로 넘김: 잡음; 배 카드인지를 공책의 옛 질문으로 가름: 잡음; 가정 글에 배 이름: 잡음; 권고를 첫 후보로: 잡음 |
| CB8 | 고른 배는 자동 확정과 구분된다(R-126) | 고른 배의 행은 상태 `user_choice`와 이유·근거·상한을 가지고 공책에 남으며 상한은 판정까지 닿는다(`ship_unchecked`). 화면의 이유 글은 "고르신 배로 봤어요"이고 맞춰 본 결과 글은 그 행의 이유 글이다. 카드 글은 상태가 아니라 이유와 근거에서 만들고 고른 배에는 "확실"이 읽히지 않는다 | `test_a_picked_ship_stays_a_user_choice_with_its_reason_and_the_cap_reaches_the_judge`, `test_vessel_screen.py::test_a_picked_ship_is_a_user_choice_on_the_card_and_nothing_on_it_reads_as_sure` | 고른 배의 결과를 자동 확정(confirmed)으로 저장: 잡음; 판정 단계가 고른 배(user_choice)를 항해 중으로 보지 않음: 잡음; 판정에 확신 상한을 넘기지 않음: 잡음 |
| CB9 | 고른 배의 검사는 검색 결과 전체와 견준다(R-132) | 같은 호출부호의 배 셋 가운데 카드에는 둘만 보이고 그중 하나를 고르면 확신 상한(부분)이 걸린다. 고른 뒤 서류로 맞추는 길에서는 그 배의 입항 신고를 정확히 한 번 받고, 받지 못하면 조회 실패(상한 부분, 이유 `mrn_lookup_failed`)다 | `test_a_pick_is_checked_against_every_search_hit_not_only_the_ones_the_card_shows`, `test_the_pick_refetches_only_the_picked_ships_report_and_a_failure_is_a_lookup_failure`, `test_a_pick_among_ships_sharing_a_call_sign_is_capped_even_though_the_call_sign_matches` | 고른 배 검사에 카드에 보인 후보만 넘김(검색 전체를 넘기지 않음): 잡음; 고른 배의 입항 신고를 다시 받지 않음: 잡음 |
| CB10 | 한 번만 묻고 상한을 지킨다 | 가르지 못한 화물이 둘이면 카드는 하나이고 둘째는 `another_question`. 화물 수 상한을 2로 낮추면 셋째 화물은 찾지 않는다. 확정한 배의 위치·일정 조회도 같은 상한을 세고 조회하지 않은 화물은 등급이 없다. 한 화물의 요청 수는 상한(찾기 14, 판정 3, 고른 뒤 1)을 넘지 않고 닿으면 `call_limit`이다. 같은 날의 입항 신고 목록은 한 번만 받는다. 시간 상한에 닿으면 남은 화물은 `time_limit`이다. 상한 숫자 사이의 산수가 맞고 MRN 쪽 수 상한이 v1 실측에서 셈한 쪽 수 이상이다. 판정의 입항 일정 조회는 세관 입항일을 받는다 | `test_vessel_step.py`의 상한 시험 여섯과 `test_the_schedule_lookup_gets_the_customs_entry_date` | 입항 일정 조회에 세관 입항일을 넘기지 않음: 잡음; 한 차례의 화물 수 상한을 뺌: 잡음; 판정 단계의 조회 상한을 뺌: 잡음; 시간 상한을 뺌: 잡음; 요청 수 상한(MRN 쪽 수)을 뺌: 잡음; 같은 날 입항 신고 목록을 다시 받음: 잡음 |
| CB11 | 지어내지 않는다 | 후보가 없는 화물과 도착 시각을 알 출처가 없는 화물은 등급이 값 없음, 확신이 불명이고 이유에 `no_position`, `no_eta`가 있다. 화면의 등급 글은 "등급 없음", 일정 글은 "일정 모름"이다. 조회 오류는 정한 글 그대로 보인다(한도 소진과 일시 실패가 갈린다). 재생 배 한 척을 확정하면 해수부 입항 예정으로 "순항, 확실, 일정 모름"이 나오고 기준 시각을 9시간 뒤로 옮기면 "주의"와 켜진 신호의 글이 보인다 | `test_vessel_step.py`, `test_vessel_screen.py`의 카드 시험들 | 조회 오류 글을 카드에 싣지 않음: 잡음 |
| CB12 | 모델과 트레이스에 가지 않는다 | 배를 확정한 차례의 작성자 프롬프트와 대화 기록 전체에 호출부호, 배 번호, MRN이 없다. 공책 전체를 글로 찍었을 때 재생 배의 목적지 원문("BUSAN, KR")이 없다. 선택 카드에서 멈춘 차례, 번호로 재개한 차례, 확정한 차례의 콜백 입력과 출력을 하나씩 따로 `trace.scrub`에 넣으면 호출부호, 배 번호, MRN, 화물 번호가 남지 않고 배 값이 든 값에서는 배 이름도 남지 않는다(`hits`와 MRN 호출부호 포함). `scrub`은 상태가 없다 | `test_ship_identifiers_and_ais_text_never_reach_the_model`, `test_trace_scrub_hides_ships_the_step_met_inside_each_payload`, `test_scrub_is_stateless_and_only_hides_values_found_inside_what_it_is_given` | 트레이스의 값 가림을 끔: 잡음; 호출부호를 가정 글(작성자 입력)로 흘림: 잡음 |
| CB13 | 기억 | 확정한 배는 다음 차례에 다시 찾지 않는다. 화물을 말하지 않은 차례를 사이에 둬도 잊지 않고, 그 차례에는 판정이 없다. 배를 확정한 화물의 조회가 이번 차례에 실패하면 판정하지 않고 확정은 남는다 | `test_a_confirmed_ship_is_not_looked_up_again_next_turn`, `test_a_confirmed_ship_is_remembered_across_turns_that_do_not_name_the_cargo`, `test_a_cargo_whose_lookup_fails_this_turn_gets_no_verdict_even_if_its_ship_was_confirmed` | 확정한 배를 차례마다 다시 찾음: 잡음 |
| CB14 | 화면 | 스위치를 켠 서버의 화물 카드 칸은 기존 여덟에 `ship`, `verdict`를 더한 열이고 꺼진 서버는 새 칸이 없다(켰다가 끈 대화의 공책에 옛 값이 있어도). 이번 차례에 배를 보지 않은 화물은 그렇다고 말한다. 판정 문항과 배 확정 문항이 모두 통과한다. 타입 검사 오류 0. 화면 시험: 기본 실행은 기존 흐름이 통과하고 그림 셋이 바이트까지 같다. `E2E_VESSEL=on` 실행은 배 식별 흐름(확정, 고르기, 같은 이름 둘, 모르겠어요, 내린 화물, 등급 없음)이 통과하고 접근성 검사에 심각·치명 위반이 없다 | `test_vessel_screen.py`, `tests/eval/test_verdict_set.py`, `web/e2e/flows.spec.ts`의 "배 식별" 묶음 | 화면 시험은 이 문서를 쓸 때 돌리지 못했다. 실행 때 처음 돈다 |

깨 보기는 마지막 커밋의 사본에서 한 곳씩(28가지) 바꿔 관련 시험 열 파일을 돌리고 되돌렸다. 목록과 결과는 아래 "깨 보기"에 있다. 되돌린 뒤에는 모두 통과했다.

## 깨 보기

사본에서 한 곳씩 바꾸고 시험 열 파일을 `-x`로 돌려 처음 틀린 시험을 적었다(실측 11-16):

| # | 바꾼 것 | 결과 | 틀린 시험 |
|---|---|---|---|
| MB01 | 스위치 기본값을 켬 | 1 failed in 1.67s | test_graph_shape_is_unchanged_when_the_switch_is_off |
| MB02 | 서버가 스위치를 늘 켬 | 1 failed, 4 passed in 2.09s | test_the_eval_runner_builds_a_graph_without_the_vessel_step_even_when_the_env_asks_for_it |
| MB03 | 서버가 켜진 그래프인지 보지 않고 늘 칸을 붙임 | 1 failed, 1 passed in 1.29s | test_screen_stream_is_unchanged_when_the_switch_is_off |
| MB04 | 내린 단계에서도 배를 찾음 | 1 failed, 13 passed in 1.86s | test_cargo_off_the_ship_is_not_looked_up_at_all |
| MB05 | MRN 조회 결과를 배 확정에 넘기지 않음 | 1 failed, 8 passed in 1.74s | test_papers_decide_between_two_ships_only_when_the_mrn_report_has_no_call_sign |
| MB06 | 찾는 쪽이 후보마다 check_candidate를 부름(고르기 전 서류 조회와 한 척 상한) | 1 failed, 10 passed in 1.76s | test_ships_sharing_a_call_sign_are_asked_and_a_pick_among_them_is_capped |
| MB07 | 고른 배 검사에 카드에 보인 후보만 넘김(검색 전체를 넘기지 않음) | 1 failed, 29 passed in 3.25s | test_a_pick_among_ships_sharing_a_call_sign_is_capped_even_though_the_call_sign_matches |
| MB08 | 판정에 확신 상한을 넘기지 않음 | 1 failed, 20 passed in 2.31s | test_papers_only_ship_is_capped_at_partial_even_with_every_other_input_clear |
| MB09 | 입항 일정 조회에 세관 입항일을 넘기지 않음 | 1 failed, 19 passed in 1.90s | test_the_schedule_lookup_gets_the_customs_entry_date |
| MB10 | 선택 카드 끼어들기 값에 이름을 실음 | 1 failed, 23 passed in 2.71s | test_same_name_ships_stop_for_a_choice_card_with_placeholders_not_names |
| MB11 | 자리표를 이름으로 바꾸지 않음 | 1 failed, 51 passed in 4.80s | test_choice_card_shows_real_names_in_place_of_placeholders_and_the_typed_text_becomes_a_nu |
| MB12 | 직접 입력을 번호로 바꾸지 않고 그대로 넘김 | 1 failed, 51 passed in 5.34s | test_choice_card_shows_real_names_in_place_of_placeholders_and_the_typed_text_becomes_a_nu |
| MB13 | 배 카드인지를 공책의 옛 질문으로 가름 | 1 failed, 56 passed in 5.57s | test_an_old_unanswered_ship_question_does_not_take_over_a_later_card |
| MB14 | 한 차례의 화물 수 상한을 뺌 | 1 failed, 32 passed in 3.39s | test_only_the_first_undecided_cargo_is_asked_and_the_cap_stops_lookups |
| MB15 | 판정 단계의 조회 상한을 뺌 | 1 failed, 38 passed in 3.65s | test_the_cap_also_limits_position_and_schedule_lookups_for_ships_already_confirmed |
| MB16 | 시간 상한을 뺌 | 1 failed, 34 passed in 3.36s | test_the_time_cap_leaves_the_rest_of_the_cargos_unlooked |
| MB17 | 요청 수 상한(MRN 쪽 수)을 뺌 | 1 failed, 15 passed in 1.69s | test_the_call_budget_per_cargo_stops_before_the_limit_is_passed |
| MB18 | 같은 날 입항 신고 목록을 다시 받음 | 1 failed, 16 passed in 1.82s | test_the_same_day_sailing_list_is_fetched_once_per_turn |
| MB19 | 조회 오류 글을 카드에 싣지 않음 | 1 failed, 12 passed in 1.97s | test_no_candidate_no_clue_and_failed_lookup_never_name_a_ship |
| MB20 | 트레이스의 값 가림을 끔 | 1 failed, 42 passed in 4.10s | test_trace_scrub_hides_ships_the_step_met_inside_each_payload |
| MB21 | 가정 글에 배 이름 | 1 failed, 27 passed in 3.85s | test_the_reply_to_the_choice_card_decides_and_no_answer_is_an_assumption |
| MB22 | 측정한 재생 화물을 고침 | 1 failed, 2 passed in 1.26s | test_state_after_a_turn_is_unchanged_when_the_switch_is_off |
| MB23 | 권고를 첫 후보로 | 1 failed, 23 passed in 2.50s | test_same_name_ships_stop_for_a_choice_card_with_placeholders_not_names |
| MB24 | 호출부호를 가정 글(작성자 입력)로 흘림 | 1 failed, 40 passed in 4.02s | test_ship_identifiers_and_ais_text_never_reach_the_model |
| MB26 | 고른 배의 입항 신고를 다시 받지 않음 | 1 failed, 31 passed in 2.91s | test_the_pick_refetches_only_the_picked_ships_report_and_a_failure_is_a_lookup_failure |
| MB27 | 고른 배의 결과를 자동 확정(confirmed)으로 저장 | 1 failed, 24 passed in 2.24s | test_the_reply_to_the_choice_card_decides_and_no_answer_is_an_assumption |
| MB28 | 판정 단계가 고른 배(user_choice)를 항해 중으로 보지 않음 | 1 failed, 28 passed in 3.78s | test_a_picked_ship_stays_a_user_choice_with_its_reason_and_the_cap_reaches_the_judge |
| MB25 | 확정한 배를 차례마다 다시 찾음 | 1 failed, 35 passed in 3.56s | test_a_confirmed_ship_is_not_looked_up_again_next_turn |

되돌린 뒤: 155 passed in 5.25s

28가지 가운데 28가지를 시험이 잡았다.

MB09는 처음 돌렸을 때 시험이 통과했다(입항 일정 조회에 세관 입항일을 넘기지 않아도 재생 응답은 같다). 그래서 `test_the_schedule_lookup_gets_the_customs_entry_date`를 T5에 더했고 다시 돌려 잡혔다.

## 비용

LLM 호출 0, 바깥 API 호출 0. 유료 실행이 없다. 스위치를 켜고 조회를 `live`로 두는 일(해수부, ShipFinder 실제 호출)은 이 계획에 없고 주인이 정할 일이다.

## 파일 구조

| 파일 | 하는 일 | Task |
|---|---|---|
| `tests/test_vessel_base_not_wired.py` | 그래프 묶음에서 `main.py`·`state.py`를, 서버 묶음에서 `server.py`·`view.py`·`trace.py`를 빼고 재생 화물 묶음을 측정한 다섯 파일의 이름으로 가리킨다 | 1, 3 |
| `tests/graph/test_vessel_off.py` (새로) | 꺼져 있으면 같다, 켜는 길은 서버 하나 | 1, 8, 10 |
| `rules/vessel.yaml` (새로), `src/marvia/config.py`, `.env.example` | 상한과 시간, 질문·선택지·가정 글, 까닭 글, 카드의 낱말, 켜진 신호의 글. 설정 칸 `vessel`(`MARVIA_VESSEL`) | 2, 4, 5, 6 |
| `src/marvia/tools/mof.py` | 배 한 척의 입항 신고 조회(`plans_for`), 쪽 수 상한 인자 | 2, 4 |
| `fixtures/unipass/TESTVSL0001~7.json`, `fixtures/shipfinder/VesselSearch/{TEST_CARGO_C,TEST_CARGO_E,QQTWN}.json`, `fixtures/mof/VsslEtrynd5/020/{QQTST4,_ALL}.xml` (새로) | 배로 이어지는 재생 화물 일곱과 검색·입항 신고 재생 | 3 |
| `src/marvia/graph/vessel.py` (새로) | 배 찾기 함수, 고른 뒤의 검사(`check_pick`), 노드 셋(vessel, ask_vessel, verdict) | 4, 5 |
| `src/marvia/graph/state.py`, `src/marvia/graph/main.py` | 공책 칸 셋, `AgentDeps.now`, `build_main_graph(..., vessel=False)`와 화살표 | 5 |
| `src/marvia/view.py`, `src/marvia/server.py` | 화물 카드의 배·판정 칸, 자리표 채우기, 직접 입력의 번호 바꾸기, 스위치 읽기 | 6 |
| `src/marvia/trace.py` | 받은 값 안의 배 값을 모아 값으로 가림 | 7 |
| `e2e/fake_api.py` | 가짜 API의 스위치와 고정 시각 | 8 |
| `web/lib/agui.ts`, `web/components/CargoCards.tsx`, `web/e2e/flows.spec.ts` | 카드 타입과 칸, 화면 시험 | 9 |
| `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `tests/test_docker.py` | e2e 이미지의 재생 응답, `E2E_VESSEL` | 9 |
| `tests/tools/test_vessel_rules.py`, `tests/graph/test_vessel_step.py`, `tests/graph/test_vessel_screen.py` (새로) | 규칙·재생 화물, 단계, 화면 쪽 시험 | 2~7 |
| `README.md`, `docs/specs/2026-10-28-marvia-v2-design.md`, 8a 네 모듈의 머리 주석 | 문서 | 10 |

---

### Task 0: 사전 등록

- [ ] **Step 1**: 이 문서를 `docs/plans/2026-11-15-marvia-v2-plan-8b-part-b.md`로 커밋한다. 아래 코드 커밋보다 먼저다.

```bash
git add docs/plans/2026-11-15-marvia-v2-plan-8b-part-b.md
git commit -m "docs: 계획 8b B부분 배 식별 단계와 화물 카드의 판정 칸 (결정, 사전 등록 검사 CB1~CB14)"
```

### Task 1: 고정을 "꺼져 있으면 같다"로 바꾼다 (CB1, CB3)

**배울 것:** 파일 해시는 "아무도 건드리지 않았다"를 지켜 준다. 건드려야 하는 파일은 해시가 아니라 동작으로 묶는다: 그래프의 모양, 한 차례가 화면으로 보낸 이벤트 전체, 차례 뒤 공책, 길 셋의 한 차례를 트레이스 가림에 넣은 결과. 값은 코드를 바꾸기 전에 내서 적어 둔다. 해시로 남는 묶음은 이 부분이 고치지 않는 파일뿐이다.

#### 커밋 1: test: 고정 묶음에서 계획 8b가 고치는 다섯 파일만 빼고 '스위치가 꺼져 있으면 동작이 같다'로 대신함

**Files:**
- Modify/Create: 없음
- Test: `tests/graph/test_vessel_off.py`, `tests/test_vessel_base_not_wired.py`

**Interfaces:**
- Consumes: `build_main_graph`, `LOOPS`, `build_app`, `screen_view`, `trace.scrub`, 준비물 `agent_deps`.
- Produces: `tests/graph/test_vessel_off.py`의 `SHAPE_SHA`, `STREAM_SHA`, `STATE_SHA`, `LOOPS_SHA`, `CARD_KEYS`. 고정 시험의 `GRAPH_FILES`(열한 파일), 서버·화면·감시·추적 묶음을 다섯 파일로 줄이고 두 묶음의 값을 `48ca3c5`에서 다시 셌다. `ALLOWED`에 `src/marvia/graph/vessel.py`.

세 해시와 `LOOPS_SHA`는 코드를 바꾸기 전 상태에서 두 번 돌려 같은 값이 나오는 것을 본 뒤 적었다(조회 시각만 고정 글로 바꾼다). 이 커밋의 시험은 코드를 바꾸기 전 상태를 묶는 것이라 처음부터 통과한다. 묶였는지는 T5 뒤에 깨 보아 확인한다("깨 보기" 표의 MB01, MB03). 값이 다르게 나오면 고치지 말고 무엇이 달라졌는지부터 본다.

- [ ] **Step 1: 실패하는 시험**

```diff
--- /dev/null
+++ b/tests/graph/test_vessel_off.py
@@ -0,0 +1,126 @@
+"""배 식별 스위치가 꺼져 있으면(기본) 그래프, 화면 스트림, 공책, 트레이스 가림이 계획 8b 전과 같다 (C1).
+
+계획 8a의 고정 시험은 그래프 폴더와 서버·화면·추적 파일을 측정 커밋(48ca3c5)의 해시로 묶었다.
+계획 8b는 그 가운데 다섯 파일(graph/main.py, graph/state.py, server.py, view.py, trace.py)을 고친다.
+그 다섯은 해시 묶음에서 빼고 여기서 "스위치가 꺼져 있으면 동작이 같다"로 묶는다.
+나머지 파일은 해시 묶음에 그대로 남는다.
+아래 값은 계획 8b의 첫 코드 커밋 전(a632dff, 다섯 파일은 48ca3c5와 같다)에 낸 값이다.
+값이 달라지면 고치기 전에 무엇이 달라졌는지부터 본다.
+"""
+
+import hashlib
+import json
+
+from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
+from langchain_core.messages import AIMessage
+from langgraph.checkpoint.memory import InMemorySaver
+from langgraph.store.memory import InMemoryStore
+from starlette.testclient import TestClient
+
+from marvia.graph.main import LOOPS, build_main_graph
+from marvia.server import build_app
+from marvia.trace import scrub
+from marvia.view import screen_view
+
+# 길마다 그래프의 노드와 화살표 (get_graph). 스위치가 꺼져 있으면 노드 하나 늘지 않는다
+SHAPE_SHA = "e75c31fff2a5071a2a17b7db21c8b9fb3850f68a4507e87b8b891c2091130fa2"
+# 가짜 모델 대본 한 차례의 화면 이벤트 전체(조회 시각만 뺀 것)
+STREAM_SHA = "48a3d2b6d6d226e7dcc2ae8585de7f168f1442314538b39741d188e5f32a8394"
+# 그 차례가 끝난 뒤 공책의 칸 이름과 화물 칸(조회 시각만 뺀 것)
+STATE_SHA = "32b3a156446f45ec5f2be40b059ca30a46e744435c45e7888d971d5ec376aee7"
+# 길 셋의 한 차례씩: 화면 이벤트, 공책의 칸 이름, 그 둘을 트레이스 가림에 넣은 결과
+LOOPS_SHA = "99e5986c5e0f58cb7d17296aa97e89ce9923967e5f290a11b9b072f0fdd6b1b0"
+CARD_KEYS = ["error", "fetched_at", "number", "port", "source", "stage", "stage_at", "vessel"]
+
+
+class ToolModel(GenericFakeChatModel):
+    def bind_tools(self, tools, **kwargs):
+        return self
+
+
+def _sha(value) -> str:
+    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
+    return hashlib.sha256(text.encode("utf-8")).hexdigest()
+
+
+def _timeless(value):
+    """조회 시각(fetched_at)만 고정 글로 바꾼다. 실행마다 달라지는 값은 이것뿐이다."""
+    if isinstance(value, dict):
+        return {k: ("T" if k == "fetched_at" else _timeless(v)) for k, v in value.items()}
+    if isinstance(value, list):
+        return [_timeless(v) for v in value]
+    return value
+
+
+def _say(name: str, args: dict, n: int) -> AIMessage:
+    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": f"s{n}-{name}"}])
+
+
+def _turn(agent_deps, loop: str = "agent"):
+    todos = {"todos": [{"content": "기한 계산", "status": "in_progress"}]}
+    steps = (_say("write_todos", todos, 1), _say("calc_deadlines", {}, 2), AIMessage(""))
+    graph = build_main_graph(
+        agent_deps(model=ToolModel(messages=iter(steps))),
+        InMemorySaver(),
+        loop=loop,
+        store=InMemoryStore(),
+    )
+    client = TestClient(build_app(graph, lambda token: "user-a", web_origin="http://web.test", forget=print))
+    payload = {
+        "threadId": "off",
+        "runId": "run-off",
+        "messages": [{"id": "m1", "role": "user", "content": "DEMO0001 DEMO0002 언제까지 수입신고 해요?"}],
+    }
+    response = client.post("/agui", json=payload, headers={"Authorization": "Bearer tok"})
+    events = [json.loads(line[6:]) for line in response.text.split("\n") if line.startswith("data: ")]
+    return graph, events
+
+
+def test_graph_shape_is_unchanged_when_the_switch_is_off(agent_deps):
+    shapes = {}
+    for loop in LOOPS:
+        deps = agent_deps(model=ToolModel(messages=iter([])))
+        drawn = build_main_graph(deps, InMemorySaver(), loop=loop, store=InMemoryStore()).get_graph()
+        edges = sorted((e.source, e.target, bool(e.conditional)) for e in drawn.edges)
+        shapes[loop] = {"nodes": sorted(drawn.nodes), "edges": edges}
+    assert "vessel" not in shapes["agent"]["nodes"]
+    assert _sha(shapes) == SHAPE_SHA
+
+
+def test_screen_stream_is_unchanged_when_the_switch_is_off(agent_deps):
+    _, events = _turn(agent_deps)
+    assert events[0]["type"] == "RUN_STARTED" and events[-1]["type"] == "RUN_FINISHED"
+    snapshots = [e["snapshot"] for e in events if e["type"] == "STATE_SNAPSHOT"]
+    assert all(
+        sorted(card) == CARD_KEYS for s in snapshots for card in s["cargos"]
+    )  # 화물 카드에 새 칸이 없다
+    assert _sha(_timeless(events)) == STREAM_SHA
+
+
+def test_state_after_a_turn_is_unchanged_when_the_switch_is_off(agent_deps):
+    graph, _ = _turn(agent_deps)
+    values = graph.get_state({"configurable": {"thread_id": "user-a/off"}}).values
+    assert not {"vessels", "verdicts", "vessel_question"} & set(values)  # 새 칸은 스위치가 켜졌을 때만 생긴다
+    seen = {
+        "keys": sorted(values),
+        "cargos": _timeless(values["cargos"]),
+        "view": _timeless(screen_view(values)),
+    }
+    assert _sha(seen) == STATE_SHA
+
+
+def test_other_loops_and_the_trace_scrubber_are_unchanged_when_the_switch_is_off(agent_deps):
+    # [왜] 위의 두 시험은 에이전트 길만 돈다. 계획자 길과 수퍼바이저 길의 한 차례, 그리고 그 차례의 이벤트와
+    #      공책을 트레이스 가림(trace.scrub)에 넣은 결과도 묶는다. 가림 코드는 계획 8b가 고치는 파일이다
+    seen = {}
+    for loop in LOOPS:
+        graph, events = _turn(agent_deps, loop)
+        values = graph.get_state({"configurable": {"thread_id": "user-a/off"}}).values
+        view = {k: v for k, v in values.items() if k != "messages"}  # 메시지 id는 실행마다 다르다
+        seen[loop] = {
+            "events": _timeless(events),
+            "keys": sorted(values),
+            "scrubbed": _timeless(scrub([events, view])),
+        }
+        assert not {"vessels", "verdicts", "vessel_question"} & set(values), loop
+    assert _sha(seen) == LOOPS_SHA
```
```diff
--- a/tests/test_vessel_base_not_wired.py
+++ b/tests/test_vessel_base_not_wired.py
@@ -1,4 +1,9 @@
-"""배 추적 기반(계획 8a)은 그래프에 연결하지 않는다. 측정 커밋(48ca3c5)의 평가 조건이 그대로임을 고정한다.
+"""측정 커밋(48ca3c5)의 파일 묶음이 그대로임을 고정한다 (계획 8a, 계획 8b에서 다섯 파일을 뺌).
+
+본 측정은 끝났다. 이 고정의 목적은 이제 "배 식별 스위치가 꺼진 길이 그대로"를 지키는 것이다.
+계획 8b는 배 식별 단계를 스위치(MARVIA_VESSEL, 기본 off) 뒤에 더하며 다섯 파일을 고친다:
+graph/main.py, graph/state.py, server.py, view.py, trace.py. 그 다섯만 묶음에서 빼고
+"꺼져 있으면 동작이 같다"를 tests/graph/test_vessel_off.py가 본다. 나머지 묶음과 값은 그대로다.
 
 묶음마다 파일 이름과 내용을 이어 sha256 하나로 묶었다. 값은 측정 커밋의 것이다.
 연결하는 계획(도구 목록·지시문·화물 줄을 바꾸는 계획)은 바뀐 묶음의 값을 함께 바꾸고 그 까닭을 적는다.
@@ -15,6 +20,19 @@ from marvia.graph.answer import cargo_lines
 from marvia.graph.tools import make_tools
 
 ROOT = Path(__file__).resolve().parents[1]
+GRAPH_FILES = (
+    "__init__",
+    "agent",
+    "answer",
+    "identify",
+    "live",
+    "rag",
+    "resume",
+    "schemas",
+    "supervisor",
+    "tools",
+    "verify",
+)
 # 묶음 이름 → (파일을 고르는 glob 목록, 측정 커밋의 sha256)
 GROUPS: dict[str, tuple[list[str], str]] = {
     "지시문": (["prompts/*.md"], "56a43bb60bac04e7796db22cf85a2c10f31152eaccba730f36ccb61d584029d3"),
@@ -22,7 +40,11 @@ GROUPS: dict[str, tuple[list[str], str]] = {
         [f"rules/{name}.yaml" for name in ("agent", "rag", "deadlines", "reimport", "identify", "eval")],
         "0725b7cd0f475d61a4ec72860ec42546672074bfa664121308bb78fa0725bb12",
     ),
-    "그래프": (["src/marvia/graph/*.py"], "ff0635075c9c63f217dedee43cb2e882816513920b53533782ab5bcf9e3d09f5"),
+    # [왜] 폴더 전체가 아니라 이름으로 적는다. main.py와 state.py(계획 8b가 고침)와 새 파일 vessel.py는 뺀다
+    "그래프(main·state 제외)": (
+        [f"src/marvia/graph/{name}.py" for name in GRAPH_FILES],
+        "fef3e2c948a43bb90c69e759d41cda1e53425f64876c5f099223a9ad36ed52eb",
+    ),
     "검색": (["src/marvia/rag/*.py"], "fcab4969270619777247aeee8325aa3db33f4116350fd25ace3342214e355eac"),
     "가림과 번호 읽기": (
         ["src/marvia/identify/mask.py", "src/marvia/identify/parse.py"],
@@ -54,18 +76,16 @@ GROUPS: dict[str, tuple[list[str], str]] = {
         ],
         "1baf7cdf1e623fe659d2c596f6caa0d002127970c956722884d97308a28f22c2",
     ),
-    "서버·화면·감시·추적": (
+    # server.py, view.py, trace.py는 계획 8b가 고쳐서 뺐다
+    "감시·지시문 읽기·추적 연결·DB·로그인": (
         [
-            "src/marvia/server.py",
-            "src/marvia/view.py",
             "src/marvia/watch.py",
             "src/marvia/prompts.py",
-            "src/marvia/trace.py",
             "src/marvia/langfuse_trace.py",
             "src/marvia/db.py",
             "src/marvia/auth.py",
         ],
-        "9879f048f94081528de7f5296357aefcc5631a461aff80afee4b9db8e521ab2f",
+        "d6f476b730ef576b312e4e4e45c006c7b3ebaad561a156e9337e4548525b5303",
     ),
     "화물 조회 도구": (
         ["src/marvia/tools/unipass_replay.py", "src/marvia/tools/verdict.py", "src/marvia/tools/rules.py"],
@@ -100,7 +120,8 @@ WIRED_FILES = [
 ]
 # [왜] 판정 평가 문항을 돌리는 코드는 판정 함수를 부르는 것이 일이다. 에이전트 평가 실행기(run.py)와
 #      다른 파일이다
-ALLOWED = {"src/marvia/eval/verdict_set.py"}
+# 배 식별 단계(계획 8b)는 graph/vessel.py 한 파일만 판정·조회 모듈을 부른다
+ALLOWED = {"src/marvia/eval/verdict_set.py", "src/marvia/graph/vessel.py"}
 NEW_MODULES = ["ports", "vessel", "signals", "judge", "vessel_match", "mof", "shipfinder"]
 
 
```

Run: `uv run pytest tests/graph/test_vessel_off.py tests/test_vessel_base_not_wired.py -q`
Expected: `8 passed in 2.03s`. 지금 상태를 묶는 시험이라 처음부터 통과한다.

- [ ] **Step 2: 확인**: 명령 A. Expected: `1209 passed, 8 skipped`, 오류 0, 명령 B 셋 모두 깨끗함.

- [ ] **Step 3: 커밋**

```bash
git add tests/graph/test_vessel_off.py tests/test_vessel_base_not_wired.py
git commit -m "test: 고정 묶음에서 계획 8b가 고치는 다섯 파일만 빼고 '스위치가 꺼져 있으면 동작이 같다'로 대신함"
```

### Task 2: 규칙 파일, 스위치, 배 한 척의 입항 신고 조회 (CB2)

**배울 것:** 사용자에게 보이는 글과 상한은 코드에 적지 않는다. 그리고 코드가 낼 수 있는 이유 이름마다 글이 있는지를 시험이 본다: 이름만 늘리고 글을 빠뜨리면 화면에서 KeyError가 난다.

#### 커밋 2: feat(tools): 배 식별 규칙 파일과 스위치 MARVIA_VESSEL(기본 off), 배 한 척의 입항 신고 조회를 둠

**Files:**
- Modify/Create: `.env.example`, `rules/verdict.yaml`, `rules/vessel.yaml`, `src/marvia/config.py`, `src/marvia/tools/mof.py`
- Test: `tests/tools/test_mof.py`, `tests/tools/test_vessel_rules.py`

**Interfaces:**
- Consumes: `load_rules`, `Settings`, `Port`, `mof.sailing_plans`, `vessel_match.Reason`.
- Produces: `rules/vessel.yaml`(`max_cargos`, `max_candidates`, `max_choices`, `question`, `skip`, `candidate`, `no_call_sign`, `assumption`, `reasons`, `labels`), `Settings.vessel: Literal["off", "on"]`, `mof.plans_for(row: Port, call_sign: str, day: date) -> list[SailingPlan] | ToolError`. 참고 글 `no_sale_date`의 글을 판매 예정일을 받지 않았다는 말로 바로잡는다(`rules/verdict.yaml`).

`rules/vessel.yaml`은 뒤 Task에서 자란다: T4가 상한(요청 수, 쪽 수, 시간)과 후보 글을, T5가 고른 뒤의 요청 수(`pick_calls`)를, T6이 켜진 신호의 글을 더한다. `plans_for`는 해수부가 조회 조건을 다르게 적용해도 남의 배 신고를 돌려주지 않게 호출부호로 한 번 더 거른다.

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/tools/test_mof.py
+++ b/tests/tools/test_mof.py
@@ -428,3 +428,15 @@ def test_among_several_reports_of_one_call_sign_the_one_nearest_the_customs_entr
     # 세관 입항일을 모르면 고르지 않는다: 받은 첫 줄 그대로이고 판정(judge)이 어느 줄도 쓰지 않는다
     first = seen(None)
     assert first.final_arrival == datetime(2026, 9, 22, 8, 0, tzinfo=KST)
+
+
+def test_plans_for_one_ship_use_the_ports_search_window(monkeypatch):
+    # [왜] 같은 이름의 배 후보마다 그 배의 입항 신고를 받아 세관 입항일·적재항과 맞춘다(계획 8b 배 확정)
+    busan = port("KRPUS")
+    assert busan is not None
+    found = mof.plans_for(busan, "qqtst 1", date(2026, 9, 24))
+    assert isinstance(found, list) and [p.call_sign for p in found] == ["QQTST1"]
+    assert mof.plans_for(busan, "QQNONE", date(2026, 9, 24)) == []
+    incheon = port("KRINC")
+    assert incheon is not None
+    assert mof.plans_for(incheon, "QQTST1", date(2026, 9, 24)).code == "port_unknown"  # type: ignore[union-attr]
```
```diff
--- /dev/null
+++ b/tests/tools/test_vessel_rules.py
@@ -0,0 +1,45 @@
+"""배 식별 규칙과 스위치 시험 (계획 8b)."""
+
+from marvia.config import Settings
+from marvia.tools.rules import load_rules
+from marvia.tools.vessel_match import Reason
+
+
+def test_the_switch_is_off_unless_asked(monkeypatch):
+    monkeypatch.delenv("MARVIA_VESSEL", raising=False)
+    assert Settings(_env_file=None).vessel == "off"  # type: ignore[call-arg]
+    monkeypatch.setenv("MARVIA_VESSEL", "on")
+    assert Settings(_env_file=None).vessel == "on"  # type: ignore[call-arg]
+
+
+def test_limits_and_texts_live_in_the_rules_file():
+    rules = load_rules("vessel")
+    assert rules["max_cargos"] == 3 and rules["max_candidates"] == 5 and rules["max_choices"] == 2
+    # 선택 카드는 권고(배 없이 진행) 하나와 후보 둘까지: 설계 6.3의 선택지 2~3개
+    assert 2 <= 1 + rules["max_choices"] <= 3
+    assert "{token}" in rules["question"] and "{token}" in rules["assumption"]
+    for text in (rules["question"], rules["assumption"], *rules["skip"].values()):
+        assert (
+            "{name}" not in text and "{call_sign}" not in text
+        )  # 가정 글과 질문 머리에는 배 이름을 넣지 않는다
+
+
+def test_every_reason_the_code_can_give_has_a_fixed_text():
+    reasons = load_rules("vessel")["reasons"]
+    # 배 확정 함수(8a)의 이유 전부와, 이 계획의 단계가 더하는 이유
+    for name in Reason.__args__:  # type: ignore[attr-defined]
+        assert name in reasons, name
+    for name in (
+        "no_clue",
+        "lookup_failed",
+        "over_cap",
+        "another_question",
+        "user_choice",
+        "user_skipped",
+        "no_answer",
+    ):
+        assert name in reasons, name
+    labels = load_rules("vessel")["labels"]
+    assert labels["no_grade"] == "등급 없음" and set(labels["eta_sources"]) == set(
+        load_rules("verdict")["eta_priority"]
+    )
```

Run: `uv run pytest tests/tools/test_mof.py tests/tools/test_vessel_rules.py -q`
Expected: `4 failed, 30 passed in 0.89s`. 실패하는 것: `test_plans_for_one_ship_use_the_ports_search_window`, `test_the_switch_is_off_unless_asked`, `test_limits_and_texts_live_in_the_rules_file`, `test_every_reason_the_code_can_give_has_a_fixed_text`.

- [ ] **Step 2: 코드**

```diff
--- a/.env.example
+++ b/.env.example
@@ -38,6 +38,9 @@ MARVIA_MOF_RELAY_TOKEN=
 MARVIA_SHIPFINDER_MODE=
 MARVIA_SHIPFINDER_KEY=
 
+# 배 식별 단계와 화물 카드의 판정 칸: off(기본) 또는 on. off면 그래프와 화면이 그대로다 (계획 8b)
+MARVIA_VESSEL=
+
 # 에이전트 RAG의 검색 길: mcp(기본, 같은 MCP 서버를 메모리 통로로) 또는 direct
 MARVIA_RAG_VIA=
 # 규정 검색 MCP HTTP 서버(scripts/serve_mcp.py)의 Bearer 토큰. 비면 서버가 뜨지 않는다
```
```diff
--- a/rules/verdict.yaml
+++ b/rules/verdict.yaml
@@ -119,7 +119,7 @@ notes:
 
 # 확신을 낮추지 않는 참고 사실의 이름과 글 (11-13 덧붙임)
 info:
-  no_sale_date: 판매 예정일을 받지 않아 배와 통관 상태만으로 본 등급이에요
+  no_sale_date: 판매 예정일을 받지 않아 여유 일수는 세지 않았어요. 배와 통관 상태만으로 본 등급이에요
   arrived: 이 항차의 실제 입항을 확인해 배 위치와 일정은 보지 않았어요. 통관 단계와 통관 멈춤만으로 본 등급이에요
   landed: 배에서 내린 화물이라 배 위치는 보지 않았어요. 통관 단계만으로 본 등급이에요
   no_first_eta: 처음 알던 도착 예정이 없어 지연은 보지 못했어요 # 이때 일정 칸은 비운다. 판매 예정일을 넘긴 "초과"만 낸다
```
```diff
--- /dev/null
+++ b/rules/vessel.yaml
@@ -0,0 +1,50 @@
+# 배 식별 단계의 값과 글. 코드(src/marvia/graph/vessel.py, src/marvia/view.py)가 읽는다 (계획 8b, 설계 4.1 ②, 6.3).
+# 스위치 MARVIA_VESSEL=on일 때만 이 단계가 돈다. 기본은 off다.
+max_cargos: 3 # 한 차례에 배를 찾는 화물 수 상한. 넘는 화물은 배를 찾지 않고 그렇다고 적는다
+max_candidates: 5 # 배 후보를 이 수까지만 맞춰 본다. 후보마다 해수부 입항 신고를 한 번 조회한다
+max_choices: 2 # 선택 카드에 보이는 배 후보 수. 권고 선택지(배 없이 진행)와 합쳐 셋까지다 (설계 6.3: 2~3개)
+
+# 배를 가리지 못했을 때의 선택 카드. {token}은 가린 화물 이름표이고 화면으로 갈 때 실제 번호로 되돌린다.
+# [주의] 질문 머리와 가정 글에는 배 이름을 넣지 않는다. 가정 글은 답과 대화 기록에 남아 모델이 다시 읽는다
+question: "{token} 화물을 실은 배를 가리지 못했어요. 어느 배인가요?"
+skip:
+  label: 모르겠어요
+  description: 배 정보 없이 진행해요. 통관 단계는 그대로 보여 드려요
+candidate: "호출부호 {call_sign} · 배 번호 {mmsi}" # 후보 선택지의 설명. 이름표(label)는 배 이름이다
+no_call_sign: 없음 # 후보에 호출부호가 없을 때 위 글에 넣는 말
+assumption: "{token} 화물의 배를 확인하지 못해 배 정보 없이 진행했어요" # 답 없이 넘어갔을 때 가정으로 남기는 글
+
+# 배 확인 결과의 이유 이름 → 화물 카드에 보이는 글. 앞의 열둘은 tools/vessel_match.py의 이유다
+reasons:
+  no_candidate: 배 후보를 찾지 못했어요
+  mrn_call_sign: 맞춰 본 칸은 호출부호예요. 입항 신고의 호출부호와 같아요
+  papers_match: 맞춰 본 칸은 입항일과 적재항이에요. 세관 기록과 해수부 입항 신고가 맞아요
+  mrn_call_sign_differs: 후보의 호출부호가 입항 신고와 달라요
+  flag_differs: 후보의 국적이 세관 기록과 달라요
+  same_call_sign_many_mmsi: 같은 호출부호의 배가 여럿이에요
+  candidate_without_call_sign: 호출부호가 없는 후보가 있어 가리지 못했어요
+  no_papers: 맞춰 볼 세관 입항일이나 적재항이 없어요
+  schedule_lookup_failed: 후보의 입항 신고를 받지 못했어요
+  papers_match_none: 세관 입항일·적재항과 맞는 후보가 없어요
+  papers_match_many: 세관 입항일·적재항과 맞는 후보가 여럿이에요
+  mrn_lookup_failed: 입항 신고 번호(MRN)로 해수부 입항 신고를 받지 못해 서류로 확정하지 않았어요
+  mrn_report_missing: 입항 신고 번호(MRN)로 찾은 입항 신고가 없어 서류로 확정하지 않았어요
+  no_clue: 배를 찾을 단서(입항 신고 번호, 배 이름)가 없어요
+  lookup_failed: 배 위치 서비스에서 후보를 받지 못했어요
+  over_cap: 한 번에 배를 찾는 화물 수를 넘어 이 화물은 찾지 않았어요
+  another_question: 다른 화물의 배를 먼저 여쭤봤어요. 이 화물은 배 없이 진행했어요
+  user_choice: 고르신 배로 봤어요
+  landed: 배에서 내린 화물이라 배 위치는 보지 않았어요
+  user_skipped: 배를 모른다고 하셔서 배 없이 진행했어요
+  no_answer: 답이 없어 배 없이 진행했어요
+
+# 화물 카드의 판정 칸에 쓰는 말
+labels:
+  no_grade: 등급 없음
+  no_schedule: 일정 모름
+  eta_sources:
+    mof_actual: 해수부 입항 실적
+    mof_final: 해수부 최종 입항 신고
+    mof_planned: 해수부 입항 예정
+    ais_eta: 배 신호
+    forwarder_eta: 포워더가 알려 준 날
```
```diff
--- a/src/marvia/config.py
+++ b/src/marvia/config.py
@@ -75,6 +75,9 @@ class Settings(BaseSettings):
     shipfinder_mode: Literal["replay", "live"] = "replay"  # MARVIA_SHIPFINDER_MODE
     shipfinder_key: SecretStr = SecretStr("")  # MARVIA_SHIPFINDER_KEY
 
+    # 배 식별 단계와 화물 카드의 판정 칸 (계획 8b). [왜] 기본이 off라 켜기 전에는 그래프와 화면이 그대로다
+    vessel: Literal["off", "on"] = "off"  # MARVIA_VESSEL
+
     # 규정 검색 MCP (계획 3b Task 8). [왜] mcp면 에이전트 RAG가 같은 MCP 서버를 메모리 통로로 부른다(설계 9절)
     rag_via: Literal["direct", "mcp"] = "mcp"  # MARVIA_RAG_VIA
     mcp_token: SecretStr = SecretStr("")  # MARVIA_MCP_TOKEN. 비면 scripts/serve_mcp.py가 뜨지 않는다
```
```diff
--- a/src/marvia/tools/mof.py
+++ b/src/marvia/tools/mof.py
@@ -392,3 +392,30 @@ def plans_near(row: Port, day: date) -> list[SailingPlan] | ToolError:
             base_url=base_url,
             max_pages=CFG["max_pages"],
         )
+
+
+def plans_for(row: Port, call_sign: str, day: date) -> list[SailingPlan] | ToolError:
+    """배 한 척의 세관 입항(예정)일 앞뒤 입항 신고. 같은 이름의 배 후보를 서류로 가를 때 쓴다."""
+    if not row.mof_office or row.mrn_search_days is None:
+        return _error("port_unknown")
+    session = _session()
+    if isinstance(session, ToolError):
+        return session
+    client, base_url, key = session
+    span = timedelta(days=row.mrn_search_days)
+    with client:
+        found = sailing_plans(
+            row.mof_office,
+            day - span,
+            day + span,
+            key=key,
+            client=client,
+            base_url=base_url,
+            call_sign=call_sign,
+        )
+    # [왜] 해수부가 조회 조건을 다르게 적용해도 남의 배 신고를 그 배의 것으로 쓰지 않는다
+    return (
+        found
+        if isinstance(found, ToolError)
+        else [p for p in found if _sign(p.call_sign) == _sign(call_sign)]
+    )
```

- [ ] **Step 3: 확인**: 명령 A. Expected: `1213 passed, 8 skipped`, 오류 0, 명령 B 셋 모두 깨끗함.

- [ ] **Step 4: 커밋**

```bash
git add .env.example rules/verdict.yaml rules/vessel.yaml src/marvia/config.py src/marvia/tools/mof.py tests/tools/test_mof.py tests/tools/test_vessel_rules.py
git commit -m "feat(tools): 배 식별 규칙 파일과 스위치 MARVIA_VESSEL(기본 off), 배 한 척의 입항 신고 조회를 둠"
```

### Task 3: 배로 이어지는 재생 화물 (결정 B17)

**배울 것:** 평가가 쓰는 fixture는 고치지 않고 새 fixture를 옆에 둔다. 고정 시험이 폴더 전체를 묶고 있었다면 묶음을 "측정한 파일의 이름"으로 좁힌다. 해시는 그대로여야 한다.

#### 커밋 3: test(tools): 배로 이어지는 재생 화물 일곱(TESTVSL0001~7)과 배 검색 재생 셋, 입항 신고 재생 둘. 측정한 다섯 화물의 묶음은 그대로 둠

**Files:**
- Modify/Create: `fixtures/mof/VsslEtrynd5/020/QQTST4.xml`, `fixtures/mof/VsslEtrynd5/020/_ALL.xml`, `fixtures/shipfinder/VesselSearch/QQTWN.json`, `fixtures/shipfinder/VesselSearch/TEST_CARGO_C.json`, `fixtures/shipfinder/VesselSearch/TEST_CARGO_E.json`, `fixtures/unipass/TESTVSL0001.json`, `fixtures/unipass/TESTVSL0002.json`, `fixtures/unipass/TESTVSL0003.json`, `fixtures/unipass/TESTVSL0004.json`, `fixtures/unipass/TESTVSL0005.json`, `fixtures/unipass/TESTVSL0006.json`, `fixtures/unipass/TESTVSL0007.json`
- Test: `tests/test_vessel_base_not_wired.py`, `tests/tools/test_vessel_rules.py`

**Interfaces:**
- Consumes: `unipass_replay.lookup_cargo`, `shipfinder.vessel_candidates`, `shipfinder.vessel_position`.
- Produces: 재생 화물 `TESTVSL0001`~`0007`(결정 B17), 배 검색 재생 `TEST_CARGO_C.json`, `TEST_CARGO_E.json`, `QQTWN.json`, 입항 신고 재생 `QQTST4.xml`, `_ALL.xml`(서명 없는 MRN 신고 `26TEST0004I`와 호출부호가 같은 두 배). 고정 시험의 `MEASURED_CARGOS`.

코드는 없다. 값은 모두 만든 것이다. 입항일은 재생 배의 입항 예정일(2026-09-24)과 같다. `TESTVSL0002`는 MRN이 입항 신고에 없어 배 이름 검색으로 간다. `TESTVSL0004`는 서류는 맞지만 위치 재생 파일이 없다. `TESTVSL0006`은 반입신고 단계라 내린 화물이다. `TESTVSL0007`은 신고에 호출부호가 없어 서류로 가르는 길이고 후보 둘의 호출부호가 같다(`QQTWN`).

- [ ] **Step 1: 가공 fixture** (시험과 코드는 다음 커밋이다. 이 커밋만으로는 시험 수가 그대로다)

```diff
--- a/tests/test_vessel_base_not_wired.py
+++ b/tests/test_vessel_base_not_wired.py
@@ -20,6 +20,7 @@ from marvia.graph.answer import cargo_lines
 from marvia.graph.tools import make_tools
 
 ROOT = Path(__file__).resolve().parents[1]
+MEASURED_CARGOS = ("DEMO0001", "DEMO0002", "DEMO0003", "MOCK12345678", "TEST87654321")
 GRAPH_FILES = (
     "__init__",
     "agent",
@@ -60,7 +61,8 @@ GROUPS: dict[str, tuple[list[str], str]] = {
     ),
     "평가셋 v3": (["eval/set_v3.yaml"], "e222b902acec89b9ba121e3c4b3361827ec37161e0b9c98b6f63ee63b0a8b705"),
     "재생 화물": (
-        ["fixtures/unipass/*.json"],
+        # [왜] 측정에 쓴 다섯 화물만 묶는다. 계획 8b가 더한 화물(TESTVSL000x)은 평가 문항이 쓰지 않는다
+        [f"fixtures/unipass/{name}.json" for name in MEASURED_CARGOS],
         "6e67943f9416bd31e256b5c04c553fa746c55e5844b962967df08b1005f8385b",
     ),
     # 아래 다섯 묶음은 11-13에 더했다. 값은 측정 커밋과 같음을 git diff로 확인한 뒤 적었다.
```
```diff
--- a/tests/tools/test_vessel_rules.py
+++ b/tests/tools/test_vessel_rules.py
@@ -1,6 +1,8 @@
 """배 식별 규칙과 스위치 시험 (계획 8b)."""
 
 from marvia.config import Settings
+from marvia.identify.models import CargoFacts, ToolError
+from marvia.tools import shipfinder
 from marvia.tools.rules import load_rules
 from marvia.tools.vessel_match import Reason
 
@@ -43,3 +45,46 @@ def test_every_reason_the_code_can_give_has_a_fixed_text():
     assert labels["no_grade"] == "등급 없음" and set(labels["eta_sources"]) == set(
         load_rules("verdict")["eta_priority"]
     )
+
+
+def test_vessel_demo_cargos_are_made_up_and_cover_the_cases():
+    # [왜] 배 식별 화면을 키 없이 보이려면 배로 이어지는 재생 화물이 있어야 한다. 기존 다섯 화물은 그대로 둔다
+    from marvia.tools import mof
+    from marvia.tools.ports import port
+    from marvia.tools.unipass_replay import lookup_cargo
+
+    seen = {}
+    for n in range(1, 8):
+        facts = lookup_cargo(f"TESTVSL000{n}")
+        assert isinstance(facts, CargoFacts), n
+        assert facts.port_code and facts.entry_date and (facts.vessel_name or "").startswith("TEST ")
+        assert facts.mrn is None or facts.mrn.startswith("26TEST")
+        seen[n] = facts
+    busan = port("KRPUS")
+    assert busan is not None and seen[1].entry_date is not None
+    listed = mof.plans_near(busan, seen[1].entry_date)
+    assert isinstance(listed, list)
+
+    def report(n: int):
+        mrn = seen[n].mrn
+        return mof.plan_by_mrn(listed, mrn) if mrn else None
+
+    assert (
+        seen[1].mrn == "26TEST0001I" and (report(1) or object()).call_sign == "QQTST1"
+    )  # MRN으로 호출부호에 닿는다
+    assert seen[2].mrn is not None and report(2) is None  # MRN으로 닿지 못하고 같은 이름의 후보가 여럿
+    assert seen[3].port_code == "KRINC"  # 확인 전 항만, 후보 없음
+    assert (
+        report(4) is not None and not report(4).call_sign
+    )  # MRN의 신고에 호출부호가 없다: 서류로 확정하는 길
+    assert seen[5].mrn is None  # 한 척인데 MRN이 없다: 서류가 맞아도 되묻는다
+    assert seen[6].stage == "반입신고" and seen[6].mrn == seen[1].mrn  # 배에서 내린 화물
+    assert (report(7) or object()).call_sign == "QQTWN"  # 호출부호가 같은 배가 둘이다
+    hits = shipfinder.vessel_candidates(seen[4].vessel_name or "")
+    assert isinstance(hits, list) and [h.mmsi for h in hits] == [999000004]  # 한 척, 서류는 맞고 위치는 없다
+    assert isinstance(shipfinder.vessel_position(999000004), ToolError)
+    five = shipfinder.vessel_candidates(seen[5].vessel_name or "")
+    assert isinstance(five, list) and [h.mmsi for h in five] == [999000005]
+    twins = shipfinder.vessel_candidates("QQTWN")
+    assert isinstance(twins, list) and [h.mmsi for h in twins] == [999000007, 999000008]
+    assert shipfinder.vessel_candidates(seen[3].vessel_name or "") == []
```
```diff
--- /dev/null
+++ b/fixtures/mof/VsslEtrynd5/020/QQTST4.xml
@@ -0,0 +1,10 @@
+<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
+<!-- 가공값. QQTST4: 세관 입항일(09-24)과 적재항(QINGDAO)이 맞는 입항 신고 한 건. 배 위치 재생 파일은 없다 -->
+<response><header><resultCode>00</resultCode><resultMsg>NORMAL_SERVICE</resultMsg></header><body><items>
+<item><prtAgCd>020</prtAgCd><clsgn>QQTST4</clsgn><vsslNm>TEST CARGO C</vsslNm>
+<vsslNltyCd>PA</vsslNltyCd><vsslKndNm>풀컨테이너선</vsslKndNm>
+<etryptPurpsNm>양하</etryptPurpsNm><prvsDpmprtPrtNm>QINGDAO</prvsDpmprtPrtNm><nxlnptPrtNm>TEST NEXT</nxlnptPrtNm>
+<details>
+<detail><reqstSeNm>변경</reqstSeNm><etryndNm>입항</etryndNm><etryptDt>2026-09-24T12:00:00+09:00</etryptDt><laidupFcltyNm>TEST부두 3선석</laidupFcltyNm><mrNum>26TEST0004I</mrNum></detail>
+</details></item>
+</items><numOfRows>50</numOfRows><pageNo>1</pageNo><totalCount>1</totalCount></body></response>
```
```diff
--- a/fixtures/mof/VsslEtrynd5/020/_ALL.xml
+++ b/fixtures/mof/VsslEtrynd5/020/_ALL.xml
@@ -14,4 +14,14 @@
 <details>
 <detail><reqstSeNm>최종</reqstSeNm><etryndNm>입항</etryndNm><etryptDt>2026-09-22T10:00:00+09:00</etryptDt><laidupFcltyNm>TEST부두 2선석</laidupFcltyNm><mrNum>26TEST0002I</mrNum></detail>
 </details></item>
-</items><numOfRows>50</numOfRows><pageNo>1</pageNo><totalCount>2</totalCount></body></response>
+<item><prtAgCd>020</prtAgCd><clsgn></clsgn><vsslNm>TEST CARGO C</vsslNm><vsslNltyCd>PA</vsslNltyCd><vsslKndNm>풀컨테이너선</vsslKndNm>
+<prvsDpmprtPrtNm>QINGDAO</prvsDpmprtPrtNm>
+<details>
+<detail><reqstSeNm>변경</reqstSeNm><etryndNm>입항</etryndNm><etryptDt>2026-09-24T12:00:00+09:00</etryptDt><laidupFcltyNm>TEST부두 3선석</laidupFcltyNm><mrNum>26TEST0004I</mrNum></detail>
+</details></item>
+<item><prtAgCd>020</prtAgCd><clsgn>QQTWN</clsgn><vsslNm>TEST TWIN</vsslNm><vsslNltyCd>PA</vsslNltyCd><vsslKndNm>풀컨테이너선</vsslKndNm>
+<prvsDpmprtPrtNm>QINGDAO</prvsDpmprtPrtNm>
+<details>
+<detail><reqstSeNm>변경</reqstSeNm><etryndNm>입항</etryndNm><etryptDt>2026-09-24T12:00:00+09:00</etryptDt><laidupFcltyNm>TEST부두 4선석</laidupFcltyNm><mrNum>26TEST0007I</mrNum></detail>
+</details></item>
+</items><numOfRows>50</numOfRows><pageNo>1</pageNo><totalCount>4</totalCount></body></response>
```
```diff
--- /dev/null
+++ b/fixtures/shipfinder/VesselSearch/QQTWN.json
@@ -0,0 +1,23 @@
+{
+ "status": 0,
+ "msg": "",
+ "total": 2,
+ "data": [
+  {
+   "match_type": 1,
+   "mmsi": 999000007,
+   "imo": 0,
+   "call_sign": "QQTWN",
+   "ship_name": "TEST TWIN",
+   "last_time": 1790044200
+  },
+  {
+   "match_type": 1,
+   "mmsi": 999000008,
+   "imo": 0,
+   "call_sign": "QQTWN",
+   "ship_name": "TEST TWIN",
+   "last_time": 1790044200
+  }
+ ]
+}
```
```diff
--- /dev/null
+++ b/fixtures/shipfinder/VesselSearch/TEST_CARGO_C.json
@@ -0,0 +1,15 @@
+{
+ "status": 0,
+ "msg": "",
+ "total": 1,
+ "data": [
+  {
+   "match_type": 1,
+   "mmsi": 999000004,
+   "imo": 0,
+   "call_sign": "QQTST4",
+   "ship_name": "TEST CARGO C",
+   "last_time": 1790044200
+  }
+ ]
+}
```
```diff
--- /dev/null
+++ b/fixtures/shipfinder/VesselSearch/TEST_CARGO_E.json
@@ -0,0 +1,15 @@
+{
+ "status": 0,
+ "msg": "",
+ "total": 1,
+ "data": [
+  {
+   "match_type": 1,
+   "mmsi": 999000005,
+   "imo": 0,
+   "call_sign": "QQTST5",
+   "ship_name": "TEST CARGO E",
+   "last_time": 1790044200
+  }
+ ]
+}
```
```diff
--- /dev/null
+++ b/fixtures/unipass/TESTVSL0001.json
@@ -0,0 +1 @@
+{"stage": "입항적재화물목록 심사완료", "stage_at": "2026-09-22T09:00:00+09:00", "port": "부산", "port_code": "KRPUS", "entry_date": "2026-09-24", "loading_port": "QINGDAO", "vessel_name": "TEST CARGO A", "mrn": "26TEST0001I"}
```
```diff
--- /dev/null
+++ b/fixtures/unipass/TESTVSL0002.json
@@ -0,0 +1 @@
+{"stage": "입항적재화물목록 심사완료", "stage_at": "2026-09-22T09:00:00+09:00", "port": "부산", "port_code": "KRPUS", "entry_date": "2026-09-24", "loading_port": "QINGDAO", "vessel_name": "TEST CARGO A", "mrn": "26TEST0009I"}
```
```diff
--- /dev/null
+++ b/fixtures/unipass/TESTVSL0003.json
@@ -0,0 +1 @@
+{"stage": "입항적재화물목록 심사완료", "stage_at": "2026-09-22T09:00:00+09:00", "port": "인천", "port_code": "KRINC", "entry_date": "2026-09-24", "loading_port": "QINGDAO", "vessel_name": "TEST NO SHIP"}
```
```diff
--- /dev/null
+++ b/fixtures/unipass/TESTVSL0004.json
@@ -0,0 +1 @@
+{"stage": "입항적재화물목록 심사완료", "stage_at": "2026-09-22T09:00:00+09:00", "port": "부산", "port_code": "KRPUS", "entry_date": "2026-09-24", "loading_port": "QINGDAO", "vessel_name": "TEST CARGO C", "mrn": "26TEST0004I"}
```
```diff
--- /dev/null
+++ b/fixtures/unipass/TESTVSL0005.json
@@ -0,0 +1 @@
+{"stage": "입항적재화물목록 심사완료", "stage_at": "2026-09-22T09:00:00+09:00", "port": "부산", "port_code": "KRPUS", "entry_date": "2026-09-24", "loading_port": "QINGDAO", "vessel_name": "TEST CARGO E"}
```
```diff
--- /dev/null
+++ b/fixtures/unipass/TESTVSL0006.json
@@ -0,0 +1 @@
+{"stage": "반입신고", "stage_at": "2026-09-26T09:00:00+09:00", "port": "부산", "port_code": "KRPUS", "entry_date": "2026-09-24", "loading_port": "QINGDAO", "vessel_name": "TEST CARGO A", "mrn": "26TEST0001I"}
```
```diff
--- /dev/null
+++ b/fixtures/unipass/TESTVSL0007.json
@@ -0,0 +1 @@
+{"stage": "입항적재화물목록 심사완료", "stage_at": "2026-09-22T09:00:00+09:00", "port": "부산", "port_code": "KRPUS", "entry_date": "2026-09-24", "loading_port": "QINGDAO", "vessel_name": "TEST TWIN", "mrn": "26TEST0007I"}
```

- [ ] **Step 2: 확인**: 명령 A. Expected: `1214 passed, 8 skipped`, 오류 0, 명령 B 셋 모두 깨끗함.

- [ ] **Step 3: 커밋**

```bash
git add fixtures/mof/VsslEtrynd5/020/QQTST4.xml fixtures/mof/VsslEtrynd5/020/_ALL.xml fixtures/shipfinder/VesselSearch/QQTWN.json fixtures/shipfinder/VesselSearch/TEST_CARGO_C.json fixtures/shipfinder/VesselSearch/TEST_CARGO_E.json fixtures/unipass/TESTVSL0001.json fixtures/unipass/TESTVSL0002.json fixtures/unipass/TESTVSL0003.json fixtures/unipass/TESTVSL0004.json fixtures/unipass/TESTVSL0005.json fixtures/unipass/TESTVSL0006.json fixtures/unipass/TESTVSL0007.json tests/test_vessel_base_not_wired.py tests/tools/test_vessel_rules.py
git commit -m "test(tools): 배로 이어지는 재생 화물 일곱(TESTVSL0001~7)과 배 검색 재생 셋, 입항 신고 재생 둘. 측정한 다섯 화물의 묶음은 그대로 둠"
```

### Task 4: 화물 한 건의 배를 찾는 함수와 요청 수 상한 (CB4, CB5, CB10, 결정 B4, B10)

**배울 것:** 조회를 잇는 코드에서 틀리기 쉬운 곳은 "결과를 줄이는 자리"와 "세지 않는 호출"이다. 후보가 많다고 앞의 몇 척만 남기면 확정 함수는 그 몇 척이 전부인 줄 안다. 줄이는 것은 바깥 호출 수이지 후보 목록이 아니다. 그리고 고르기 전에 하는 일과 고른 뒤에 하는 일을 섞지 않는다: 고르지도 않은 배의 조회를 하면 요청 수가 늘고 카드 글이 거짓이 된다.

#### 커밋 4: feat(graph): 화물 한 건의 배를 찾는 함수. MRN 호출부호나 MRN 조회가 성공한 서류로 맞춰 본 칸이 있을 때만 확정하고 요청 수 상한을 지킴

**Files:**
- Modify/Create: `rules/vessel.yaml`, `src/marvia/graph/vessel.py`, `src/marvia/tools/mof.py`
- Test: `tests/graph/test_vessel_step.py`, `tests/tools/test_mof.py`

**Interfaces:**
- Consumes: `port`, `mof.plans_near(row, day, max_pages=...)`, `plan_by_mrn`, `plans_for`, `shipfinder.vessel_candidates`, `match_vessel`, `watches_ship`.
- Produces: `marvia.graph.vessel.find_vessel(facts: CargoFacts, *, near: dict | None = None) -> dict`. 돌려주는 dict: `status`(`confirmed`, `ask`, `none`, `unknown`), `reason`(`rules/vessel.yaml reasons`의 이름), 확정이면 `mmsi`(글), `call_sign`, `name`, `basis`, `cap`, 되묻기면 `candidates`(후보마다 `check`, `max_candidates`까지)와 `lookup`(MRN 조회 결과), `mrn_call_sign`, `hits`(검색 결과 전체, 배 번호는 글), 조회 실패면 `detail`(클라이언트의 정한 오류 글). `rules/vessel.yaml`의 `max_find_calls`(14), `max_mrn_pages`(8), `verdict_calls`(3), `max_calls`(18). `mof.plans_near`의 `max_pages` 인자.

배 번호(`mmsi`)는 글이다(결정 B15). 시험 파일 이름은 `test_vessel_step.py`다(`tests/tools/test_vessel.py`와 이름이 겹치면 pytest가 모으지 못한다). 요청 수는 최악의 경우를 센다: MRN 입항 신고 목록은 쪽 수 상한만큼, 그 목록은 같은 항만·같은 날이면 한 차례에 한 번만 받는다. 후보 수가 상한을 넘으면 후보마다의 입항 신고를 받지 않는다. 시간 상한과 화물 수 상한은 T5의 노드가 건다. 이 커밋에 "찾는 쪽은 `check_candidate`를 부르지 않는다"는 시험이 있고(CB4) T5의 `check_pick`이 그 한 곳이다.

- [ ] **Step 1: 실패하는 시험**

```diff
--- /dev/null
+++ b/tests/graph/test_vessel_step.py
@@ -0,0 +1,166 @@
+"""배 식별 단계 시험 (계획 8b). 바깥 조회는 재생 데이터이고 키 없이 돈다."""
+
+import pytest
+
+from marvia.graph import vessel
+from marvia.identify.models import CargoFacts, ToolError
+from marvia.tools import mof, shipfinder
+from marvia.tools.rules import load_rules
+from marvia.tools.shipfinder import VesselHit
+from marvia.tools.unipass_replay import lookup_cargo
+
+
+def facts(number: str) -> CargoFacts:
+    found = lookup_cargo(number)
+    assert isinstance(found, CargoFacts)
+    return found
+
+
+@pytest.fixture(autouse=True)
+def _fresh():
+    shipfinder.reset_state()
+
+
+def test_mrn_leads_to_one_ship_and_the_call_sign_is_what_was_checked(monkeypatch):
+    monkeypatch.setattr(
+        mof, "plans_for", lambda *a, **k: pytest.fail("호출부호를 맞췄는데 입항 신고를 받았다")
+    )
+    found = vessel.find_vessel(facts("TESTVSL0001"))
+    assert found == {
+        "status": "confirmed",
+        "reason": "mrn_call_sign",
+        "basis": ["call_sign"],
+        "cap": None,
+        "mmsi": "999000001",
+        "call_sign": "QQTST1",
+        "name": "TEST CARGO A",
+    }
+
+
+def test_same_name_ships_are_not_picked_and_each_says_why_papers_cannot_settle_it():
+    # TESTVSL0002: MRN의 입항 신고가 없어(서류로 확정하는 길이 닫힘) 같은 이름의 셋 가운데 고르지 못한다
+    found = vessel.find_vessel(facts("TESTVSL0002"))
+    assert found["status"] == "ask" and found["reason"] == "mrn_report_missing"
+    assert [c["mmsi"] for c in found["candidates"]] == ["999000001", "999000002", "999000003"]
+    assert "mmsi" not in found  # 고르지 않았다
+    # 후보마다 서류로 맞춰 본 이유가 따라온다(선택 카드가 보인다). 상한은 고른 뒤 검사가 건다
+    assert {c["check"] for c in found["candidates"]} == {"mrn_report_missing"}
+    assert all("cap" not in c for c in found["candidates"])
+    assert (found["lookup"], found["mrn_call_sign"]) == ("not_found", None)  # 고른 뒤 검사가 쓸 것
+
+
+def test_papers_decide_between_two_ships_only_when_the_mrn_report_has_no_call_sign(monkeypatch):
+    # TESTVSL0004: MRN의 입항 신고가 있고 호출부호가 없다. 서류(입항일 09-24, 적재항 QINGDAO)가 한 척에만
+    #      맞는다
+    hits = [VesselHit(mmsi=999000004, call_sign="QQTST4"), VesselHit(mmsi=999000005, call_sign="QQTST9")]
+    monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: hits)
+    found = vessel.find_vessel(facts("TESTVSL0004"))
+    assert (found["status"], found["reason"], found["mmsi"]) == ("confirmed", "papers_match", "999000004")
+    assert (found["basis"], found["cap"]) == (["entry_date", "loading_port"], "partial")
+
+
+def test_one_ship_found_by_name_is_checked_against_its_own_sailing_report():
+    # TESTVSL0004: 한 척이고 그 배의 입항 신고가 입항일과 적재항이 맞는다. 맞춰 본 칸은 둘이고 호출부호는
+    #      아니다
+    found = vessel.find_vessel(facts("TESTVSL0004"))
+    assert (found["status"], found["reason"], found["basis"], found["cap"]) == (
+        "confirmed",
+        "papers_match",
+        ["entry_date", "loading_port"],
+        "partial",
+    )
+    # TESTVSL0005: 한 척인데 MRN이 없다. 이름이 닮았을 뿐이니 서류가 맞아도 확정하지 않고 되묻는다
+    asked = vessel.find_vessel(facts("TESTVSL0005"))
+    assert (asked["status"], asked["reason"]) == ("ask", "mrn_report_missing")
+    assert [c["name"] for c in asked["candidates"]] == ["TEST CARGO E"]
+
+
+def test_ships_sharing_a_call_sign_are_asked_and_a_pick_among_them_is_capped():
+    found = vessel.find_vessel(facts("TESTVSL0007"))
+    assert (found["status"], found["reason"]) == ("ask", "same_call_sign_many_mmsi")
+    assert [(c["mmsi"], c["check"]) for c in found["candidates"]] == [
+        ("999000007", "mrn_call_sign"),  # 그 후보 하나만 있다면 호출부호가 맞는다
+        ("999000008", "mrn_call_sign"),
+    ]
+    assert (found["lookup"], found["mrn_call_sign"]) == ("found_signed", "QQTWN")
+
+
+def test_a_failed_mrn_lookup_is_a_card_not_a_papers_confirmation(monkeypatch):
+    broken = ToolError(code="too_many", message="입항 신고가 너무 많아요", retryable=False)
+    monkeypatch.setattr(mof, "plans_near", lambda *a, **k: broken)
+    found = vessel.find_vessel(facts("TESTVSL0004"))  # 서류는 맞지만 MRN으로 입항 신고를 받지 못했다
+    assert (found["status"], found["reason"]) == ("ask", "mrn_lookup_failed")
+    assert [c["check"] for c in found["candidates"]] == ["mrn_lookup_failed"]
+
+
+def test_no_candidate_no_clue_and_failed_lookup_never_name_a_ship(monkeypatch):
+    assert vessel.find_vessel(facts("TESTVSL0003")) == {"status": "none", "reason": "no_candidate"}
+    from datetime import UTC, datetime
+
+    bare = CargoFacts(number="TESTVSL0009", stage="입항", fetched_at=datetime.now(UTC))
+    monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: pytest.fail("단서 없이 찾았다"))
+    assert vessel.find_vessel(bare) == {"status": "unknown", "reason": "no_clue"}
+    quota = ToolError(code="quota_exhausted", message="오늘 조회할 수 있는 횟수를 다 썼어요", retryable=False)
+    monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: quota)
+    # 클라이언트의 정한 오류 글을 그대로 싣는다: 한도 소진("내일")과 일시 실패("잠시 뒤")가 갈린다
+    assert vessel.find_vessel(facts("TESTVSL0004")) == {
+        "status": "unknown",
+        "reason": "lookup_failed",
+        "detail": "오늘 조회할 수 있는 횟수를 다 썼어요",
+    }
+
+
+def test_cargo_off_the_ship_is_not_looked_up_at_all(monkeypatch):
+    for name in ("plans_near", "plans_for"):
+        monkeypatch.setattr(mof, name, lambda *a, **k: pytest.fail("내린 화물인데 해수부를 불렀다"))
+    monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: pytest.fail("내린 화물인데 찾았다"))
+    assert vessel.find_vessel(facts("TESTVSL0006")) == {"status": "unknown", "reason": "landed"}
+
+
+def test_too_many_candidates_are_asked_without_one_schedule_call_each(monkeypatch):
+    many = [VesselHit(mmsi=999000010 + n, call_sign=f"QQMNY{n}", ship_name="TEST CARGO A") for n in range(7)]
+    monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: many)
+    monkeypatch.setattr(mof, "plans_for", lambda *a, **k: pytest.fail("후보 수 상한을 넘었는데 조회했다"))
+    found = vessel.find_vessel(facts("TESTVSL0004"))  # 서류로 확정하는 길이 열린 화물
+    assert found["status"] == "ask" and found["reason"] == "schedule_lookup_failed"
+    assert len(found["candidates"]) == 5  # rules/vessel.yaml max_candidates
+
+
+def test_the_call_budget_per_cargo_stops_before_the_limit_is_passed(monkeypatch):
+    # 한 화물의 해수부·ShipFinder 요청 수는 rules의 상한을 넘지 않는다(쪽 넘김은 쪽 수 상한만큼 센다).
+    # 닿으면 배를 지어내지 않고 조회 한도에 닿았다고 한다
+    calls = []
+    for name, module in (("plans_near", mof), ("plans_for", mof), ("vessel_candidates", shipfinder)):
+        real = getattr(module, name)
+        monkeypatch.setattr(module, name, lambda *a, _n=name, _r=real, **k: calls.append(_n) or _r(*a, **k))
+    cfg = load_rules("vessel")
+    vessel.find_vessel(facts("TESTVSL0002"))
+    assert calls[0] == "plans_near" and calls.count("vessel_candidates") == 1
+    monkeypatch.setitem(cfg, "max_find_calls", cfg["max_mrn_pages"])  # MRN 길만 쓰면 바닥이다
+    calls.clear()
+    assert vessel.find_vessel(facts("TESTVSL0002")) == {"status": "unknown", "reason": "call_limit"}
+    assert calls == ["plans_near"]  # 배 검색은 부르지 않았다
+    monkeypatch.setitem(cfg, "max_find_calls", cfg["max_mrn_pages"] - 1)
+    calls.clear()
+    assert vessel.find_vessel(facts("TESTVSL0002")) == {"status": "unknown", "reason": "call_limit"}
+    assert calls == []  # MRN 길의 쪽 수도 못 쓰면 아무것도 부르지 않는다
+
+
+def test_the_same_day_sailing_list_is_fetched_once_per_turn(monkeypatch):
+    calls = []
+    real = mof.plans_near
+    monkeypatch.setattr(mof, "plans_near", lambda *a, **k: calls.append(1) or real(*a, **k))
+    near: dict = {}
+    for number in ("TESTVSL0001", "TESTVSL0002", "TESTVSL0004"):
+        vessel.find_vessel(facts(number), near=near)
+    assert len(calls) == 1  # 세 화물 모두 부산, 같은 입항일
+
+
+def test_the_budget_numbers_add_up_and_leave_the_mrn_path_enough_pages_for_busan():
+    cfg = load_rules("vessel")
+    assert cfg["max_find_calls"] == cfg["max_mrn_pages"] + 1 + cfg["max_candidates"]
+    assert cfg["max_find_calls"] + cfg["verdict_calls"] + cfg["pick_calls"] == cfg["max_calls"]
+    # v1이 부산 5일치를 12쪽으로 쟀다. 창이 3일이면 약 7쪽이라 쪽 상한이 그보다 커야
+    # MRN 길이 too_many로 끝나지 않는다
+    window_days = 2 * load_rules("ports")["ports"]["KRPUS"]["mrn_search_days"] + 1
+    assert cfg["max_mrn_pages"] >= -(-12 * window_days // 5)
```
```diff
--- a/tests/tools/test_mof.py
+++ b/tests/tools/test_mof.py
@@ -440,3 +440,10 @@ def test_plans_for_one_ship_use_the_ports_search_window(monkeypatch):
     incheon = port("KRINC")
     assert incheon is not None
     assert mof.plans_for(incheon, "QQTST1", date(2026, 9, 24)).code == "port_unknown"  # type: ignore[union-attr]
+
+
+def test_plans_near_takes_a_page_cap_for_the_caller_to_count_requests_by():
+    busan = port("KRPUS")
+    assert busan is not None
+    assert isinstance(mof.plans_near(busan, date(2026, 9, 24), max_pages=2), list)
+    assert isinstance(mof.plans_near(busan, date(2026, 9, 24)), list)  # 안 주면 rules/mof.yaml의 쪽 수 상한
```

Run: `uv run pytest tests/graph/test_vessel_step.py tests/tools/test_mof.py -q`
Expected: `1 error in 0.33s`. 실패하는 것: `ERROR tests/graph/test_vessel_step.py`.

- [ ] **Step 2: 코드**

```diff
--- a/rules/vessel.yaml
+++ b/rules/vessel.yaml
@@ -1,6 +1,20 @@
 # 배 식별 단계의 값과 글. 코드(src/marvia/graph/vessel.py, src/marvia/view.py)가 읽는다 (계획 8b, 설계 4.1 ②, 6.3).
 # 스위치 MARVIA_VESSEL=on일 때만 이 단계가 돈다. 기본은 off다.
 max_cargos: 3 # 한 차례에 배를 찾는 화물 수 상한. 넘는 화물은 배를 찾지 않고 그렇다고 적는다
+# 한 화물이 쓰는 해수부·ShipFinder 요청 수 상한(재시도는 세지 않는다. 실패한 요청은 두 번 더 부른다).
+# 배 찾기 max_find_calls = MRN 길의 입항 신고 목록 쪽 수 max_mrn_pages + 배 검색 1 + 후보별 입항 신고 max_candidates.
+# 판정 verdict_calls = 배 위치 1 + 해수부 입항 실적 1 + 입항 예정 1. 닿으면 배를 지어내지 않는다.
+# 고른 뒤 pick_calls = 고른 배의 입항 신고 1(서류로 맞추는 길일 때). 합 max_calls = 18.
+# 한 차례에 많아야 max_cargos x 18 = 54 (같은 날의 입항 신고 목록은 한 번만 받는다)
+# max_mrn_pages 8의 까닭 [추정]: v1이 부산 5일치를 12쪽으로 쟀다(쪽당 50건). MRN 창은 3일(rules/ports.yaml
+# mrn_search_days 1)이라 약 7쪽이다. 쪽 상한을 채우면 8a의 규칙대로 too_many 오류이고 MRN 길이 실패한다.
+# 실제 응답으로 쪽 수를 재 보면 고친다
+max_calls: 18
+max_find_calls: 14
+verdict_calls: 3
+pick_calls: 1
+max_mrn_pages: 8
+max_seconds: 30 # 한 차례에 배 찾기에 쓰는 시간. 넘으면 남은 화물은 찾지 않는다(요청 하나는 15초까지 기다릴 수 있다)
 max_candidates: 5 # 배 후보를 이 수까지만 맞춰 본다. 후보마다 해수부 입항 신고를 한 번 조회한다
 max_choices: 2 # 선택 카드에 보이는 배 후보 수. 권고 선택지(배 없이 진행)와 합쳐 셋까지다 (설계 6.3: 2~3개)
 
@@ -31,6 +45,9 @@ reasons:
   mrn_report_missing: 입항 신고 번호(MRN)로 찾은 입항 신고가 없어 서류로 확정하지 않았어요
   no_clue: 배를 찾을 단서(입항 신고 번호, 배 이름)가 없어요
   lookup_failed: 배 위치 서비스에서 후보를 받지 못했어요
+  call_limit: 조회 한도에 닿아 배를 확인하지 못했어요
+  time_limit: 조회 시간이 길어져 이 화물은 찾지 않았어요
+  not_looked: 이번 차례에는 배를 보지 않았어요
   over_cap: 한 번에 배를 찾는 화물 수를 넘어 이 화물은 찾지 않았어요
   another_question: 다른 화물의 배를 먼저 여쭤봤어요. 이 화물은 배 없이 진행했어요
   user_choice: 고르신 배로 봤어요
```
```diff
--- /dev/null
+++ b/src/marvia/graph/vessel.py
@@ -0,0 +1,126 @@
+"""배 식별 단계: 식별한 화물마다 실은 배를 코드가 찾아 확정하거나 되묻는다 (계획 8b, 설계 4.1 ②, 6.3).
+
+길: 화물의 MRN → 해수부 입항 신고 → 호출부호 → ShipFinder 후보(호출부호, 없으면 세관이 준 배 이름)
+→ (MRN 호출부호가 없거나 맞지 않으면 후보마다 해수부 입항 신고) → tools/vessel_match.match_vessel.
+자동 확정은 두 길뿐이다: (가) MRN에서 얻은 호출부호와 후보의 호출부호가 글자까지 같다,
+(나) MRN 호출부호가 없을 때 그 후보의 입항 신고에서 입항일과 적재항이 둘 다 맞는다.
+한 척이어도, 이름이 같아도 그 밖에는 되묻는다. 배에서 내린 단계의 화물은 배를 찾지 않는다.
+하지 않는 일: LLM에게 고르게 하기, 배 이름·목적지 글·위치로 고르기, 후보의 국적 조회(후보마다 한 번
+더 불러야 해서 두지 않았다. 국적은 모르는 값으로 넘긴다), 판정 계산(tools/judge.py).
+[주의] 스위치 MARVIA_VESSEL=on일 때만 그래프에 들어간다. 꺼져 있으면 이 파일의 어떤 함수도 돌지 않는다.
+[주의] 여기서 얻은 배 이름·호출부호·배 번호는 모델에 주지 않는다. 화면의 화물 카드와 선택 카드로만 간다.
+"""
+
+from __future__ import annotations
+
+import re
+
+from marvia.identify.models import CargoFacts, ToolError
+from marvia.tools import mof, shipfinder
+from marvia.tools.ports import port
+from marvia.tools.rules import load_rules
+from marvia.tools.signals import watches_ship
+from marvia.tools.vessel import SailingPlan
+from marvia.tools.vessel_match import Candidate, MrnLookup, match_vessel
+
+
+def _sign(call_sign: str | None) -> str:
+    return re.sub(r"\s+", "", call_sign or "").upper()
+
+
+def _spend(budget: list[int], cost: int) -> bool:
+    """남은 요청 수에서 cost만큼 쓴다. 모자라면 쓰지 않고 거짓을 돌려준다."""
+    if budget[0] < cost:
+        return False
+    budget[0] -= cost
+    return True
+
+
+def find_vessel(facts: CargoFacts, *, near: dict | None = None) -> dict:
+    """화물 한 건의 배를 찾는다.
+
+    status: confirmed(이 배다), ask(되묻는다), none(후보 없음), unknown(찾지 않았거나 실패).
+
+    near: 같은 차례에 받은 해수부 입항 신고 목록(항만 코드, 입항일 → 목록). 같은 날의 목록은 한 번만 받는다.
+    """
+    cfg = load_rules("vessel")
+    if not watches_ship(facts.stage):
+        return {"status": "unknown", "reason": "landed"}  # [왜] 내린 화물은 배를 조회하지 않는다
+    near = {} if near is None else near
+    budget = [cfg["max_find_calls"]]
+    row = port(facts.port_code) if facts.port_code else None
+    mrn_sign = None
+    lookup: MrnLookup = "none"  # MRN으로 입항 신고를 찾은 결과(vessel_match.MrnLookup)
+    if row and facts.mrn and facts.entry_date:
+        key = (facts.port_code, facts.entry_date)
+        if key not in near:
+            if not _spend(budget, cfg["max_mrn_pages"]):
+                return {"status": "unknown", "reason": "call_limit"}
+            near[key] = mof.plans_near(row, facts.entry_date, max_pages=cfg["max_mrn_pages"])
+        listed = near[key]
+        report = None if isinstance(listed, ToolError) else mof.plan_by_mrn(listed, facts.mrn)
+        if isinstance(listed, ToolError):
+            lookup = "failed"  # 실패, 쪽 상한(too_many), 모양 오류
+        elif report is None:
+            lookup = "not_found"
+        elif _sign(report.call_sign):
+            lookup, mrn_sign = "found_signed", report.call_sign
+        else:
+            lookup = "found_unsigned"
+    keyword = mrn_sign or facts.vessel_name
+    if not keyword:
+        return {"status": "unknown", "reason": "no_clue"}
+    if not _spend(budget, 1):
+        return {"status": "unknown", "reason": "call_limit"}
+    hits = shipfinder.vessel_candidates(keyword)
+    if isinstance(hits, ToolError):
+        # [왜] 클라이언트의 정한 오류 글을 그대로 싣는다: 한도 소진("내일")과 일시 실패("잠시 뒤")가 갈린다
+        return {"status": "unknown", "reason": "lookup_failed", "detail": hits.message}
+    signs = sorted({_sign(h.call_sign) for h in hits} - {""})
+    plans: dict[str, list[SailingPlan] | None] = {}
+    # [왜] 후보마다의 입항 신고는 서류로 확정하는 길(MRN의 신고에 호출부호가 없을 때)에만 쓴다. 다른 길은
+    #      받을 일이 없다. 후보 수가 상한을 넘으면 조회하지 않는다: 목록을 잘라 "한 척만 맞다"고 하지 않고,
+    #      입항 신고를 받지 못한 것으로 넘겨 되묻는다
+    if (
+        hits
+        and row
+        and facts.entry_date
+        and lookup == "found_unsigned"
+        and len(signs) <= cfg["max_candidates"]
+    ):
+        for sign in signs:
+            if not _spend(budget, 1):
+                return {"status": "unknown", "reason": "call_limit"}
+            got = mof.plans_for(row, sign, facts.entry_date)
+            plans[sign] = None if isinstance(got, ToolError) else got
+    # [왜] 배 번호를 글로 둔다. 트레이스 가림(trace.scrub)은 글만 본다. 숫자로 두면 가려지지 않고 나간다
+    ships = [{"mmsi": str(h.mmsi), "call_sign": h.call_sign or None, "name": h.ship_name} for h in hits]
+    listed_hits = [Candidate(mmsi=h.mmsi, call_sign=h.call_sign or None) for h in hits]
+    match = match_vessel(facts, listed_hits, plans, mrn_sign, lookup)
+    if match.status == "confirmed":
+        chosen = next(s for s in ships if s["mmsi"] == str(match.mmsi))
+        return {
+            "status": "confirmed",
+            "reason": match.reason,
+            "basis": match.basis,
+            "cap": match.cap,
+            **chosen,
+        }
+    if match.status == "ask":
+        # 후보마다 서류로 맞춰 본 결과(선택 카드의 "서류로 본 결과"). 그 후보 하나만 있다고 보고 맞춘 이유
+        #      이름이다.
+        # [주의] 여기서는 check_candidate를 부르지 않는다. 그것은 사용자가 고른 뒤(ask_vessel)에 한다
+        shown = []
+        for ship, cand in list(zip(ships, listed_hits, strict=True))[: cfg["max_candidates"]]:
+            alone = match_vessel(facts, [cand], plans, mrn_sign, lookup)
+            shown.append({**ship, "check": alone.reason})
+        # 고른 뒤의 검사가 쓸 것: MRN으로 입항 신고를 찾은 결과와 그 호출부호(공책에는 입항 신고를 두지
+        #      않는다)
+        return {
+            "status": "ask",
+            "reason": match.reason,
+            "candidates": shown,
+            "lookup": lookup,
+            "mrn_call_sign": mrn_sign,
+        }
+    return {"status": "none", "reason": match.reason}
```
```diff
--- a/src/marvia/tools/mof.py
+++ b/src/marvia/tools/mof.py
@@ -373,7 +373,7 @@ def port_schedule(
     )
 
 
-def plans_near(row: Port, day: date) -> list[SailingPlan] | ToolError:
+def plans_near(row: Port, day: date, *, max_pages: int | None = None) -> list[SailingPlan] | ToolError:
     """세관 입항(예정)일 앞뒤의 입항 신고 전체. MRN으로 배를 찾을 때 쓴다(plan_by_mrn). 범위는 항만 표에서."""
     if not row.mof_office or row.mrn_search_days is None:
         return _error("port_unknown")
@@ -390,7 +390,7 @@ def plans_near(row: Port, day: date) -> list[SailingPlan] | ToolError:
             key=key,
             client=client,
             base_url=base_url,
-            max_pages=CFG["max_pages"],
+            max_pages=max_pages or CFG["max_pages"],
         )
 
 
```

- [ ] **Step 3: 확인**: 명령 A. Expected: `1227 passed, 8 skipped`, 오류 0, 명령 B 셋 모두 깨끗함.

- [ ] **Step 4: 커밋**

```bash
git add rules/vessel.yaml src/marvia/graph/vessel.py src/marvia/tools/mof.py tests/graph/test_vessel_step.py tests/tools/test_mof.py
git commit -m "feat(graph): 화물 한 건의 배를 찾는 함수. MRN 호출부호나 MRN 조회가 성공한 서류로 맞춰 본 칸이 있을 때만 확정하고 요청 수 상한을 지킴"
```

### Task 5: 노드 셋을 스위치 뒤에 붙인다 (CB4~CB11, CB13, 결정 B5~B12)

**배울 것:** 끼어들기(`interrupt`)가 있는 노드는 재개할 때 처음부터 다시 돈다. 그래서 바깥 조회(vessel)와 되묻기(ask_vessel)를 다른 노드로 나누고, 되묻는 노드에는 조회를 두지 않는다. 멈춘 값은 체크포인트와 트레이스로 가므로 이름 대신 자리표를 싣는다. 그리고 고른 배는 자동 확정과 다른 이름으로 남긴다. 같은 이름으로 남기면 이 다음 코드가 둘을 구분하지 못한다.

#### 커밋 5: feat(graph): 배 식별 단계(vessel, ask_vessel, verdict)를 스위치 뒤에 붙임. 고른 배는 고른 뒤에 같은 검사에 걸고 확신 상한은 판정이 건다

**Files:**
- Modify/Create: `rules/vessel.yaml`, `src/marvia/graph/main.py`, `src/marvia/graph/state.py`, `src/marvia/graph/vessel.py`
- Test: `tests/graph/test_vessel_step.py`

**Interfaces:**
- Consumes: `find_vessel`, `judge`(cap, cap_note), `check_candidate`, `shipfinder.vessel_position`, `mof.port_schedule`, `mof.plans_for`, `interrupt`, `MarviaState`, `watches_ship`.
- Produces: 공책 칸 `vessels: list[dict]`(`token`, `status`(`confirmed`, `user_choice`, `ask`, `none`, `unknown`), `reason`, `mmsi`, `call_sign`, `name`, `basis`, `cap`, `check`, `detail`), `verdicts: list[dict]`(`token`과 `Verdict`의 칸), `vessel_question: dict | None`(`candidates`, `lookup`, `mrn_call_sign`, `hits` 포함). `marvia.graph.vessel`의 `find_vessels(state) -> dict`, `check_pick(state, token, question, picked) -> Match`, `ask_vessel(state) -> dict`, `verdict_node(now)`. `AgentDeps.now: Callable[[], datetime]`. `build_main_graph(..., vessel: bool = False)`. `rules/vessel.yaml pick_calls`(1).

새 칸 셋은 `start` 노드가 비우지 않는다(`start`를 건드리면 꺼진 공책이 달라진다). `find_vessels`가 차례마다 `vessels`와 `verdicts`를 다시 쓰되, 확정한 배와 "모르겠어요" 답은 말하지 않은 화물 것까지 이어 둔다. `check_pick`은 `check_candidate`에 검색 결과 전체(`hits`)를 넘기고(R-132), 서류로 맞추는 길(`lookup == found_unsigned`)에서만 고른 배의 입항 신고를 한 번 받는다. 받지 못하면 조회 실패다. verdict 노드는 화물 사실이 없는 화물(이번 차례 조회 실패)을 건너뛰고, 배를 본 화물(`confirmed`, `user_choice`)만 위치와 일정을 받고, 상한(`cap`)을 `judge`에 넘기고, 입항 일정 조회에 세관 입항일을 넘긴다. 이 커밋 뒤에 `tests/graph/test_vessel_off.py`가 그대로 통과하는지 꼭 본다(CB1).

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/graph/test_vessel_step.py
+++ b/tests/graph/test_vessel_step.py
@@ -1,8 +1,18 @@
 """배 식별 단계 시험 (계획 8b). 바깥 조회는 재생 데이터이고 키 없이 돈다."""
 
+import json
+from datetime import UTC, datetime
+
 import pytest
+from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
+from langchain_core.messages import AIMessage
+from langgraph.checkpoint.memory import InMemorySaver
+from langgraph.store.memory import InMemoryStore
+from langgraph.types import Command
 
 from marvia.graph import vessel
+from marvia.graph.main import build_main_graph
+from marvia.graph.schemas import Draft
 from marvia.identify.models import CargoFacts, ToolError
 from marvia.tools import mof, shipfinder
 from marvia.tools.rules import load_rules
@@ -95,8 +105,6 @@ def test_a_failed_mrn_lookup_is_a_card_not_a_papers_confirmation(monkeypatch):
 
 def test_no_candidate_no_clue_and_failed_lookup_never_name_a_ship(monkeypatch):
     assert vessel.find_vessel(facts("TESTVSL0003")) == {"status": "none", "reason": "no_candidate"}
-    from datetime import UTC, datetime
-
     bare = CargoFacts(number="TESTVSL0009", stage="입항", fetched_at=datetime.now(UTC))
     monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: pytest.fail("단서 없이 찾았다"))
     assert vessel.find_vessel(bare) == {"status": "unknown", "reason": "no_clue"}
@@ -124,6 +132,7 @@ def test_too_many_candidates_are_asked_without_one_schedule_call_each(monkeypatc
     found = vessel.find_vessel(facts("TESTVSL0004"))  # 서류로 확정하는 길이 열린 화물
     assert found["status"] == "ask" and found["reason"] == "schedule_lookup_failed"
     assert len(found["candidates"]) == 5  # rules/vessel.yaml max_candidates
+    assert len(found["hits"]) == 7  # 검색 결과 전체는 자르지 않는다(같은 호출부호의 배를 가리는 데 쓴다)
 
 
 def test_the_call_budget_per_cargo_stops_before_the_limit_is_passed(monkeypatch):
@@ -164,3 +173,375 @@ def test_the_budget_numbers_add_up_and_leave_the_mrn_path_enough_pages_for_busan
     # MRN 길이 too_many로 끝나지 않는다
     window_days = 2 * load_rules("ports")["ports"]["KRPUS"]["mrn_search_days"] + 1
     assert cfg["max_mrn_pages"] >= -(-12 * window_days // 5)
+
+
+# 아래는 그래프에 붙인 단계 시험. 스위치를 켠 그래프(vessel=True)만 본다. 꺼진 쪽은 test_vessel_off.py가 본다
+NOW = datetime(2026, 9, 22, 3, 0, tzinfo=UTC)  # 한국 시각 09-22 12:00. 재생 배의 마지막 위치 수신 30분 뒤
+
+
+class ToolModel(GenericFakeChatModel):
+    def bind_tools(self, tools, **kwargs):
+        return self
+
+
+def graph_on(agent_deps, prompts: list | None = None, now=NOW):
+    def write(prompt):
+        if prompts is not None:
+            prompts.append(prompt)
+        return Draft(answer="확인했어요", citations=[], next_options=[], forwarder_message="")
+
+    deps = agent_deps(model=ToolModel(messages=iter([AIMessage("")] * 9)), now=lambda: now, write=write)
+    return build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore(), vessel=True)
+
+
+def run(graph, text: str, thread: str = "t"):
+    config = {"configurable": {"thread_id": thread}}
+    graph.invoke({"text": text}, config)
+    return config, graph.get_state(config)
+
+
+def test_confirmed_ship_gets_a_verdict_from_position_and_schedule(agent_deps):
+    _, state = run(graph_on(agent_deps), "TESTVSL0001 어디쯤 왔어요?")
+    assert not state.interrupts
+    ship, cell = state.values["vessels"][0], state.values["verdicts"][0]
+    assert (ship["token"], ship["status"], ship["mmsi"]) == ("[BL1]", "confirmed", "999000001")
+    assert cell["token"] == "[BL1]" and cell["grade"] == "fine" and cell["eta_source"] == "mof_planned"
+    assert cell["trusted_eta"].startswith("2026-09-24T12:00")  # 해수부 입항 예정 09-24 12:00(한국 시각)
+    assert cell["confidence"] == "sure" and cell["schedule"] is None  # 호출부호를 맞췄고, 처음 예정은 없다
+    assert "no_position" not in cell["notes"] and "no_schedule" not in cell["notes"]
+
+
+def test_the_schedule_lookup_gets_the_customs_entry_date(agent_deps, monkeypatch):
+    # [왜] 입항 일정은 세관 입항일 근처로 좁혀 받는다. 입항일을 넘기지 않으면 엉뚱한 날의 신고를 받는다
+    seen = []
+    real = mof.port_schedule
+    monkeypatch.setattr(mof, "port_schedule", lambda *a, **k: (seen.append(k), real(*a, **k))[1])
+    run(graph_on(agent_deps), "TESTVSL0001 어디쯤 왔어요?")
+    assert seen and seen[0]["entry_date"] is not None
+
+
+def test_papers_only_ship_is_capped_at_partial_even_with_every_other_input_clear(agent_deps, monkeypatch):
+    # [왜] 11-15 판정. 호출부호를 맞추지 못하고 서류(입항일·적재항)로만 확정한 배는 확신이 부분을 넘지 못한다.
+    #      TESTVSL0004의 배(QQTST4)는 위치 파일이 없어 이미 부분이다. 위치가 있는 배(QQTST1)로 상한이 실제로
+    #      걸리는지 본다
+    hits = [VesselHit(mmsi=999000001, call_sign="QQTST1"), VesselHit(mmsi=999000005, call_sign="QQTST9")]
+    monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: hits)
+    _, state = run(graph_on(agent_deps), "TESTVSL0004 어디쯤 왔어요?")
+    ship, cell = state.values["vessels"][0], state.values["verdicts"][0]
+    assert (ship["reason"], ship["basis"], ship["cap"]) == (
+        "papers_match",
+        ["entry_date", "loading_port"],
+        "partial",
+    )
+    assert cell["grade"] == "fine" and cell["confidence"] == "partial" and "ship_unchecked" in cell["notes"]
+    _, mrn = run(graph_on(agent_deps), "TESTVSL0001 어디쯤 왔어요?", "t2")
+    assert (
+        mrn.values["verdicts"][0]["confidence"] == "sure"
+        and "ship_unchecked" not in mrn.values["verdicts"][0]["notes"]
+    )
+
+
+def test_without_any_arrival_time_there_is_no_grade_and_the_card_says_why(agent_deps, monkeypatch):
+    _, state = run(graph_on(agent_deps), "TESTVSL0003 TESTVSL0004 어디쯤 왔어요?")
+    ships = {v["token"]: v for v in state.values["vessels"]}
+    cells = {v["token"]: v for v in state.values["verdicts"]}
+    assert (ships["[BL1]"]["status"], ships["[BL1]"]["reason"]) == ("none", "no_candidate")
+    assert cells["[BL1]"]["grade"] is None and cells["[BL1]"]["confidence"] == "unknown"
+    assert {"no_position", "no_eta"} <= set(cells["[BL1]"]["notes"])
+    # 서류로 확정한 배(위치 파일 없음)는 해수부 입항 예정이 있어 등급이 나오되 확신은 부분이다
+    assert ships["[BL2]"]["status"] == "confirmed" and cells["[BL2]"]["eta_source"] == "mof_planned"
+    assert (cells["[BL2]"]["grade"], cells["[BL2]"]["confidence"]) == ("fine", "partial")
+    # 입항 일정도 못 받으면 도착 시각을 알 출처가 없어 등급이 없다
+    failed = ToolError(code="timeout", message="시간 초과", retryable=True)
+    monkeypatch.setattr(mof, "port_schedule", lambda *a, **k: failed)
+    _, none_left = run(graph_on(agent_deps), "TESTVSL0004 어디쯤 왔어요?", "t2")
+    cell = none_left.values["verdicts"][0]
+    assert cell["grade"] is None and cell["confidence"] == "unknown" and "no_eta" in cell["notes"]
+
+
+def test_cargo_off_the_ship_gets_a_customs_only_verdict_and_nothing_is_looked_up(agent_deps, monkeypatch):
+    for module, name in (
+        (shipfinder, "vessel_position"),
+        (shipfinder, "vessel_candidates"),
+        (mof, "port_schedule"),
+    ):
+        monkeypatch.setattr(module, name, lambda *a, **k: pytest.fail("내린 화물인데 바깥을 불렀다"))
+    _, state = run(graph_on(agent_deps), "TESTVSL0006 어디쯤 왔어요?")
+    ship, cell = state.values["vessels"][0], state.values["verdicts"][0]
+    assert (ship["status"], ship["reason"]) == ("unknown", "landed")
+    assert (cell["grade"], cell["confidence"], cell["schedule"], cell["info"]) == (
+        "fine",
+        "sure",
+        None,
+        ["landed"],
+    )
+    assert cell["trusted_eta"] is None and cell["notes"] == []
+
+
+def test_same_name_ships_stop_for_a_choice_card_with_placeholders_not_names(agent_deps):
+    _, state = run(graph_on(agent_deps), "TESTVSL0002 어디쯤 왔어요?")
+    card = state.interrupts[0].value
+    assert sorted(card) == ["kind", "options", "question", "recommended"] and card["kind"] == "choice"
+    assert "[BL1]" in card["question"] and "TESTVSL0002" not in card["question"]
+    assert card["recommended"] == 0 and card["options"][0]["label"] == "모르겠어요"
+    assert [o["label"] for o in card["options"][1:]] == ["{ship1}", "{ship2}"]  # 합쳐 셋
+    # [왜] 끼어들기 값은 트레이스와 체크포인트로 간다. 배 이름·호출부호·배 번호는 자리표로만 싣는다
+    shown = json.dumps(card, ensure_ascii=False)
+    assert not any(word in shown for word in ("TEST CARGO", "QQTST", "99900"))
+    assert state.values["vessels"][0]["status"] == "ask" and state.values["verdicts"] == []
+
+
+@pytest.mark.parametrize(
+    ("reply", "status", "reason", "mmsi"),
+    [
+        ({"selected": 1}, "user_choice", "mrn_report_missing", "999000001"),
+        ({"selected": 2}, "user_choice", "mrn_report_missing", "999000002"),
+        ({"selected": 0}, "unknown", "user_skipped", None),
+        ({"timeout": True}, "unknown", "no_answer", None),
+    ],
+)
+def test_the_reply_to_the_choice_card_decides_and_no_answer_is_an_assumption(
+    agent_deps, reply, status, reason, mmsi
+):
+    graph = graph_on(agent_deps)
+    config, _ = run(graph, "TESTVSL0002 어디쯤 왔어요?")
+    graph.invoke(Command(resume=reply), config)
+    values = graph.get_state(config).values
+    ship = values["vessels"][0]
+    assert (ship["status"], ship["reason"], ship.get("mmsi")) == (status, reason, mmsi)
+    assert values["vessel_question"] is None and len(values["verdicts"]) == 1
+    noted = [a for a in values["assumptions"] if "배를 확인하지 못해" in a]
+    assert len(noted) == (1 if reason == "no_answer" else 0)
+    assert all("[BL1]" in a and "TEST CARGO" not in a for a in noted)  # 가정 글에 배 이름을 넣지 않는다
+
+
+def test_a_picked_ship_stays_a_user_choice_with_its_reason_and_the_cap_reaches_the_judge(
+    agent_deps, monkeypatch
+):
+    # (다) 공책에 user_choice와 그 reason이 그대로 남고 judge에 cap이 넘어간다
+    seen = []
+    real = vessel.judge
+    monkeypatch.setattr(vessel, "judge", lambda *a, **k: seen.append(k.get("cap")) or real(*a, **k))
+    graph = graph_on(agent_deps)
+    config, _ = run(graph, "TESTVSL0002 어디쯤 왔어요?")
+    seen.clear()
+    graph.invoke(Command(resume={"selected": 1}), config)
+    values = graph.get_state(config).values
+    ship, cell = values["vessels"][0], values["verdicts"][0]
+    # MRN으로 찾은 입항 신고가 없어 서류로도 맞춰 볼 수 없다. 사용자 선택만으로는 확실이 되지 않는다
+    assert (ship["status"], ship["reason"], ship["basis"], ship["cap"]) == (
+        "user_choice",
+        "mrn_report_missing",
+        [],
+        "partial",
+    )
+    assert seen == ["partial"]  # judge가 받은 확신 상한 그대로
+    assert cell["grade"] == "fine" and cell["confidence"] == "partial" and "ship_unchecked" in cell["notes"]
+
+
+def test_a_pick_among_ships_sharing_a_call_sign_is_capped_even_though_the_call_sign_matches(agent_deps):
+    graph = graph_on(agent_deps)
+    config, state = run(graph, "TESTVSL0007 어디쯤 왔어요?")
+    assert state.interrupts and state.values["vessels"][0]["reason"] == "same_call_sign_many_mmsi"
+    graph.invoke(Command(resume={"selected": 1}), config)
+    values = graph.get_state(config).values
+    ship, cell = values["vessels"][0], values["verdicts"][0]
+    assert (ship["status"], ship["reason"], ship["cap"]) == (
+        "user_choice",
+        "same_call_sign_many_mmsi",
+        "partial",
+    )
+    assert "call_sign" not in ship["basis"]
+    assert (
+        cell["confidence"] != "sure" and "ship_unchecked" in cell["notes"]
+    )  # 호출부호는 같지만 배를 가르지 못했다
+
+
+def test_the_finder_never_calls_check_candidate_only_the_pick_step_does(monkeypatch):
+    # (나) 배 찾기 단계(되묻기 전)는 check_candidate를 부르지 않는다: 그 검사는 사용자가 고른 뒤의 것이다.
+    #      호출 시험과 소스 읽기(AST) 둘로 본다
+    import ast
+    import inspect
+
+    monkeypatch.setattr(
+        vessel, "check_candidate", lambda *a, **k: pytest.fail("고르기 전에 check_candidate를 불렀다")
+    )
+    for number in ("TESTVSL0001", "TESTVSL0002", "TESTVSL0004", "TESTVSL0005", "TESTVSL0007"):
+        vessel.find_vessel(facts(number))
+    tree = ast.parse(inspect.getsource(vessel))
+    users = {
+        fn.name
+        for fn in ast.walk(tree)
+        if isinstance(fn, ast.FunctionDef)
+        for call in ast.walk(fn)
+        if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "check_candidate"
+    }
+    assert users == {"check_pick"}  # ask_vessel이 check_pick을 통해서만 부른다
+
+
+def test_the_pick_refetches_only_the_picked_ships_report_and_a_failure_is_a_lookup_failure(
+    agent_deps, monkeypatch
+):
+    # 서류로 맞추는 길(TESTVSL0004의 MRN 신고에 호출부호가 없음): 고른 뒤 그 배의 입항 신고를 한 번 받는다.
+    #      그 요청도 화물당 상한(rules pick_calls)의 셈에 든다. 받지 못하면 조회 실패로 보고 확신 상한과
+    #      이유를 단다
+    hits = [VesselHit(mmsi=999000001, call_sign="QQTST1"), VesselHit(mmsi=999000005, call_sign="QQTST9")]
+    monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: hits)
+    monkeypatch.setitem(load_rules("vessel"), "max_candidates", 1)  # 후보 수가 상한을 넘어 되묻는다
+    calls = []
+    real = mof.plans_for
+    monkeypatch.setattr(mof, "plans_for", lambda *a, **k: calls.append(a[1]) or real(*a, **k))
+    graph = graph_on(agent_deps)
+    config, state = run(graph, "TESTVSL0004 어디쯤 왔어요?")
+    assert state.interrupts and calls == []  # 찾을 때는 후보 수 상한 때문에 받지 않았다
+    graph.invoke(Command(resume={"selected": 1}), config)
+    assert calls == ["QQTST1"] and len(calls) <= load_rules("vessel")["pick_calls"]
+    ship = graph.get_state(config).values["vessels"][0]
+    assert (ship["status"], ship["reason"], ship["basis"], ship["cap"]) == (
+        "user_choice",
+        "papers_match",
+        ["entry_date", "loading_port"],
+        "partial",
+    )
+    broken = ToolError(code="timeout", message="시간 초과", retryable=True)
+    monkeypatch.setattr(mof, "plans_for", lambda *a, **k: broken)
+    graph2 = graph_on(agent_deps)
+    config2, _ = run(graph2, "TESTVSL0004 어디쯤 왔어요?", "t2")
+    graph2.invoke(Command(resume={"selected": 1}), config2)
+    failed = graph2.get_state(config2).values["vessels"][0]
+    assert (failed["status"], failed["reason"], failed["cap"]) == (
+        "user_choice",
+        "mrn_lookup_failed",
+        "partial",
+    )
+
+
+def test_only_the_first_undecided_cargo_is_asked_and_the_cap_stops_lookups(agent_deps, monkeypatch):
+    calls = []
+    real = vessel.find_vessel
+    monkeypatch.setattr(
+        vessel, "find_vessel", lambda facts, **kw: calls.append(facts.number) or real(facts, **kw)
+    )
+    monkeypatch.setitem(load_rules("vessel"), "max_cargos", 2)
+    graph = graph_on(agent_deps)
+    _, state = run(graph, "TESTVSL0002 TESTVSL0001 TESTVSL0004")
+    rows = [(v["token"], v["status"], v["reason"]) for v in state.values["vessels"]]
+    assert calls == ["TESTVSL0002", "TESTVSL0001"]  # 상한 2: 셋째 화물은 찾지 않는다
+    assert rows[0][1] == "ask" and rows[1][1] == "confirmed" and rows[2][1:] == ("unknown", "over_cap")
+
+
+def test_second_undecided_cargo_is_not_asked_in_the_same_turn(agent_deps, monkeypatch):
+    ship = {"mmsi": "999000001", "call_sign": None, "name": "", "check": "no_papers", "basis": []}
+    undecided = {"status": "ask", "reason": "no_papers", "candidates": [ship]}
+    monkeypatch.setattr(vessel, "find_vessel", lambda facts, **kw: dict(undecided))
+    _, state = run(graph_on(agent_deps), "TESTVSL0001 TESTVSL0004")
+    rows = [(v["status"], v["reason"]) for v in state.values["vessels"]]
+    assert rows == [("ask", "no_papers"), ("unknown", "another_question")] and len(state.interrupts) == 1
+
+
+def test_the_time_cap_leaves_the_rest_of_the_cargos_unlooked(agent_deps, monkeypatch):
+    clock = iter([0.0, 40.0])  # 시작, 둘째 화물 전(40초 지남)
+    monkeypatch.setattr(vessel, "_clock", lambda: next(clock))
+    _, state = run(graph_on(agent_deps), "TESTVSL0001 TESTVSL0004")
+    rows = [(v["status"], v["reason"]) for v in state.values["vessels"]]
+    assert rows[0][0] == "confirmed" and rows[1] == ("unknown", "time_limit")
+
+
+def test_a_confirmed_ship_is_not_looked_up_again_next_turn(agent_deps, monkeypatch):
+    graph = graph_on(agent_deps)
+    config, _ = run(graph, "TESTVSL0001 어디쯤 왔어요?")
+    monkeypatch.setattr(vessel, "find_vessel", lambda facts, **kw: pytest.fail("확정한 배를 다시 찾았다"))
+    graph.invoke({"text": "TESTVSL0001 지금은요?"}, config)
+    assert graph.get_state(config).values["vessels"][0]["status"] == "confirmed"
+
+
+def test_a_confirmed_ship_is_remembered_across_turns_that_do_not_name_the_cargo(agent_deps, monkeypatch):
+    graph = graph_on(agent_deps)
+    config, _ = run(graph, "TESTVSL0001 어디쯤 왔어요?")
+    graph.invoke({"text": "고마워요"}, config)
+    assert graph.get_state(config).values["verdicts"] == []  # 화물을 말하지 않은 차례에는 판정도 없다
+    monkeypatch.setattr(vessel, "find_vessel", lambda facts, **kw: pytest.fail("확정한 배를 다시 찾았다"))
+    graph.invoke({"text": "TESTVSL0001 지금은요?"}, config)
+    values = graph.get_state(config).values
+    assert values["vessels"][0]["status"] == "confirmed" and values["verdicts"][0]["grade"] == "fine"
+
+
+def test_a_cargo_whose_lookup_fails_this_turn_gets_no_verdict_even_if_its_ship_was_confirmed(
+    agent_deps, monkeypatch
+):
+    from marvia.graph import identify
+
+    graph = graph_on(agent_deps)
+    config, _ = run(graph, "TESTVSL0001 어디쯤 왔어요?")
+    failed = ToolError(code="timeout", message="시간 초과", retryable=True)
+    monkeypatch.setattr(identify, "lookup_cargo", lambda number: failed)
+    graph.invoke({"text": "TESTVSL0001 지금은요?"}, config)
+    values = graph.get_state(config).values
+    assert values["cargos"][0]["facts"] is None and values["verdicts"] == []  # 화물 사실 없이 판정하지 않는다
+    assert values["vessels"][0]["status"] == "confirmed"  # 확정한 배는 남는다
+
+
+def test_the_cap_also_limits_position_and_schedule_lookups_for_ships_already_confirmed(
+    agent_deps, monkeypatch
+):
+    graph = graph_on(agent_deps)
+    config, _ = run(graph, "TESTVSL0001 어디쯤 왔어요?")
+    graph.invoke({"text": "TESTVSL0004 어디쯤 왔어요?"}, config)
+    asked = []
+    real = shipfinder.vessel_position
+    monkeypatch.setattr(shipfinder, "vessel_position", lambda mmsi: asked.append(mmsi) or real(mmsi))
+    monkeypatch.setitem(load_rules("vessel"), "max_cargos", 1)
+    graph.invoke({"text": "TESTVSL0001 TESTVSL0004 둘 다 어디쯤 왔어요?"}, config)
+    values = graph.get_state(config).values
+    assert asked == [999000001]  # 둘째 화물의 배는 확정돼 있어도 이번 차례에는 조회하지 않는다
+    first, second = values["verdicts"]
+    assert "over_cap" not in first["notes"] and first["grade"] == "fine"
+    assert (
+        "over_cap" in second["notes"] and second["grade"] is None
+    )  # 조회하지 않은 화물에 등급을 내지 않는다
+    assert [v["status"] for v in values["vessels"]] == ["confirmed", "confirmed"]  # 확정은 잊지 않는다
+
+
+def test_one_cargo_makes_at_most_the_budgeted_number_of_requests_in_the_verdict_step(agent_deps, monkeypatch):
+    # 위치 1 + 해수부 입항 실적 1 + 입항 예정 1 = rules/vessel.yaml verdict_calls
+    counts = {"n": 0}
+    for module, name in ((shipfinder, "fetch_position"), (mof, "control_arrivals"), (mof, "sailing_plans")):
+        real = getattr(module, name)
+        monkeypatch.setattr(
+            module, name, lambda *a, _r=real, **k: counts.__setitem__("n", counts["n"] + 1) or _r(*a, **k)
+        )
+    graph = graph_on(agent_deps)
+    config, _ = run(graph, "TESTVSL0001 어디쯤 왔어요?")
+    before = counts["n"]
+    graph.invoke({"text": "TESTVSL0001 지금은요?"}, config)  # 확정한 배: 찾기는 건너뛰고 판정의 요청만 남는다
+    assert counts["n"] - before == load_rules("vessel")["verdict_calls"]
+
+
+def test_ship_identifiers_and_ais_text_never_reach_the_model(agent_deps):
+    prompts: list[str] = []
+    graph = graph_on(agent_deps, prompts)
+    config, state = run(graph, "TESTVSL0001 어디쯤 왔어요?")
+    seen = "\n".join(prompts) + "\n".join(str(m.content) for m in state.values["messages"])
+    assert prompts and "QQTST1" not in seen and "999000001" not in seen and "26TEST0001I" not in seen
+    # 배 신호의 목적지 글(재생 값 "BUSAN, KR")은 공책 어디에도 없다
+    assert "BUSAN, KR" not in json.dumps(state.values, ensure_ascii=False, default=str)
+
+
+def test_a_pick_is_checked_against_every_search_hit_not_only_the_ones_the_card_shows(agent_deps, monkeypatch):
+    # R-132. 같은 호출부호의 배가 셋인데 카드에는 둘만 보인다(max_choices). 보이는 하나를 골라도 잘린 쪽의
+    #      같은 호출부호가
+    #      확신 상한을 건다. 후보 목록과 같은 자리로 자르면 상한이 빠진다
+    trio = [VesselHit(mmsi=999000020 + n, call_sign="QQTWN", ship_name="TEST TWIN") for n in range(3)]
+    monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: trio)
+    monkeypatch.setitem(load_rules("vessel"), "max_candidates", 2)
+    graph = graph_on(agent_deps)
+    config, state = run(graph, "TESTVSL0007 어디쯤 왔어요?")
+    question = state.values["vessel_question"]
+    assert len(question["candidates"]) == 2 and len(question["hits"]) == 3
+    graph.invoke(Command(resume={"selected": 1}), config)
+    ship = graph.get_state(config).values["vessels"][0]
+    assert (ship["status"], ship["reason"], ship["cap"]) == (
+        "user_choice",
+        "same_call_sign_many_mmsi",
+        "partial",
+    )
```

Run: `uv run pytest tests/graph/test_vessel_step.py -q`
Expected: `25 failed, 11 passed in 0.72s`. 실패하는 것: `test_too_many_candidates_are_asked_without_one_schedule_call_each`, `test_confirmed_ship_gets_a_verdict_from_position_and_schedule`, `test_the_schedule_lookup_gets_the_customs_entry_date`, `test_papers_only_ship_is_capped_at_partial_even_with_every_other_input_clear`, `test_without_any_arrival_time_there_is_no_grade_and_the_card_says_why`, `test_cargo_off_the_ship_gets_a_customs_only_verdict_and_nothing_is_looked_up`, `test_same_name_ships_stop_for_a_choice_card_with_placeholders_not_names`, `test_the_reply_to_the_choice_card_decides_and_no_answer_is_an_assumption`, `test_the_reply_to_the_choice_card_decides_and_no_answer_is_an_assumption`, `test_the_reply_to_the_choice_card_decides_and_no_answer_is_an_assumption`, `test_the_reply_to_the_choice_card_decides_and_no_answer_is_an_assumption`, `test_a_picked_ship_stays_a_user_choice_with_its_reason_and_the_cap_reaches_the_judge`, `test_a_pick_among_ships_sharing_a_call_sign_is_capped_even_though_the_call_sign_matches`, `test_the_finder_never_calls_check_candidate_only_the_pick_step_does`, `test_the_pick_refetches_only_the_picked_ships_report_and_a_failure_is_a_lookup_failure`, `test_only_the_first_undecided_cargo_is_asked_and_the_cap_stops_lookups`, `test_second_undecided_cargo_is_not_asked_in_the_same_turn`, `test_the_time_cap_leaves_the_rest_of_the_cargos_unlooked`, `test_a_confirmed_ship_is_not_looked_up_again_next_turn`, `test_a_confirmed_ship_is_remembered_across_turns_that_do_not_name_the_cargo`, `test_a_cargo_whose_lookup_fails_this_turn_gets_no_verdict_even_if_its_ship_was_confirmed`, `test_the_cap_also_limits_position_and_schedule_lookups_for_ships_already_confirmed`, `test_one_cargo_makes_at_most_the_budgeted_number_of_requests_in_the_verdict_step`, `test_ship_identifiers_and_ais_text_never_reach_the_model`, `test_a_pick_is_checked_against_every_search_hit_not_only_the_ones_the_card_shows`.

- [ ] **Step 2: 코드**

```diff
--- a/rules/vessel.yaml
+++ b/rules/vessel.yaml
@@ -25,6 +25,8 @@ skip:
   label: 모르겠어요
   description: 배 정보 없이 진행해요. 통관 단계는 그대로 보여 드려요
 candidate: "호출부호 {call_sign} · 배 번호 {mmsi}" # 후보 선택지의 설명. 이름표(label)는 배 이름이다
+candidate_check: "서류로 본 결과: {check}" # 후보 설명 뒤에 붙는 글. {check}는 아래 reasons의 글이다
+no_name: 이름 없는 배 # 후보에 배 이름이 없을 때의 이름표
 no_call_sign: 없음 # 후보에 호출부호가 없을 때 위 글에 넣는 말
 assumption: "{token} 화물의 배를 확인하지 못해 배 정보 없이 진행했어요" # 답 없이 넘어갔을 때 가정으로 남기는 글
 
```
```diff
--- a/src/marvia/graph/main.py
+++ b/src/marvia/graph/main.py
@@ -12,6 +12,9 @@
         → 없으면 에이전트 길과 같은 갈림길(finish / decline / write)
         에이전트 길의 대화 기록(messages)은 차례를 넘어 이어지고, 답(가린 글)이 기록 끝에 붙는다 (계획 3d).
         기록이 길면 brief가 앞부분을 요약하고, 요약 LLM이 실패하면 brief 다음에 finish
+배 식별(vessel이 참일 때, 계획 8b): 화물 조회가 끝난 자리(identify 또는 lookup 다음)와 첫 일 사이에
+        vessel → (가르지 못한 화물이 있으면 ask_vessel) → verdict를 둔다. 세 노드는 graph/vessel.py에 있다.
+        꺼져 있으면(기본) 그 노드를 만들지 않는다
 하지 않는 일: 노드 재시도(LLM은 SDK가 재시도한다).
 LLM·RAG는 AgentDeps로 받는다. 테스트는 가짜 함수·가짜 모델을 넣어 키 없이 돈다.
 """
@@ -22,7 +25,7 @@ import json
 from collections.abc import Callable
 from contextlib import suppress
 from dataclasses import dataclass
-from datetime import date
+from datetime import UTC, date, datetime
 
 import httpx
 import psycopg
@@ -52,6 +55,7 @@ from marvia.graph.tools import (
     worst_search_calls,
 )
 from marvia.graph.verify import verify
+from marvia.graph.vessel import ask_vessel, find_vessels, verdict_node
 from marvia.identify.mask import token_for, unmask
 from marvia.identify.parse import kind_of, read_numbers
 from marvia.llm import LLMFailed
@@ -78,6 +82,7 @@ class AgentDeps:
     # 공식 사이트 조회용 HTTP 클라이언트 (에이전트 길의 official_lookup, 계획 3d). 없으면 그 도구도 없다
     web: httpx.Client | None = None
     watch: WatchDeps | None = None  # 감시 목록 (에이전트 길의 watch_cargo, 계획 3d). 없으면 그 도구도 없다
+    now: Callable[[], datetime] = lambda: datetime.now(UTC)  # 판정의 기준 시각 (배 식별 단계, 계획 8b)
 
 
 def start(state: MarviaState) -> dict:
@@ -236,7 +241,13 @@ def _after_agent(state: MarviaState) -> str:
 
 
 def build_main_graph(
-    deps: AgentDeps, checkpointer=None, *, loop: str = "planner", store=None, permission_mode: str = "ask"
+    deps: AgentDeps,
+    checkpointer=None,
+    *,
+    loop: str = "planner",
+    store=None,
+    permission_mode: str = "ask",
+    vessel: bool = False,
 ):
     """메인 순서도를 조립한다. checkpointer가 있어야 interrupt로 멈췄다가 이어 갈 수 있다.
 
@@ -244,6 +255,8 @@ def build_main_graph(
     store: 장기 기억 저장소(LangGraph Store).
     permission_mode: "ask"면 저장 같은 부작용 앞에서 승인을 받고,
     "auto"면 always_ask 도구만 묻는다 (설계 6.3).
+    vessel: 참이면 화물 조회 뒤에 배 식별 단계(vessel → ask_vessel → verdict)를 둔다 (계획 8b).
+    거짓(기본)이면 그 노드를 만들지 않아 그래프가 그대로다.
     """
     if loop not in LOOPS:
         # [왜] 모르는 이름이 조용히 계획자 길로 떨어지면 다른 길을 돌린 줄 모른다
@@ -501,11 +514,24 @@ def build_main_graph(
     graph.add_edge("start", "identify")
     # [왜] 식별 뒤 첫 일: 계획자 길은 plan, 에이전트 길은 news(감시 변화) → brief
     first = "news" if loop in LOOP_PATHS else "plan"
+    # [왜] 배 식별 단계는 화물 조회가 끝난 자리와 첫 일 사이에 끼운다. 꺼져 있으면 그 자리가 곧 첫 일이다
+    after_cargo = "vessel" if vessel else first
     graph.add_conditional_edges(
-        "identify", lambda state: "ask" if state.get("question") else first, ["ask", first]
+        "identify", lambda state: "ask" if state.get("question") else after_cargo, ["ask", after_cargo]
     )
     graph.add_edge("ask", "lookup")
-    graph.add_edge("lookup", first)
+    graph.add_edge("lookup", after_cargo)
+    if vessel:
+        graph.add_node("vessel", find_vessels)
+        graph.add_node("ask_vessel", ask_vessel)
+        graph.add_node("verdict", verdict_node(deps.now))
+        graph.add_conditional_edges(
+            "vessel",
+            lambda state: "ask_vessel" if state.get("vessel_question") else "verdict",
+            ["ask_vessel", "verdict"],
+        )
+        graph.add_edge("ask_vessel", "verdict")
+        graph.add_edge("verdict", first)
     if loop in LOOP_PATHS:
         if deps.model is None:
             raise ValueError(
```
```diff
--- a/src/marvia/graph/state.py
+++ b/src/marvia/graph/state.py
@@ -82,6 +82,12 @@ class MarviaState(IdentifyState, total=False):
     # [왜] 서브에이전트 안의 메시지는 부모 기록에 들어오지 않는다.
     #      평가가 도구 순서와 방문 순서를 여기서 읽는다
     visits: list[dict]
+    # 아래는 배 식별 단계 칸 (계획 8b). 스위치 MARVIA_VESSEL=on일 때만 생긴다. start가 비우지 않고
+    # vessel 노드가 차례마다 다시 쓴다. [주의] 모델에 주지 않는다. 화면의 화물 카드로만 간다
+    # 화물마다 배 확인 결과 {"token", "status", "reason", "mmsi"(글), "call_sign", "name", "basis", "check"}
+    vessels: list[dict]
+    verdicts: list[dict]  # 화물마다 판정 {"token", ...tools/judge.Verdict}
+    vessel_question: dict | None  # 배를 가리지 못해 물을 선택 카드와 후보. 없으면 None
 
 
 def merge_evidence(old: list[dict], new: list[dict], limit: int) -> list[dict]:
```
```diff
--- a/src/marvia/graph/vessel.py
+++ b/src/marvia/graph/vessel.py
@@ -14,14 +14,23 @@
 from __future__ import annotations
 
 import re
+import time
+from collections.abc import Callable
+from datetime import datetime
 
+from langgraph.types import interrupt
+
+from marvia.graph.state import MarviaState
 from marvia.identify.models import CargoFacts, ToolError
 from marvia.tools import mof, shipfinder
+from marvia.tools.judge import judge
 from marvia.tools.ports import port
 from marvia.tools.rules import load_rules
 from marvia.tools.signals import watches_ship
-from marvia.tools.vessel import SailingPlan
-from marvia.tools.vessel_match import Candidate, MrnLookup, match_vessel
+from marvia.tools.vessel import KST, SailingPlan
+from marvia.tools.vessel_match import Candidate, Match, MrnLookup, check_candidate, match_vessel
+
+_clock = time.monotonic  # [왜] 시험이 시계를 바꿔 끼운다
 
 
 def _sign(call_sign: str | None) -> str:
@@ -120,7 +129,185 @@ def find_vessel(facts: CargoFacts, *, near: dict | None = None) -> dict:
             "status": "ask",
             "reason": match.reason,
             "candidates": shown,
+            # 검색 결과 전체(카드에 보이는 둘이나 상한으로 자르기 전). 같은 호출부호의 다른 배를 가리는 데
+            #      쓴다
+            "hits": [{"mmsi": ship["mmsi"], "call_sign": ship["call_sign"]} for ship in ships],
             "lookup": lookup,
             "mrn_call_sign": mrn_sign,
         }
     return {"status": "none", "reason": match.reason}
+
+
+def find_vessels(state: MarviaState) -> dict:
+    """vessel 노드: 조회에 성공한 화물마다 배를 찾는다. 한 차례에 max_cargos건까지 찾고 하나만 되묻는다."""
+    cfg = load_rules("vessel")
+    # [왜] 확정한 배와 "모르겠어요"라고 답한 화물은 같은 대화에서 다시 찾거나 다시 묻지 않는다
+    kept = {
+        v["token"]: v
+        for v in state.get("vessels", [])
+        if v["status"] in ("confirmed", "user_choice") or v["reason"] == "user_skipped"
+    }
+    rows: list[dict] = []
+    question = None
+    looked = 0
+    started = _clock()
+    near: dict = {}  # 같은 차례에 같은 항만·같은 날의 해수부 입항 신고 목록은 한 번만 받는다
+    for cargo in state.get("cargos", []):
+        token = cargo["token"]
+        if not cargo.get("facts"):
+            continue  # 조회에 실패한 화물은 화물 카드가 이미 그 까닭을 보인다
+        facts = CargoFacts.model_validate(cargo["facts"])
+        if token in kept:
+            rows.append(kept[token])
+            continue
+        if not watches_ship(facts.stage):
+            rows.append({"token": token, "status": "unknown", "reason": "landed"})  # 바깥 호출이 없다
+            continue
+        if looked >= cfg["max_cargos"]:
+            rows.append({"token": token, "status": "unknown", "reason": "over_cap"})
+            continue
+        if looked and _clock() - started >= cfg["max_seconds"]:
+            rows.append({"token": token, "status": "unknown", "reason": "time_limit"})
+            continue
+        looked += 1
+        found = find_vessel(facts, near=near)
+        ships = found.pop("candidates", [])
+        meta = {
+            "lookup": found.pop("lookup", "none"),
+            "mrn_call_sign": found.pop("mrn_call_sign", None),
+            "hits": found.pop("hits", []),
+        }
+        if found["status"] == "ask" and question is not None:
+            found = {"status": "unknown", "reason": "another_question"}
+        elif found["status"] == "ask":
+            # [왜] 이름·호출부호·배 번호는 끼어들기 값에 싣지 않는다(트레이스와 체크포인트로 간다).
+            #      자리표만 싣고 서버가 화면으로 보낼 때 이 후보들(question["candidates"])로 바꾼다
+            options = [
+                {"label": f"{{ship{i}}}", "description": f"{{ship{i}_info}}"}
+                for i in range(1, min(len(ships), cfg["max_choices"]) + 1)
+            ]
+            question = {
+                "kind": "choice",
+                "question": cfg["question"].format(token=token),
+                "options": [cfg["skip"], *options],
+                "recommended": 0,  # [왜] 근거 없이 한 척을 권하지 않는다. 권고는 "배 없이 진행"이다
+                "token": token,
+                "candidates": ships,
+                **meta,  # 고른 뒤 검사가 쓴다
+            }
+        rows.append({"token": token, **found})
+    # [왜] 화물 칸은 이번 차례에 말한 화물만 담는다. 말하지 않은 화물의 확정과 답도 다음 차례를 위해 남긴다
+    seen = {row["token"] for row in rows}
+    rows += [row for token, row in kept.items() if token not in seen]
+    return {"vessels": rows, "vessel_question": question, "verdicts": []}
+
+
+def check_pick(state: MarviaState, token: str, question: dict, picked: dict) -> Match:
+    """고른 후보를 check_candidate에 건다. 그 배의 입항 신고는 서류로 맞추는 길일 때만 한 번 받는다."""
+    cargo = next(c for c in state.get("cargos", []) if c["token"] == token)
+    facts = CargoFacts.model_validate(cargo["facts"])
+    # [왜] 검색 결과 전체를 넘긴다. 카드에 보인 후보만 넘기면 잘린 쪽의 같은 호출부호의 배를 놓쳐 상한이
+    #      빠진다
+    everyone = [Candidate(mmsi=int(c["mmsi"]), call_sign=c["call_sign"]) for c in question["hits"]]
+    mine = Candidate(mmsi=int(picked["mmsi"]), call_sign=picked["call_sign"])
+    lookup: MrnLookup = question.get("lookup", "none")
+    plans: dict[str, list[SailingPlan] | None] = {}
+    row = port(facts.port_code) if facts.port_code else None
+    sign = _sign(picked["call_sign"])
+    if lookup == "found_unsigned" and sign and row and facts.entry_date:
+        got = mof.plans_for(row, sign, facts.entry_date)
+        if isinstance(got, ToolError):
+            lookup = (
+                "failed"  # 고른 뒤의 조회가 실패하면 조회 실패로 본다(확신 상한과 이유 mrn_lookup_failed)
+            )
+        else:
+            plans[sign] = got
+    return check_candidate(facts, mine, everyone, plans, question.get("mrn_call_sign"), lookup)
+
+
+def ask_vessel(state: MarviaState) -> dict:
+    """ask_vessel 노드: 선택 카드로 묻고 답으로 배를 정한다. 답이 없으면 배 없이 진행하고 가정으로 남긴다."""
+    cfg = load_rules("vessel")
+    question = state.get("vessel_question") or {}
+    # [주의] 재개하면 이 노드가 처음부터 다시 돈다. interrupt 앞에 바깥 조회를 두지 않는다
+    reply = interrupt({k: question[k] for k in ("kind", "question", "options", "recommended")}) or {}
+    ships, picked = question["candidates"], None
+    selected = reply.get("selected")
+    # [왜] 번호만 받는다. 직접 입력한 글은 서버가 후보와 맞춰 번호로 바꿔 보낸다(server.turn_input)
+    #      그래서 사용자가 적은 호출부호가 그래프의 입력과 트레이스에 실리지 않는다
+    if isinstance(selected, int) and 1 <= selected <= len(ships):
+        picked = ships[selected - 1]
+    reason = "user_skipped" if "selected" in reply else "no_answer"  # 시간 초과나 취소는 선택이 없다
+    token = question["token"]
+    if picked:
+        # [왜] 사용자가 고른 배를 같은 검사에 건다(check_candidate). 서류로 맞추는 길(MRN 조회가 성공했고
+        #      신고에
+        #      호출부호가 없을 때)에는 그 배의 입항 신고를 이때 한 번 받는다(해수부 요청 1회, rules
+        #      pick_calls).
+        #      받지 못하면 조회 실패로 본다. 입항 신고는 공책에 두지 않는다
+        found = check_pick(state, token, question, picked)
+        row = {
+            "token": token,
+            "status": found.status,  # user_choice: 자동 확정(confirmed)과 구분한다
+            "reason": found.reason,
+            "basis": found.basis,
+            "cap": found.cap,
+            "mmsi": picked["mmsi"],
+            "call_sign": picked["call_sign"],
+            "name": picked["name"],
+        }
+    else:
+        row = {"token": token, "status": "unknown", "reason": reason}
+    update: dict = {
+        "vessels": [row if v["token"] == token else v for v in state.get("vessels", [])],
+        "vessel_question": None,
+    }
+    if not picked and reason == "no_answer":
+        update["assumptions"] = [*state.get("assumptions", []), cfg["assumption"].format(token=token)]
+    return update
+
+
+# [주의] 돌려주는 타입을 Callable로 적지 않는다. 인자 이름(state)이 빠져 add_node 타입 검사가 거절한다
+def verdict_node(now: Callable[[], datetime]):
+    """verdict 노드를 만든다. now는 판정의 기준 시각(시험이 고정한다)."""
+
+    def verdict(state: MarviaState) -> dict:
+        ships = {v["token"]: v for v in state.get("vessels", [])}
+        limit = load_rules("vessel")["max_cargos"]
+        out = []
+        looked = 0
+        for cargo in state.get("cargos", []):
+            ship = ships.get(cargo["token"])
+            # [왜] 이번 차례의 화물 조회가 실패했으면 지난 차례에 배를 확정했어도 판정하지 않는다
+            if ship is None or not cargo.get("facts"):
+                continue
+            facts = CargoFacts.model_validate(cargo["facts"])
+            position = plan = None
+            # [왜] 배를 확정하지 못했거나 내린 화물이면 위치와 일정을 부르지 않는다.
+            #      판정은 화물 사실만으로 낸다(tools/judge.py). 도착 시각을 모르니 등급이 비고
+            #      확신이 내려간다. 값을 지어내지 않는다
+            sailing = ship["status"] in ("confirmed", "user_choice")
+            capped = sailing and looked >= limit
+            if sailing and not capped:
+                looked += 1
+                got = shipfinder.vessel_position(int(ship["mmsi"]))
+                position = None if isinstance(got, ToolError) else got
+                row = port(facts.port_code) if facts.port_code else None
+                if row and ship.get("call_sign"):
+                    today = now().astimezone(KST).date()  # 한국 날짜
+                    schedule = mof.port_schedule(
+                        row, ship["call_sign"], today=today, entry_date=facts.entry_date
+                    )
+                    plan = None if isinstance(schedule, ToolError) else schedule
+            # [왜] 호출부호를 코드로 맞춘 배만 "확실"이 될 수 있다. 서류(입항일·적재항)로만 확정했거나
+            #      사용자가 고른 배,
+            #      같은 호출부호의 배가 여럿인 배는 확신이 부분을 넘지 못한다(11-15 판정). 상한은 judge가 건다
+            cap = ship.get("cap") if sailing else None
+            found = judge(facts, position, plan, now=now(), cap=cap, cap_note="ship_unchecked")
+            found = found.model_dump(mode="json")
+            if capped:
+                found["notes"].append("over_cap")  # 글은 rules/vessel.yaml reasons에 있다
+            out.append({"token": cargo["token"], **found})
+        return {"verdicts": out}
+
+    return verdict
```

- [ ] **Step 3: 확인**: 명령 A. Expected: `1251 passed, 8 skipped`, 오류 0, 명령 B 셋 모두 깨끗함.

- [ ] **Step 4: 커밋**

```bash
git add rules/vessel.yaml src/marvia/graph/main.py src/marvia/graph/state.py src/marvia/graph/vessel.py tests/graph/test_vessel_step.py
git commit -m "feat(graph): 배 식별 단계(vessel, ask_vessel, verdict)를 스위치 뒤에 붙임. 고른 배는 고른 뒤에 같은 검사에 걸고 확신 상한은 판정이 건다"
```

### Task 6: 화물 카드의 배와 판정 칸, 선택 카드의 자리표 채우기 (CB7, CB8, CB11, CB14, 결정 B6, B8, B14)

**배울 것:** 화면으로 가는 값은 허용 목록 한 곳(`view.py`)에서만 고른다. 판정의 이름(`fine`, `no_eta`)을 사람이 읽는 글로 바꾸는 일도 거기서 하고, 글은 규칙 파일에서 온다. 화면은 등급을 정하지 않고 받은 글을 보인다. 칸을 붙일지는 공책이 아니라 서버가 정한다.

#### 커밋 6: feat(server): 스위치가 켜져 있으면 화물 카드에 배와 판정 칸을 보임. 선택 카드는 자리표를 후보로 바꾸고 직접 적은 글은 번호로 바꿔 넘김

**Files:**
- Modify/Create: `rules/vessel.yaml`, `src/marvia/server.py`, `src/marvia/view.py`
- Test: `tests/graph/test_vessel_screen.py`

**Interfaces:**
- Consumes: 공책 칸 `vessels`, `verdicts`, `vessel_question`, `GRADE_LABEL`, `CONFIDENCE_LABEL`, `SCHEDULE_LABEL`, `rules/vessel.yaml`, `rules/verdict.yaml`.
- Produces: 화물 카드의 `ship`(`status`, `reason`, `detail`, `check`, `name`, `call_sign`, `mmsi`)과 `verdict`(`grade`, `grade_label`, `confidence`, `schedule`, `eta`, `eta_source`, `margin_days`, `signals`, `notes`, `info`). `screen_view(values, vessel=False)`, `interrupt_card(value, mask_map, candidates=None)`, `ship_texts`, `vessel_choice(typed, candidates) -> int`, `is_vessel_card(value) -> bool`. `server.LIVE_KEYS`에 `vessels`, `verdicts`. 서버는 그래프에 `vessel` 노드가 있을 때만 칸을 붙이고(`getattr(graph, "nodes", {})`), 서버 진입점이 `vessel=settings.vessel == "on"`을 넘긴다. 배 선택 카드의 직접 입력은 서버(`turn_input`)가 후보와 맞춰 번호로 바꿔 넘긴다. `rules/vessel.yaml labels.signals`, `candidate_check`, `no_name`.

고른 배(`user_choice`)의 카드는 이유 글을 "고르신 배로 봤어요"로 쓰고 맞춰 본 결과 글(`check`)은 그 행의 이유 글이다. 상태가 아니라 이유와 근거에서 글을 만들어 자동 확정의 글("... 같아요")이 고른 배에 붙지 않는다. 선택 카드에서 멈춘 동안에는 그 화물의 `verdict`가 `None`이고 `ship.status`가 `ask`다. 화면은 "배를 확인한 뒤에 보여 드려요"를 그때만 보인다. 직접 입력의 번호 바꾸기는 멈춘 카드가 배 선택 카드일 때만 한다(멈춘 값의 선택지 이름이 자리표인지로 가른다. 공책에 남은 옛 배 질문으로 가르면 그 사이에 뜬 오타 번호 카드의 답이 배 번호로 바뀐다). 길이와 모양 검사를 먼저 하고, 바꾼 번호는 후보 목록 안이라 카드에 안 보인 셋째 후보도 맞는다. 후보 중 호출부호가 둘 이상의 배에 걸리는 글은 어느 배도 고르지 못하고(0번) 배 번호는 고른다. `graph.nodes`를 읽는 줄은 가짜 그래프(`nodes`가 없는 객체)로 서버를 시험하는 기존 시험이 있어 `getattr`로 읽는다.

- [ ] **Step 1: 실패하는 시험**

```diff
--- /dev/null
+++ b/tests/graph/test_vessel_screen.py
@@ -0,0 +1,283 @@
+"""배 식별 단계의 화면 쪽 시험: 화물 카드의 배·판정 칸과 선택 카드 (계획 8b). 스위치를 켠 그래프만 본다."""
+
+import json
+from datetime import UTC, datetime
+
+import pytest
+from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
+from langchain_core.messages import AIMessage
+from langgraph.checkpoint.memory import InMemorySaver
+from langgraph.store.memory import InMemoryStore
+from starlette.testclient import TestClient
+
+from marvia.graph.main import build_main_graph
+from marvia.server import build_app
+from marvia.tools.rules import load_rules
+from marvia.view import screen_view
+
+NOW = datetime(2026, 9, 22, 3, 0, tzinfo=UTC)  # 한국 시각 09-22 12:00
+CARD_KEYS = [
+    "error",
+    "fetched_at",
+    "number",
+    "port",
+    "ship",
+    "source",
+    "stage",
+    "stage_at",
+    "verdict",
+    "vessel",
+]
+
+
+class ToolModel(GenericFakeChatModel):
+    def bind_tools(self, tools, **kwargs):
+        return self
+
+
+def served(agent_deps, now=NOW, vessel=True):
+    deps = agent_deps(model=ToolModel(messages=iter([AIMessage("")] * 9)), now=lambda: now)
+    graph = build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore(), vessel=vessel)
+    return TestClient(build_app(graph, lambda token: "user-a", web_origin="http://web.test", forget=print))
+
+
+def run(client, thread: str, text: str = "", resume: list | None = None) -> list[dict]:
+    payload: dict = {"threadId": thread, "runId": f"run-{thread}", "messages": []}
+    if text:
+        payload["messages"] = [{"id": "m1", "role": "user", "content": text}]
+    if resume:
+        payload["resume"] = resume
+    response = client.post("/agui", json=payload, headers={"Authorization": "Bearer tok"})
+    assert response.status_code == 200, response.text
+    return [json.loads(line[6:]) for line in response.text.split("\n") if line.startswith("data: ")]
+
+
+def cards(events: list[dict]) -> list[dict]:
+    return [e["snapshot"] for e in events if e["type"] == "STATE_SNAPSHOT"][-1]["cargos"]
+
+
+def test_cargo_card_carries_ship_and_verdict_in_fixed_words(agent_deps):
+    events = run(served(agent_deps), "s1", "TESTVSL0001 TESTVSL0003 어디쯤 왔어요?")
+    assert events[-1]["outcome"] == {"type": "success"}
+    first, second = cards(events)
+    assert sorted(first) == CARD_KEYS and first["number"] == "TESTVSL0001"
+    assert first["ship"] == {
+        "status": "confirmed",
+        "reason": "맞춰 본 칸은 호출부호예요. 입항 신고의 호출부호와 같아요",
+        "detail": None,
+        "check": None,
+        "name": "TEST CARGO A",
+        "call_sign": "QQTST1",
+        "mmsi": "999000001",
+    }
+    cell = first["verdict"]
+    assert (cell["grade"], cell["grade_label"], cell["confidence"], cell["schedule"]) == (
+        "fine",
+        "순항",
+        "확실",
+        "일정 모름",  # 처음 알던 도착 예정을 받지 않아 지연을 보지 못했다: 일정 칸은 비어 있다
+    )
+    assert cell["eta"].startswith("2026-09-24T12:00") and cell["eta_source"] == "해수부 입항 예정"
+    assert cell["signals"] == [] and cell["notes"] == []
+    # 판매 예정일과 처음 알던 도착 예정을 받는 통로가 아직 없다. 카드가 그렇다고 말한다
+    assert cell["margin_days"] is None
+    assert cell["info"] == [
+        "판매 예정일을 받지 않아 여유 일수는 세지 않았어요. 배와 통관 상태만으로 본 등급이에요",
+        "처음 알던 도착 예정이 없어 지연은 보지 못했어요",
+    ]
+    # 배를 확인하지 못한 화물: 등급을 지어내지 않고 "등급 없음"과 그 까닭을 보인다
+    assert second["ship"]["status"] == "none" and second["ship"]["reason"] == "배 후보를 찾지 못했어요"
+    assert second["ship"]["name"] is None and second["ship"]["mmsi"] is None
+    lost = second["verdict"]
+    assert lost["grade"] is None and lost["grade_label"] == "등급 없음" and lost["schedule"] == "일정 모름"
+    assert lost["confidence"] == "불명" and lost["eta"] is None and lost["eta_source"] is None
+    assert "도착 시각을 알 출처가 없어 등급을 내지 않았어요" in lost["notes"]
+
+
+def test_lookup_failure_texts_differ_between_quota_and_a_passing_failure(agent_deps, monkeypatch):
+    from marvia.identify.models import ToolError
+    from marvia.tools import shipfinder
+
+    quota = ToolError(code="quota_exhausted", message="오늘 조회할 수 있는 횟수를 다 썼어요", retryable=False)
+    monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: quota)
+    ship = cards(run(served(agent_deps), "s5", "TESTVSL0004 어디쯤 왔어요?"))[0]["ship"]
+    assert ship["reason"] == "배 위치 서비스에서 후보를 받지 못했어요"
+    assert ship["detail"] == "오늘 조회할 수 있는 횟수를 다 썼어요"  # 클라이언트의 정한 글 그대로
+    busy = ToolError(code="busy", message="서비스가 바빠요. 잠시 뒤 다시 조회할 수 있어요", retryable=True)
+    monkeypatch.setattr(shipfinder, "vessel_candidates", lambda keywords: busy)
+    again = cards(run(served(agent_deps), "s6", "TESTVSL0004 어디쯤 왔어요?"))[0]["ship"]
+    assert again["detail"] != ship["detail"] and "잠시 뒤" in again["detail"]
+
+
+def test_cargo_off_the_ship_says_so_and_shows_customs_only(agent_deps):
+    card = cards(run(served(agent_deps), "s7", "TESTVSL0006 어디쯤 왔어요?"))[0]
+    assert card["ship"]["reason"] == "배에서 내린 화물이라 배 위치는 보지 않았어요"
+    assert (card["verdict"]["grade_label"], card["verdict"]["eta"]) == ("순항", None)
+    assert card["verdict"]["info"] == [
+        "배에서 내린 화물이라 배 위치는 보지 않았어요. 통관 단계만으로 본 등급이에요"
+    ]
+
+
+def test_a_cargo_the_loop_looked_up_itself_says_the_ship_was_not_looked_at_this_turn(agent_deps):
+    # [왜] 루프 안에서 lookup_cargo로 새로 찾은 화물은 배 식별 단계를 지나지 않는다(결정 3). "확인한 뒤에 보여
+    #      드려요"가 아니라 사실대로 말한다
+    values = {
+        "cargos": [{"token": "[BL1]", "facts": {"stage": "입항", "fetched_at": "2026-09-22T03:00:00Z"}}],
+        "mask_map": {"[BL1]": "TESTVSL0001"},
+        "vessels": [],
+        "verdicts": [],
+    }
+    card = screen_view(values, vessel=True)["cargos"][0]
+    assert card["ship"]["reason"] == "이번 차례에는 배를 보지 않았어요" and card["verdict"] is None
+
+
+def test_the_cards_follow_the_server_switch_not_leftover_values_in_the_notebook(agent_deps):
+    # [왜] 스위치를 켰다가 끈 대화의 공책에는 vessels·verdicts가 남아 있다. 꺼진 서버는 그 칸을 보이지 않는다
+    values = {
+        "cargos": [{"token": "[BL1]", "facts": {"stage": "입항", "fetched_at": "2026-09-22T03:00:00Z"}}],
+        "mask_map": {"[BL1]": "TESTVSL0001"},
+        "vessels": [{"token": "[BL1]", "status": "confirmed", "reason": "mrn_call_sign"}],
+        "verdicts": [],
+    }
+    assert sorted(screen_view(values, vessel=False)["cargos"][0]) == sorted(
+        set(CARD_KEYS) - {"ship", "verdict"}
+    )
+    off = served(agent_deps, vessel=False)
+    assert sorted(cards(run(off, "s8", "TESTVSL0001"))[0]) == sorted(set(CARD_KEYS) - {"ship", "verdict"})
+
+
+def test_triggered_signals_are_named_on_the_card(agent_deps):
+    late = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)  # 마지막 위치 수신 뒤 9시간 반
+    cell = cards(run(served(agent_deps, now=late), "s2", "TESTVSL0001 어디쯤 왔어요?"))[0]["verdict"]
+    assert cell["grade_label"] == "주의" and cell["signals"] == ["배 위치가 한동안 들어오지 않았어요"]
+
+
+def test_every_signal_info_and_note_has_a_card_word():
+    cfg, rules = load_rules("vessel"), load_rules("verdict")
+    assert set(cfg["labels"]["signals"]) == set(rules["signal_ids"])
+    for name in ("over_cap", "call_limit", "not_looked", "landed", "lookup_failed"):
+        assert name in cfg["reasons"], name
+    assert "ship_unchecked" in rules["notes"]  # 확신 상한의 까닭 글은 판정 쪽(rules/verdict.yaml)에 있다
+
+
+def test_choice_card_shows_real_names_in_place_of_placeholders_and_the_typed_text_becomes_a_number(
+    agent_deps,
+):
+    client = served(agent_deps)
+    events = run(client, "s3", "TESTVSL0002 어디쯤 왔어요?")
+    outcome = events[-1]["outcome"]
+    assert outcome["type"] == "interrupt"
+    card = outcome["interrupts"][0]
+    meta = card["metadata"]
+    assert card["reason"] == "choice" and "TESTVSL0002" in meta["question"] and meta["recommended"] == 0
+    assert [o["label"] for o in meta["options"]] == ["모르겠어요", "TEST CARGO A", "TEST CARGO A"]
+    first, second = meta["options"][1]["description"], meta["options"][2]["description"]
+    missing = "MRN)로 찾은 입항 신고가 없어 서류로 확정하지 않았어요"
+    assert "호출부호 QQTST1 · 배 번호 999000001" in first and missing in first
+    assert "호출부호 없음 · 배 번호 999000002" in second and missing in second
+    assert "{ship" not in json.dumps(meta, ensure_ascii=False)  # 자리표가 남지 않는다
+    assert "candidates" not in meta and "token" not in meta  # 화면에는 카드 칸만 간다
+    waiting = cards(events)[0]
+    assert waiting["ship"]["status"] == "ask" and waiting["verdict"] is None
+    # 직접 입력: 서버가 후보와 맞춰 번호로 바꿔 보낸다. 그래프는 사용자가 적은 호출부호를 받지 않는다
+    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"custom": "qqtst1 이에요"}}]
+    events = run(client, "s3", resume=resume)
+    assert events[-1]["outcome"] == {"type": "success"}
+    chosen = cards(events)[0]
+    assert chosen["ship"]["reason"] == "고르신 배로 봤어요" and chosen["ship"]["mmsi"] == "999000001"
+    assert (
+        chosen["verdict"]["confidence"] == "부분"
+        and "호출부호를 맞춰 보지 못해" in chosen["verdict"]["notes"][0]
+    )
+
+
+@pytest.mark.parametrize(
+    ("typed", "reason"),
+    [
+        ("모르겠어요 잘", "배를 모른다고 하셔서 배 없이 진행했어요"),
+        ("QQTST1과 QQTST3 둘 다", "배를 모른다고 하셔서 배 없이 진행했어요"),
+    ],
+)
+def test_typed_text_that_matches_no_single_candidate_is_a_skip(agent_deps, typed, reason):
+    client = served(agent_deps)
+    card = run(client, "s9", "TESTVSL0002 어디쯤 왔어요?")[-1]["outcome"]["interrupts"][0]
+    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"custom": typed}}]
+    assert cards(run(client, "s9", resume=resume))[0]["ship"]["reason"] == reason
+
+
+def test_cancelled_card_goes_on_without_a_ship_and_says_so_in_the_answer(agent_deps):
+    client = served(agent_deps)
+    card = run(client, "s4", "TESTVSL0002 어디쯤 왔어요?")[-1]["outcome"]["interrupts"][0]
+    events = run(client, "s4", resume=[{"interruptId": card["id"], "status": "cancelled"}])
+    assert events[-1]["outcome"] == {"type": "success"}
+    after = cards(events)[0]
+    assert after["ship"]["reason"] == "답이 없어 배 없이 진행했어요" and after["verdict"]["grade"] is None
+    answer = "".join(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT")
+    assert "TESTVSL0002 화물의 배를 확인하지 못해 배 정보 없이 진행했어요" in answer
+
+
+def test_a_hidden_candidate_can_be_picked_by_typing_its_call_sign(agent_deps):
+    # [왜] 카드에는 후보가 둘만 보이지만 후보는 셋이다. 직접 입력은 보이지 않는 셋째도 맞춘다.
+    #      번호가 카드의 선택지 수를 넘어도 서버가 거절하지 않는다(번호는 후보 목록 안이다)
+    client = served(agent_deps)
+    card = run(client, "s10", "TESTVSL0002 어디쯤 왔어요?")[-1]["outcome"]["interrupts"][0]
+    assert len(card["metadata"]["options"]) == 3
+    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"custom": "qqtst3 이에요"}}]
+    events = run(client, "s10", resume=resume)
+    assert events[-1]["outcome"] == {"type": "success"}
+    assert cards(events)[0]["ship"]["mmsi"] == "999000003"
+
+
+def test_an_old_unanswered_ship_question_does_not_take_over_a_later_card(agent_deps):
+    # [왜] 공책의 vessel_question은 다음 차례가 비우기 전까지 남는다. 그 사이에 번호를 묻는 카드(오타)가 뜨면
+    #      사용자가 적은 번호는 그 카드의 답이다. 배 후보와 맞춰 바꾸면 안 된다
+    client = served(agent_deps)
+    first = run(client, "s11", "TESTVSL0002 어디쯤 왔어요?")[-1]["outcome"]["interrupts"][0]
+    assert first["reason"] == "choice"
+    later = run(client, "s11", "DEMU1234565 어디야?")[-1]["outcome"]["interrupts"][0]  # 오타 번호를 묻는 카드
+    assert "컨테이너 번호 모양인데" in later["metadata"]["question"]
+    resume = [{"interruptId": later["id"], "status": "resolved", "payload": {"custom": "TESTVSL0001"}}]
+    events = run(client, "s11", resume=resume)
+    assert events[-1]["outcome"] == {"type": "success"}
+    assert cards(events)[0]["number"] == "TESTVSL0001"  # 적은 번호가 그대로 읽혔다
+
+
+def test_typing_a_call_sign_that_two_ships_share_cannot_pick_either_and_the_mmsi_can(agent_deps):
+    # 호출부호가 같은 두 배(TESTVSL0007): 호출부호만 적으면 어느 배인지 모른다(0번, 모르겠어요). 배 번호를
+    #      적으면 그 배다
+    client = served(agent_deps)
+    card = run(client, "s12", "TESTVSL0007 어디쯤 왔어요?")[-1]["outcome"]["interrupts"][0]
+    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"custom": "qqtwn"}}]
+    skipped = cards(run(client, "s12", resume=resume))[0]
+    assert skipped["ship"]["reason"] == "배를 모른다고 하셔서 배 없이 진행했어요"
+    card = run(client, "s13", "TESTVSL0007 어디쯤 왔어요?")[-1]["outcome"]["interrupts"][0]
+    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"custom": "배 번호 999000008"}}]
+    picked = cards(run(client, "s13", resume=resume))[0]
+    assert (
+        picked["ship"]["mmsi"] == "999000008" and picked["ship"]["check"] == "같은 호출부호의 배가 여럿이에요"
+    )
+    assert picked["verdict"]["confidence"] != "확실"  # 위치와 일정이 없어 등급도 없다(불명). 확실은 아니다
+
+
+def test_a_picked_ship_is_a_user_choice_on_the_card_and_nothing_on_it_reads_as_sure(agent_deps):
+    # (가) 카드 글은 status가 아니라 reason과 basis로 만든다. 고른 배는 확신 상한(부분) 때문에 "확실"로
+    #      보이지 않는다.
+    #      위치와 입항 일정이 모두 있는 배(TESTVSL0002의 QQTST1), 같은 호출부호의 두 배 가운데 하나를 고른
+    #      경우를 본다
+    client = served(agent_deps)
+    card = run(client, "s14", "TESTVSL0002 어디쯤 왔어요?")[-1]["outcome"]["interrupts"][0]
+    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"selected": 1}}]
+    picked = cards(run(client, "s14", resume=resume))[0]
+    assert picked["ship"]["status"] == "user_choice" and picked["ship"]["reason"] == "고르신 배로 봤어요"
+    assert picked["ship"]["check"] == "입항 신고 번호(MRN)로 찾은 입항 신고가 없어 서류로 확정하지 않았어요"
+    assert picked["verdict"]["grade_label"] == "순항" and picked["verdict"]["confidence"] == "부분"
+    assert "호출부호를 맞춰 보지 못해 확신을 부분으로 낮췄어요" in picked["verdict"]["notes"]
+    shown = json.dumps(picked, ensure_ascii=False)
+    assert "확실" not in shown  # 고른 배의 카드 어디에도 "확실"이 없다
+    card = run(client, "s15", "TESTVSL0007 어디쯤 왔어요?")[-1]["outcome"]["interrupts"][0]
+    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"selected": 1}}]
+    twin = cards(run(client, "s15", resume=resume))[0]
+    assert (
+        twin["ship"]["status"] == "user_choice" and twin["ship"]["check"] == "같은 호출부호의 배가 여럿이에요"
+    )
+    assert "확실" not in json.dumps(twin, ensure_ascii=False)
```

Run: `uv run pytest tests/graph/test_vessel_screen.py -q`
Expected: `14 failed, 1 passed in 2.74s`. 실패하는 것: `test_cargo_card_carries_ship_and_verdict_in_fixed_words`, `test_lookup_failure_texts_differ_between_quota_and_a_passing_failure`, `test_cargo_off_the_ship_says_so_and_shows_customs_only`, `test_a_cargo_the_loop_looked_up_itself_says_the_ship_was_not_looked_at_this_turn`, `test_the_cards_follow_the_server_switch_not_leftover_values_in_the_notebook`, `test_triggered_signals_are_named_on_the_card`, `test_every_signal_info_and_note_has_a_card_word`, `test_choice_card_shows_real_names_in_place_of_placeholders_and_the_typed_text_becomes_a_number`, `test_typed_text_that_matches_no_single_candidate_is_a_skip`, `test_typed_text_that_matches_no_single_candidate_is_a_skip`, `test_cancelled_card_goes_on_without_a_ship_and_says_so_in_the_answer`, `test_a_hidden_candidate_can_be_picked_by_typing_its_call_sign`, `test_typing_a_call_sign_that_two_ships_share_cannot_pick_either_and_the_mmsi_can`, `test_a_picked_ship_is_a_user_choice_on_the_card_and_nothing_on_it_reads_as_sure`.

- [ ] **Step 2: 코드**

```diff
--- a/rules/vessel.yaml
+++ b/rules/vessel.yaml
@@ -67,3 +67,10 @@ labels:
     mof_planned: 해수부 입항 예정
     ais_eta: 배 신호
     forwarder_eta: 포워더가 알려 준 날
+  signals: # 켜진 신호의 이름 → 카드에 보이는 글. 열쇠는 rules/verdict.yaml signal_ids와 같다
+    customs_hold: 통관이 보류되었거나 검사 대상으로 지정됐어요
+    anchor_wait: 배가 항구 앞에 오래 멈춰 있어요
+    dest_changed: 배 신호의 목적지가 이 항만이 아니에요
+    position_stale: 배 위치가 한동안 들어오지 않았어요
+    eta_conflict: 배 신호의 도착 예정과 해수부 입항 예정이 어긋나요
+    navstat_mismatch: 배 신호의 항해 상태와 속도가 맞지 않아요
```
```diff
--- a/src/marvia/server.py
+++ b/src/marvia/server.py
@@ -64,7 +64,7 @@ from marvia.graph.state import merge_cargos, merge_evidence
 from marvia.graph.tools import SERVER_SURFACE
 from marvia.tools.rules import load_rules
 from marvia.trace import tracer_callbacks
-from marvia.view import interrupt_card, screen_view
+from marvia.view import interrupt_card, is_vessel_card, screen_view, vessel_choice
 from marvia.watch import forget_user
 
 LOG = logging.getLogger(__name__)
@@ -75,7 +75,8 @@ ERROR_TEXT = "이번 차례를 끝내지 못했어요. 다시 물어봐 주세
 THREAD_ID = re.compile(r"[A-Za-z0-9_-]+")
 # [왜] 프록시·압축이 이벤트를 모았다가 한꺼번에 보내면 "진행 중인 할 일"이 답과 함께 뜬다
 SSE_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}
-LIVE_KEYS = ("todos", "plan", "cargos", "evidence", "mask_map")  # 화면 보기를 바꾸는 공책 칸
+# 화면 보기를 바꾸는 공책 칸. vessels와 verdicts는 배 식별 스위치가 켜졌을 때만 흘러온다 (계획 8b)
+LIVE_KEYS = ("todos", "plan", "cargos", "evidence", "mask_map", "vessels", "verdicts")
 CHOICE_KEYS = ("selected", "custom", "timeout")  # 선택지 재개 값에서 받는 칸 (설계 6.3)
 
 
@@ -117,6 +118,9 @@ def turn_events(
 ) -> Iterator[BaseEvent]:
     """한 차례를 돌리며 AG-UI 이벤트를 낸다. 작업 스레드 하나에서 끝까지 돈다(동기 그래프와 저장기)."""
     yield RunStartedEvent(thread_id=thread, run_id=run)
+    vessel = "vessel" in getattr(
+        graph, "nodes", {}
+    )  # 배 식별 단계가 있는 그래프만 화물 카드에 배·판정 칸을 붙인다 (계획 8b)
     answer = ""
     tail: list[
         BaseEvent
@@ -131,12 +135,13 @@ def turn_events(
                     if not namespace and "answer" in part:
                         answer = part["answer"]  # [왜] 답은 저장하지 않는 칸이라 갱신에서만 읽는다 (R-035)
                     if node != "__interrupt__" and _merge(live, part, inside=bool(namespace)):
-                        yield StateSnapshotEvent(snapshot=screen_view(live))
+                        yield StateSnapshotEvent(snapshot=screen_view(live, vessel))
         state = graph.get_state(config)
         if state.interrupts:
             # [왜] 질문과 승인은 한 번에 하나씩 멈춘다 (batched, ask_user 혼자 부르기)
             pending = state.interrupts[0]
-            card = interrupt_card(pending.value, state.values.get("mask_map", {}))
+            asked = state.values.get("vessel_question") or {}
+            card = interrupt_card(pending.value, state.values.get("mask_map", {}), asked.get("candidates"))
             stopped = CardInterrupt(id=pending.id, reason=card["kind"], metadata=card)
             outcome = RunFinishedInterruptOutcome(interrupts=[stopped])
             tail = [RunFinishedEvent(thread_id=thread, run_id=run, outcome=outcome)]
@@ -215,6 +220,16 @@ def turn_input(graph, body: RunAgentInput, config: dict) -> Any:
             raise Refused(422, "답 모양이 틀렸어요")
         if len(custom) > max_text:
             raise Refused(422, "글이 너무 길어요")
+        if is_vessel_card(value) and custom:
+            # [왜] 멈춘 카드가 배 선택 카드일 때만(공책에 남은 옛 질문이 아니라 멈춘 값으로 가른다).
+            #      직접 적은 글(호출부호나 배 번호)은 후보와 맞춰 번호로 바꿔 그래프에 넘긴다. 사용자가
+            #      적은 값이 노드 입력과 트레이스에 실리지 않는다. 후보 한 척에만 맞을 때만 그 배고 아니면
+            #      "모르겠어요"(0번)다. 카드에 안 보인 후보(둘 넘는 후보)도 맞고 번호는 후보 목록 안이다
+            choice = {
+                "selected": vessel_choice(
+                    custom, (state.values.get("vessel_question") or {}).get("candidates", [])
+                )
+            }
         return Command(resume=choice)
     # [왜] 마지막 메시지 하나만 본다. user가 아니거나 글이 아니면 앞 메시지로 물러서지 않고 거절한다
     last = body.messages[-1] if body.messages else None
@@ -399,7 +414,12 @@ def main() -> None:
     ):
         deps = agent_deps(settings, pool, watch_conn)
         graph = build_main_graph(
-            deps, saver, loop=settings.loop, store=store, permission_mode=settings.permission_mode
+            deps,
+            saver,
+            loop=settings.loop,
+            store=store,
+            permission_mode=settings.permission_mode,
+            vessel=settings.vessel == "on",  # 기본은 off다 (계획 8b)
         )
         app = build_app(
             graph,
```
```diff
--- a/src/marvia/view.py
+++ b/src/marvia/view.py
@@ -4,7 +4,10 @@
 카드와 화물 카드의 토큰을 실제 번호로 되돌리는 일은 여기서 한다. 답 글은 답 노드(graph/main.py)가
 되돌려 이미 번호로 나온다. 가림 표(mask_map)는 dict로 보내지 않고 "이렇게 읽었어요" 목록
 (토큰, 번호, 종류)으로만 보인다. 메시지, 원문(text), 조회할 번호(numbers)도 보내지 않는다.
-하지 않는 일: 답 글 만들기(graph/answer.py), ETA·등급(선박 위치 조회와 함께 2차, 설계 10절 화물 카드).
+배 식별 스위치가 켜진 서버(screen_view의 vessel)는 화물 카드에 배(ship)와 판정(verdict) 칸을 더한다(계획 8b).
+그 값은 코드가 낸 것이고 화면의 글은 rules/vessel.yaml, rules/verdict.yaml이 정한 글이다.
+선택 카드의 후보 이름·호출부호·배 번호는 끼어들기 값에 없고(자리표), 여기서 공책의 후보로 바꿔 채운다.
+하지 않는 일: 답 글 만들기(graph/answer.py), 판정 계산(tools/judge.py).
 """
 
 from __future__ import annotations
@@ -14,6 +17,7 @@ from urllib.parse import urlparse
 
 from marvia.identify.mask import unmask
 from marvia.tools.rules import load_rules
+from marvia.tools.verdict import CONFIDENCE_LABEL, GRADE_LABEL, SCHEDULE_LABEL
 
 # 토큰 이름표 → 화면에 보일 이름 ("이렇게 읽었어요")
 KIND_NAMES = {"BL": "B/L", "CARGO": "화물관리번호", "CNTR": "컨테이너 번호", "NUM": "읽지 못한 덩어리"}
@@ -48,7 +52,70 @@ def _plan(values: dict) -> list[dict]:
     ]
 
 
-def screen_view(values: dict) -> dict:
+def _ship(row: dict | None) -> dict:
+    """화물 카드의 배 칸. [주의] 배 이름·호출부호·배 번호는 화면에만 보인다. 모델에는 가지 않는다."""
+    reasons = load_rules("vessel")["reasons"]
+    if row is None:  # 이번 차례에 배 식별 단계를 지나지 않은 화물(루프 안에서 새로 찾은 화물)
+        return {
+            "status": "unknown",
+            "reason": reasons["not_looked"],
+            "detail": None,
+            "check": None,
+            "name": None,
+            "call_sign": None,
+            "mmsi": None,
+        }
+    # [왜] 화면 글은 status가 아니라 reason과 basis로 만든다. 사용자가 고른 배(status user_choice)는 "고르신
+    #      배로
+    #      봤어요"에 그 검사의 reason 글(맞춘 칸이나 맞추지 못한 까닭)을 서류로 본 결과로 덧붙인다
+    picked = row["status"] == "user_choice"
+    return {
+        "status": row["status"],
+        "reason": reasons["user_choice"] if picked else reasons[row["reason"]],
+        "detail": row.get("detail"),  # 조회 클라이언트의 정한 오류 글. 한도 소진과 일시 실패가 갈린다
+        "check": reasons[row["reason"]] if picked else None,
+        "name": row.get("name"),
+        "call_sign": row.get("call_sign"),
+        "mmsi": row.get("mmsi"),
+    }
+
+
+def _verdict(row: dict) -> dict:
+    """화물 카드의 판정 칸. 등급이 없으면 "등급 없음"과 그 까닭(notes)을 보인다."""
+    labels, texts, reasons = (
+        load_rules("vessel")["labels"],
+        load_rules("verdict"),
+        load_rules("vessel")["reasons"],
+    )
+    return {
+        "grade": row["grade"],  # 색을 고르는 이름(fine·watch·alert·act). 없으면 None
+        "grade_label": GRADE_LABEL.get(row["grade"], labels["no_grade"]),
+        "confidence": CONFIDENCE_LABEL[row["confidence"]],
+        "schedule": SCHEDULE_LABEL.get(row["schedule"], labels["no_schedule"]),
+        "eta": row["trusted_eta"],
+        "eta_source": labels["eta_sources"].get(row["eta_source"]),
+        "margin_days": row["margin_days"],
+        "signals": [labels["signals"][s["id"]] for s in row["signals"] if s["state"] == "triggered"],
+        # 판정 함수의 이유는 verdict.yaml에, 배 식별 단계가 더한 이유(over_cap 등)는 vessel.yaml에 있다
+        "notes": [texts["notes"].get(name) or reasons[name] for name in row["notes"]],
+        "info": [texts["info"][name] for name in row["info"]],
+    }
+
+
+def ship_texts(candidates: list[dict]) -> dict[str, str]:
+    """선택 카드의 자리표({ship1}, {ship1_info}) → 후보의 이름과 설명. 번호는 후보 순서(1부터)다."""
+    cfg = load_rules("vessel")
+    out: dict[str, str] = {}
+    for i, ship in enumerate(candidates, 1):
+        info = cfg["candidate"].format(call_sign=ship["call_sign"] or cfg["no_call_sign"], mmsi=ship["mmsi"])
+        if ship.get("check"):
+            info += " · " + cfg["candidate_check"].format(check=cfg["reasons"][ship["check"]])
+        out[f"{{ship{i}}}"] = ship["name"] or cfg["no_name"]
+        out[f"{{ship{i}_info}}"] = info
+    return out
+
+
+def screen_view(values: dict, vessel: bool = False) -> dict:
     """STATE_SNAPSHOT에 실을 값: 할 일, "이렇게 읽었어요", 화물 카드, 근거 패널."""
     mask_map = values.get("mask_map", {})
     reading = [
@@ -56,8 +123,17 @@ def screen_view(values: dict) -> dict:
         for token, number in mask_map.items()
     ]
     cargos = []
+    # [왜] 칸을 붙일지는 공책이 아니라 서버의 스위치가 정한다. 켰다가 끈 대화의 옛 값은 보이지 않는다
+    ships = {row["token"]: row for row in values.get("vessels", [])}
+    verdicts = {row["token"]: row for row in values.get("verdicts", [])}
     for cargo in values.get("cargos", []):
         facts, error = cargo.get("facts") or {}, cargo.get("error") or {}
+        cell = verdicts.get(cargo["token"])
+        more = (
+            {"ship": _ship(ships.get(cargo["token"])), "verdict": cell and _verdict(cell)}
+            if vessel and facts
+            else ({"ship": None, "verdict": None} if vessel else {})
+        )
         cargos.append(
             {
                 "number": unmask(cargo["token"], mask_map),
@@ -68,6 +144,7 @@ def screen_view(values: dict) -> dict:
                 "source": facts.get("source"),
                 "fetched_at": facts.get("fetched_at"),
                 "error": error.get("message"),
+                **more,
             }
         )
     evidence = [
@@ -83,7 +160,14 @@ def screen_view(values: dict) -> dict:
     return {"plan": _plan(values), "reading": reading, "cargos": cargos, "evidence": evidence}
 
 
-def interrupt_card(value: dict, mask_map: dict[str, str]) -> dict:
+def _fill(text: str, texts: dict[str, str]) -> str:
+    """선택 카드 글의 자리표를 후보의 이름과 설명으로 바꾼다."""
+    for key, value in texts.items():
+        text = text.replace(key, value)
+    return text
+
+
+def interrupt_card(value: dict, mask_map: dict[str, str], candidates: list[dict] | None = None) -> dict:
     """멈춘 이유(interrupt 값)를 화면 카드로 바꾼다: 선택지 카드 또는 승인 카드 (설계 6.3)."""
     if "action_requests" in value:
         # [왜] review_configs는 도구 이름마다 하나다(요청 순서가 아니다). 모르는 도구는 승인·거절만 연다
@@ -105,13 +189,38 @@ def interrupt_card(value: dict, mask_map: dict[str, str]) -> dict:
                 for request in value["action_requests"]
             ],
         }
+    texts = ship_texts(candidates or [])
     return {
         "kind": "choice",
         "question": unmask(value["question"], mask_map),
         "options": [
-            {"label": unmask(o["label"], mask_map), "description": unmask(o["description"], mask_map)}
+            {
+                "label": unmask(_fill(o["label"], texts), mask_map),
+                "description": unmask(_fill(o["description"], texts), mask_map),
+            }
             for o in value["options"]
         ],
         "recommended": value["recommended"],
         "timeout_s": load_rules("server")["question"]["timeout_s"],
     }
+
+
+def vessel_choice(typed: str, candidates: list[dict]) -> int:
+    """배 선택 카드에 직접 적은 글 → 선택 번호.
+
+    호출부호나 배 번호가 후보 한 척에만 들어 있으면 그 번호(1부터)다.
+
+    그 밖(맞는 후보가 없거나 둘 이상)은 0(모르겠어요)이다.
+    """
+    text = "".join(typed.split()).upper()
+    named = [
+        i
+        for i, ship in enumerate(candidates, 1)
+        if (ship["call_sign"] and "".join(ship["call_sign"].split()).upper() in text) or ship["mmsi"] in text
+    ]
+    return named[0] if len(named) == 1 else 0
+
+
+def is_vessel_card(value: dict) -> bool:
+    """멈춘 값이 배 선택 카드인가. 후보 선택지의 이름이 자리표({ship1}...)로 실려 있다."""
+    return any(str(o.get("label", "")).startswith("{ship") for o in value.get("options", []))
```

- [ ] **Step 3: 확인**: 명령 A. Expected: `1266 passed, 8 skipped`, 오류 0, 명령 B 셋 모두 깨끗함.

- [ ] **Step 4: 커밋**

```bash
git add rules/vessel.yaml src/marvia/server.py src/marvia/view.py tests/graph/test_vessel_screen.py
git commit -m "feat(server): 스위치가 켜져 있으면 화물 카드에 배와 판정 칸을 보임. 선택 카드는 자리표를 후보로 바꾸고 직접 적은 글은 번호로 바꿔 넘김"
```

### Task 7: 트레이스 가림이 받은 값 안의 배 값을 모아 가린다 (CB12, 결정 B15)

**배울 것:** 가림 함수는 값 하나만 받는 상태 없는 함수다. 다른 호출의 기억을 쓰면 다시 띄우거나 프로세스가 여럿일 때 구멍이 난다. 그래서 받은 값 안에서 가릴 값을 찾고 그 호출 안에서만 쓴다. 시험은 트레이서가 실제로 받는 값(span마다 따로)을 따로 넣어 본다. 한 덩어리로 넣으면 다른 값에서 찾은 이름으로 가려져 실제보다 잘 가려진 것처럼 보인다.

#### 커밋 7: feat(trace): 받은 값 안의 vessels·candidates에서 배의 이름·호출부호·배 번호를 모아 그 값 안에서 값으로 가림

**Files:**
- Modify/Create: `src/marvia/trace.py`
- Test: `tests/graph/test_vessel_step.py`

**Interfaces:**
- Consumes: `marvia.trace.scrub`, `MASK`, 콜백의 `on_chain_start`·`on_chain_end` 값.
- Produces: `scrub`이 받은 값 안의 `vessels`·`candidates`·`hits`와 MRN 호출부호(`mrn_call_sign`)에서 `name`, `call_sign`, `mmsi`(세 글자 이상)를 모아 그 호출 안에서 글에 든 그 값을 MASK로 바꾼다(긴 값부터). 모은 값은 컨텍스트 변수에 두고 호출이 끝나면 비운다.

호출부호와 배 이름은 번호 모양(8자 이상 덩어리) 규칙에 걸리지 않아 이 값 가림이 없으면 남는다. 검색 결과 전체(`hits`)와 MRN 호출부호는 질문 공책에 새로 생긴 값이라 이 커밋이 함께 가린다. 값을 모으는 곳이 없는 값(세관이 준 화물 사실의 `vessel_name`)은 가려지지 않는다(결정 B15의 남는 구멍).

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/graph/test_vessel_step.py
+++ b/tests/graph/test_vessel_step.py
@@ -4,6 +4,7 @@ import json
 from datetime import UTC, datetime
 
 import pytest
+from langchain_core.callbacks import BaseCallbackHandler
 from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
 from langchain_core.messages import AIMessage
 from langgraph.checkpoint.memory import InMemorySaver
@@ -545,3 +546,68 @@ def test_a_pick_is_checked_against_every_search_hit_not_only_the_ones_the_card_s
         "same_call_sign_many_mmsi",
         "partial",
     )
+
+
+class Recorder(BaseCallbackHandler):
+    """트레이서가 받는 값을 그대로 모은다: 노드마다의 입력과 출력, 따로따로."""
+
+    def __init__(self):
+        self.payloads: list = []
+
+    def on_chain_start(self, serialized, inputs, **kwargs):
+        self.payloads.append(inputs)
+
+    def on_chain_end(self, outputs, **kwargs):
+        self.payloads.append(outputs)
+
+
+def test_trace_scrub_hides_ships_the_step_met_inside_each_payload(agent_deps):
+    # [왜] Langfuse는 span마다 값을 따로 scrub에 넣는다. 한 덩어리로 넣으면 다른 값에서 찾은 배 이름
+    #      으로 가려져 실제보다 잘 가려진 것처럼 보인다. 값을 모으는 일도 받은 값 안에서만 한다
+    from marvia.trace import MASK, _ship_values, scrub
+
+    recorder = Recorder()
+    graph = graph_on(agent_deps)
+    config = {"configurable": {"thread_id": "tr"}, "callbacks": [recorder]}
+    graph.invoke({"text": "TESTVSL0002 어디쯤 왔어요?"}, config)  # 선택 카드에서 멈춘다
+    assert graph.get_state(config).interrupts
+    graph.invoke(Command(resume={"selected": 1}), config)  # 번호로 재개한다
+    graph.invoke({"text": "TESTVSL0001 어디쯤 왔어요?"}, {**config, "configurable": {"thread_id": "tr2"}})
+    raw = [json.dumps(p, ensure_ascii=False, default=str) for p in recorder.payloads]
+    ids = ("QQTST1", "QQTST3", "999000001", "999000002", "999000003")
+    assert any(s in text for text in raw for s in ids)  # 가리기 전에는 배의 값이 있다
+    for payload in recorder.payloads:
+        shown = json.dumps(scrub(payload), ensure_ascii=False, default=str)
+        for secret in (*ids, "26TEST0001I", "26TEST0009I", "TESTVSL0001", "TESTVSL0002"):
+            assert secret not in shown, (secret, shown[:200])
+        # 배 이름은 배 값(vessels, candidates)이 함께 든 값에서 가린다. 세관이 준 화물 사실의 vessel_name은
+        # 그 값 옆에 배 값이 없어 지금도 남는다(8b 전부터의 동작, 가림 규칙을 고치는 일은 이 계획 밖이다)
+        names: set[str] = set()
+        _ship_values(payload, names)
+        if names:
+            assert "TEST CARGO" not in json.dumps(scrub(payload), ensure_ascii=False, default=str)
+    assert any(MASK in json.dumps(scrub(p), ensure_ascii=False, default=str) for p in recorder.payloads)
+
+
+def test_scrub_is_stateless_and_only_hides_values_found_inside_what_it_is_given():
+    from marvia.trace import MASK, scrub
+
+    held = {
+        "vessels": [{"token": "[BL1]", "name": "TEST CARGO A", "call_sign": "QQTST1", "mmsi": "999000001"}]
+    }
+    assert scrub(held)["vessels"][0]["name"] == MASK and scrub(held)["vessels"][0]["call_sign"] == MASK
+    # 같은 글이라도 그 값 밖의 다른 값에서는 가리지 않는다(앞 호출의 기억이 남지 않는다)
+    other = {"note": "TEST CARGO A QQTST1"}
+    assert scrub(other) == other
+    # 후보 목록과 되묻는 값 안의 값도 모은다. 너무 짧은 값(세 글자 미만)은 다른 글을 지우므로 모으지 않는다
+    asked = {
+        "vessel_question": {"candidates": [{"name": "TEST CARGO C", "call_sign": "QQ", "mmsi": "999000004"}]}
+    }
+    out = scrub({**asked, "text": "TEST CARGO C QQ"})
+    assert out["text"] == f"{MASK} QQ"
+    # 검색 결과 전체(hits)와 MRN 호출부호(mrn_call_sign)도 모은다. 질문 값은 그 둘을 함께 든다
+    more = {
+        "vessel_question": {"hits": [{"mmsi": "999000020", "call_sign": "QQTWN"}], "mrn_call_sign": "QQMRN"}
+    }
+    out = scrub({**more, "text": "999000020 QQTWN QQMRN"})
+    assert out["text"] == f"{MASK} {MASK} {MASK}"
```

Run: `uv run pytest tests/graph/test_vessel_step.py -q`
Expected: `2 failed, 36 passed in 2.58s`. 실패하는 것: `test_trace_scrub_hides_ships_the_step_met_inside_each_payload`, `test_scrub_is_stateless_and_only_hides_values_found_inside_what_it_is_given`.

- [ ] **Step 2: 코드**

```diff
--- a/src/marvia/trace.py
+++ b/src/marvia/trace.py
@@ -16,6 +16,7 @@ tracer_callbacks: 그래프 실행 설정에 넣을 콜백. 서버·CLI·평가
 
 from __future__ import annotations
 
+import contextvars
 import dataclasses
 import functools
 from typing import Any
@@ -28,10 +29,42 @@ from marvia.config import Settings
 from marvia.identify.parse import find_spans
 
 MASK = "[가림]"
+# 지금 가리는 값 안에서 모은, 값으로 가릴 글(배 이름·호출부호·배 번호). scrub 한 번이 끝나면 비운다.
+# [왜] 이 값들은 번호 모양(8자 이상 덩어리)이 아니라 find_spans에 걸리지 않는다. 상태를 두지 않는다:
+#      받은 값 안에서 찾고 그 호출 안에서만 쓴다 (계획 8b). 비어 있으면 가림은 전과 같다
+_HIDDEN: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar("trace_hidden", default=())
+_MIN_HIDDEN = 3  # 이보다 짧은 값은 모으지 않는다. 두 글자 값은 다른 글을 군데군데 지운다
+_SHIP_KEYS = ("name", "call_sign", "mmsi")
+
+
+def _ship_values(value: Any, found: set[str], depth: int = 0) -> None:
+    """값 안(공책의 vessels, 후보 candidates, 검색 결과 hits, MRN 호출부호)에서 배의 값을 모은다."""
+    if depth > 8:
+        return
+    if isinstance(value, dict):
+        for key, item in value.items():
+            if key == "mrn_call_sign" and isinstance(item, str) and len(item) >= _MIN_HIDDEN:
+                found.add(item)
+            if key in ("vessels", "candidates", "hits") and isinstance(item, list):
+                for ship in item:
+                    if isinstance(ship, dict):
+                        found.update(
+                            v
+                            for k in _SHIP_KEYS
+                            if isinstance(v := ship.get(k), str) and len(v) >= _MIN_HIDDEN
+                        )
+            _ship_values(item, found, depth + 1)
+    elif isinstance(value, (list, tuple)):
+        for item in value:
+            _ship_values(item, found, depth + 1)
 
 
 def scrub_text(text: str) -> str:
-    """글 속 번호 후보 덩어리(identify.parse.find_spans와 같은 규칙)를 모두 MASK로 바꾼다."""
+    """글 속 번호 후보 덩어리(identify.parse.find_spans와 같은 규칙)와 값으로 가릴 글을 MASK로 바꾼다."""
+    for hidden in sorted(
+        _HIDDEN.get(), key=len, reverse=True
+    ):  # [왜] 긴 값부터: 짧은 값이 앞부분만 가리지 않게
+        text = text.replace(hidden, MASK)
     pieces: list[str] = []
     last = 0
     for span in find_spans(text):
@@ -45,7 +78,13 @@ def scrub(data: Any, **_: Any) -> Any:
 
     [왜] 인자 이름이 data이고 나머지 키워드는 받아 버린다. Langfuse 클라이언트가 mask(data=...)로 부른다.
     """
-    return _walk(data, set())
+    found: set[str] = set()
+    _ship_values(data, found)
+    token = _HIDDEN.set(tuple(found))
+    try:
+        return _walk(data, set())
+    finally:
+        _HIDDEN.reset(token)
 
 
 def _key(key: Any, taken: dict) -> Any:
```

- [ ] **Step 3: 확인**: 명령 A. Expected: `1268 passed, 8 skipped`, 오류 0, 명령 B 셋 모두 깨끗함.

- [ ] **Step 4: 커밋**

```bash
git add src/marvia/trace.py tests/graph/test_vessel_step.py
git commit -m "feat(trace): 받은 값 안의 vessels·candidates에서 배의 이름·호출부호·배 번호를 모아 그 값 안에서 값으로 가림"
```

### Task 8: 켜는 길은 서버 하나, 동작으로 고정한다 (CB2, 결정 B1)

**배울 것:** 깨 보아 살아남은 변이는 시험이 없는 곳이다. 글자 찾기는 `Settings().vessel`이나 `vessel=flag`를 지나간다. 켜는 길은 "실제로 만든 그래프"를 보고, 넘기는 곳은 코드 문법 트리로 센다.

#### 커밋 8: test(server): 환경에 스위치를 켜도 평가 실행기의 그래프에는 배 식별 단계가 없고, 스위치를 넘기는 곳은 서버와 가짜 API뿐임을 동작으로 고정

**Files:**
- Modify/Create: `e2e/fake_api.py`
- Test: `tests/graph/test_vessel_off.py`

**Interfaces:**
- Consumes: `evaluate_item`, `build_main_graph`, `ast`.
- Produces: 가짜 API(`e2e/fake_api.py`)가 `vessel=settings.vessel == "on"`으로 그래프를 짓고 판정 기준 시각을 고정한다(`now`). 시험 둘: 환경에 `MARVIA_VESSEL=on`을 넣고 평가 실행기(계획자·에이전트 길)가 만든 그래프에 `vessel` 노드가 없음, `build_main_graph`에 `vessel=`을 넘기는 파일은 `src/marvia/server.py`와 `e2e/fake_api.py`뿐임.

감시 재조회(`watch.py`, `scripts/recheck_watch.py`)는 메인 그래프를 만들지 않는다(조회 서브그래프만 쓴다). 그래서 "스위치를 넘기지 않는 진입점"에는 평가 실행기와 길 비교 스크립트, `try_agent`, `try_main`이 있고 문법 트리 시험이 그 전부를 본다.

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/graph/test_vessel_off.py
+++ b/tests/graph/test_vessel_off.py
@@ -8,8 +8,10 @@
 값이 달라지면 고치기 전에 무엇이 달라졌는지부터 본다.
 """
 
+import ast
 import hashlib
 import json
+from pathlib import Path
 
 from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
 from langchain_core.messages import AIMessage
@@ -124,3 +126,51 @@ def test_other_loops_and_the_trace_scrubber_are_unchanged_when_the_switch_is_off
         }
         assert not {"vessels", "verdicts", "vessel_question"} & set(values), loop
     assert _sha(seen) == LOOPS_SHA
+
+
+def test_the_eval_runner_builds_a_graph_without_the_vessel_step_even_when_the_env_asks_for_it(
+    agent_deps, monkeypatch
+):
+    # [왜] 11-13 판정. 켜는 길은 서버 하나다. 평가 실행기가 스위치를 환경에서 읽으면 측정이 달라진다.
+    #      환경에 MARVIA_VESSEL=on을 넣고 평가 실행기가 실제로 만든 그래프를 본다(글자 찾기가 아니라 동작)
+    from marvia.eval import run as eval_run
+    from marvia.eval.dataset import Item, load_set
+    from marvia.tools.rules import load_rules
+
+    monkeypatch.setenv("MARVIA_VESSEL", "on")
+    built = []
+    real = eval_run.build_main_graph
+    monkeypatch.setattr(
+        eval_run, "build_main_graph", lambda *a, **k: built.append(real(*a, **k)) or built[-1]
+    )
+    base = {"id": "T1", "group": "related", "kind": "시험", "behaviour": ["answer"]}
+    asked = Item.model_validate({**base, "question": "DEMO0001 언제까지 수입신고 해요?"})
+    for loop in ("planner", "agent"):
+        deps = agent_deps(model=ToolModel(messages=iter([AIMessage("끝")] * 5)))
+        eval_run.evaluate_item(deps, asked, loop, load_set().as_of, load_rules("pricing"))
+    assert len(built) == 2 and all("vessel" not in graph.nodes for graph in built)
+    # 서버 진입점만 스위치를 읽는다: build_main_graph를 부르며 vessel= 키워드를 넘기는 파일은 server.py뿐이다
+    root = Path(__file__).resolve().parents[2]
+    passing = []
+    for folder in ("src", "scripts", "e2e"):
+        for path in (root / folder).rglob("*.py"):
+            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
+                if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "build_main_graph":
+                    if any(keyword.arg == "vessel" for keyword in node.keywords):
+                        passing.append(
+                            (
+                                str(path.relative_to(root)),
+                                ast.unparse(next(k for k in node.keywords if k.arg == "vessel").value),
+                            )
+                        )
+    assert sorted(passing) == [
+        ("e2e/fake_api.py", "settings.vessel == 'on'"),
+        ("src/marvia/server.py", "settings.vessel == 'on'"),
+    ]
+
+
+def test_the_default_setting_is_off_and_compose_does_not_turn_it_on_for_the_runtime(monkeypatch):
+    from marvia.config import Settings
+
+    monkeypatch.delenv("MARVIA_VESSEL", raising=False)
+    assert Settings(_env_file=None).vessel == "off"  # type: ignore[call-arg]
```

Run: `uv run pytest tests/graph/test_vessel_off.py -q`
Expected: `1 failed, 5 passed in 2.24s`. 실패하는 것: `test_the_eval_runner_builds_a_graph_without_the_vessel_step_even_when_the_env_asks_for_it`.

- [ ] **Step 2: 코드**

```diff
--- a/e2e/fake_api.py
+++ b/e2e/fake_api.py
@@ -1,7 +1,8 @@
 """화면 e2e용 가짜 API (계획 4b Task 9). 실제 모델·Voyage·DB 없이 화면 서버(marvia.server)를 띄운다.
 
 질문 글로 각본을 고르는 가짜 모델, 가짜 RAG·조문 조회·작성자, 메모리 대화 기록으로 그래프를 만든다.
-UNI-PASS는 재생 데이터(DEMO 번호)다. 로그인은 개발 로그인(MARVIA_AUTH=dev)만 쓴다.
+UNI-PASS·해수부·ShipFinder는 재생 데이터(DEMO·TESTVSL 번호, QQ 호출부호)다.
+로그인은 개발 로그인(MARVIA_AUTH=dev)만 쓴다.
 [주의] 운영 이미지에는 이 파일이 들어가지 않는다(Dockerfile의 e2e 단계에만 복사한다). 바깥 호출 0건:
        Anthropic·Voyage 클라이언트를 만들지 않고, compose e2e 망은 바깥으로 나가지 못한다(internal).
 실행(컨테이너 안): python e2e/fake_api.py
@@ -11,7 +12,7 @@ from __future__ import annotations
 
 import os
 import time
-from datetime import date
+from datetime import UTC, date, datetime
 from typing import Any
 
 import uvicorn
@@ -127,12 +128,17 @@ def fake_deps() -> AgentDeps:
         write=write,
         model=ScriptModel(),
         provision=lambda label, as_of: [UNIT] if label == "관세법 제241조제3항" else [],
+        # [왜] 재생 배의 마지막 위치 수신(09-22 11:30) 30분 뒤로 고정한다. 판정과 그림이 날마다 같다 (계획 8b)
+        now=lambda: datetime(2026, 9, 22, 3, 0, tzinfo=UTC),
     )
 
 
 def main() -> None:
     settings = Settings()
-    graph = build_main_graph(fake_deps(), InMemorySaver(), loop="agent", store=InMemoryStore())
+    # [왜] 배 식별 화면은 MARVIA_VESSEL=on으로 띄웠을 때만 본다(compose의 E2E_VESSEL). 기본은 off다 (계획 8b)
+    graph = build_main_graph(
+        fake_deps(), InMemorySaver(), loop="agent", store=InMemoryStore(), vessel=settings.vessel == "on"
+    )
     app = build_app(graph, verifier(settings), web_origin=settings.web_origin, forget=lambda user: None)
     uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
 
```

- [ ] **Step 3: 확인**: 명령 A. Expected: `1270 passed, 8 skipped`, 오류 0, 명령 B 셋 모두 깨끗함.

- [ ] **Step 4: 커밋**

```bash
git add e2e/fake_api.py tests/graph/test_vessel_off.py
git commit -m "test(server): 환경에 스위치를 켜도 평가 실행기의 그래프에는 배 식별 단계가 없고, 스위치를 넘기는 곳은 서버와 가짜 API뿐임을 동작으로 고정"
```

### Task 9: 웹 화물 카드와 화면 시험 (CB14, 결정 B14, B18, B19)

**배울 것:** 화면 시험의 그림은 "기능을 켰을 때"와 "껐을 때"를 한 실행에 섞지 않는다. 켜는 값 하나(`E2E_VESSEL`)가 가짜 API와 시험 묶음을 함께 고르게 하면, 기본 실행의 그림이 그대로인지가 곧 꺼진 화면이 그대로인지다.

#### 커밋 9: feat(web): 화물 카드에 배와 판정 칸. 화면 시험은 E2E_VESSEL=on일 때 배 식별 흐름 다섯을 돌림

**Files:**
- Modify/Create: `.dockerignore`, `Dockerfile`, `docker-compose.yml`, `web/components/CargoCards.tsx`, `web/e2e/flows.spec.ts`, `web/lib/agui.ts`
- Test: `tests/test_docker.py`

**Interfaces:**
- Consumes: 화물 카드의 `ship`, `verdict` 칸(T6), 선택 카드(기존 `ChoiceCardView` 그대로), `AgentDeps.now`.
- Produces: `web/lib/agui.ts`의 `Ship`(상태에 `user_choice` 포함), `Verdict` 타입과 `Cargo.ship?`, `Cargo.verdict?`. `CargoCards`의 `VesselCells`. 화면 시험 "배 식별" 묶음(확정, 고르기, 같은 이름 둘, 모르겠어요, 내린 화물, 등급 없음)과 그림 `vessel-*.png`. compose의 `E2E_VESSEL`, e2e 이미지의 `fixtures/mof`, `fixtures/shipfinder`.

선택 카드 컴포넌트는 고치지 않는다. 같은 이름의 후보 둘은 버튼의 설명(호출부호, 배 번호, 서류로 본 결과)으로 갈린다.

이 커밋의 확인에는 아래가 더 있다. **이 문서를 쓸 때는 타입 검사까지만 돌렸다. 화면 시험 두 실행은 여기서 처음 돈다.**

```bash
cd web && npm ci && npx tsc --noEmit && cd ..
docker compose -p marvia-v2-e2e --profile e2e run --rm --build playwright      # 기존 흐름 통과, 배 식별 건너뜀
git status --short web/e2e/screenshots                       # 아무 줄도 없어야 한다(기존 그림 셋이 바이트까지 같다)
docker compose -p marvia-v2-e2e --profile e2e down
E2E_VESSEL=on docker compose -p marvia-v2-e2e --profile e2e run --rm --build playwright   # 배 식별 통과, 기존 건너뜀
docker compose -p marvia-v2-e2e --profile e2e down
```

기본 실행 뒤 그림이 달라졌으면 멈추고 무엇이 달라졌는지 본다(꺼진 화면이 바뀐 것이다). 켠 실행이 만든 그림 셋은 눈으로 본 뒤 이 커밋에 함께 넣는다. `web/tsconfig.tsbuildinfo`는 커밋에 넣지 않는다.

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/test_docker.py
+++ b/tests/test_docker.py
@@ -28,6 +28,8 @@ def test_the_build_context_is_an_allow_list_without_secrets_or_real_data():
         "fixtures/unipass",
         "corpus/graph",
         "e2e/fake_api.py",
+        "fixtures/mof",  # 배 식별 화면 시험의 재생 응답(가공값). e2e 이미지에만 복사한다 (계획 8b)
+        "fixtures/shipfinder",
     }
 
 
@@ -145,3 +147,17 @@ def test_local_web_servers_listen_on_loopback_and_the_e2e_image_does_not_run_as_
         if line.startswith("USER ")
     ]
     assert users[-1:] == ["pwuser"], users
+
+
+def test_vessel_screen_test_is_off_by_default_and_its_replay_data_stays_out_of_the_runtime_image():
+    # [왜] 배 식별 화면 시험은 E2E_VESSEL=on으로 부를 때만 켠다. 기본 실행의 화면과 그림은 그대로다 (계획 8b)
+    services = COMPOSE["services"]
+    assert services["api-e2e"]["environment"]["MARVIA_VESSEL"] == "${E2E_VESSEL:-off}"
+    assert services["playwright"]["environment"]["E2E_VESSEL"] == "${E2E_VESSEL:-off}"
+    assert all(
+        "MARVIA_VESSEL" not in (services[name].get("environment") or {}) for name in ("api", "prepare")
+    )
+    stages = re.split(r"(?m)^FROM ", (ROOT / "Dockerfile").read_text(encoding="utf-8"))
+    by_name = {stage.splitlines()[0].split()[-1]: stage for stage in stages[1:]}
+    assert "fixtures/mof" in by_name["e2e"] and "fixtures/shipfinder" in by_name["e2e"]
+    assert all("fixtures/mof" not in by_name[name] for name in ("build", "base", "runtime"))
```

Run: `uv run pytest tests/test_docker.py -q`
Expected: `2 failed, 6 passed in 5.54s`. 실패하는 것: `test_the_build_context_is_an_allow_list_without_secrets_or_real_data`, `test_vessel_screen_test_is_off_by_default_and_its_replay_data_stays_out_of_the_runtime_image`.

- [ ] **Step 2: 코드**

```diff
--- a/.dockerignore
+++ b/.dockerignore
@@ -8,6 +8,8 @@
 !prompts
 !migrations
 !fixtures/unipass
+!fixtures/mof
+!fixtures/shipfinder
 !corpus/graph
 !e2e/fake_api.py
 **/__pycache__
```
```diff
--- a/Dockerfile
+++ b/Dockerfile
@@ -36,6 +36,9 @@ HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=3 \
 
 FROM base AS e2e
 COPY e2e/fake_api.py /app/e2e/fake_api.py
+# [왜] 배 식별 화면 시험이 쓰는 재생 응답(가공값)이다. 운영 이미지에는 넣지 않는다 (계획 8b)
+COPY fixtures/mof /app/fixtures/mof
+COPY fixtures/shipfinder /app/fixtures/shipfinder
 CMD ["python", "/app/e2e/fake_api.py"]
 
 FROM base AS runtime
```
```diff
--- a/docker-compose.yml
+++ b/docker-compose.yml
@@ -90,6 +90,8 @@ services:
       MARVIA_AUTH: dev
       MARVIA_DEV_TOKEN: e2e-token # 시험용 값. 운영에 쓰지 않는다
       MARVIA_WEB_ORIGIN: http://web-e2e:3000
+      # 배 식별 화면 시험: E2E_VESSEL=on docker compose -p marvia-v2-e2e --profile e2e run --rm --build playwright (계획 8b)
+      MARVIA_VESSEL: ${E2E_VESSEL:-off}
     networks: [e2e]
   web-e2e:
     profiles: [e2e]
@@ -106,6 +108,7 @@ services:
     environment:
       E2E_BASE_URL: http://web-e2e:3000
       E2E_DEV_TOKEN: e2e-token
+      E2E_VESSEL: ${E2E_VESSEL:-off} # on이면 배 식별 흐름만, off면 기존 흐름만 돈다
     volumes:
       - ./web/e2e/screenshots:/work/e2e/screenshots # 스크린샷을 저장소에 남긴다
     depends_on:
```
```diff
--- a/web/components/CargoCards.tsx
+++ b/web/components/CargoCards.tsx
@@ -1,11 +1,60 @@
 // 화물 카드 (설계 10절): 통관 단계, 항구, 단계 시각, 출처와 조회 시각.
 // [왜] ETA·등급은 선박 위치 조회와 함께 2차로 미뤘다(계획 4b 결정 D3). 빈 칸 대신 그렇다고 적는다.
+// 서버의 배 식별 스위치가 켜져 있으면(verdict 칸이 오면) 그 자리에 배와 판정 칸을 보인다 (계획 8b).
+// [주의] 등급·일정·확신과 그 까닭은 서버가 보낸 글 그대로다. 화면이 등급을 정하거나 바꾸지 않는다.
 import type { Cargo } from "@/lib/agui";
 
 function when(value: string | null): string {
   return value ? new Date(value).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" }) : "모름";
 }
 
+function VesselCells({ c }: { c: Cargo }) {
+  const ship = c.ship;
+  const v = c.verdict;
+  const why = v ? [...v.signals, ...v.notes, ...v.info] : [];
+  return (
+    <>
+      <dt>배</dt>
+      <dd>
+        {ship?.name ?? "확인하지 못함"}
+        {ship?.mmsi ? ` (호출부호 ${ship.call_sign ?? "없음"} · 배 번호 ${ship.mmsi})` : ""}
+        {ship ? <span className="hint">{ship.reason}</span> : null}
+        {ship?.detail ? <span className="hint">{ship.detail}</span> : null}
+        {ship?.check ? <span className="hint">서류로 본 결과: {ship.check}</span> : null}
+      </dd>
+      {v ? (
+        <>
+          <dt>등급</dt>
+          <dd data-grade={v.grade ?? "none"}>{v.grade_label}</dd>
+          <dt>일정</dt>
+          <dd>{v.schedule}</dd>
+          <dt>확신</dt>
+          <dd>{v.confidence}</dd>
+          <dt>도착 예정</dt>
+          <dd>{v.eta ? `${when(v.eta)} (${v.eta_source ?? "출처 모름"})` : "모름"}</dd>
+          {why.length ? (
+            <>
+              <dt>까닭</dt>
+              <dd>
+                <ul>
+                  {why.map((line) => (
+                    <li key={line}>{line}</li>
+                  ))}
+                </ul>
+              </dd>
+            </>
+          ) : null}
+        </>
+      ) : ship?.status === "ask" ? (
+        <>
+          <dt>등급</dt>
+          <dd>배를 확인한 뒤에 보여 드려요</dd>
+        </>
+      ) : null}
+    </>
+  );
+}
+
 export function CargoCards({ cargos }: { cargos: Cargo[] }) {
   if (!cargos.length) return null;
   return (
@@ -24,8 +73,14 @@ export function CargoCards({ cargos }: { cargos: Cargo[] }) {
               <dd>{c.port ?? "모름"}</dd>
               <dt>단계 시각</dt>
               <dd>{when(c.stage_at)}</dd>
-              <dt>ETA·등급</dt>
-              <dd>선박 위치 조회 뒤(2차)</dd>
+              {c.verdict === undefined ? (
+                <>
+                  <dt>ETA·등급</dt>
+                  <dd>선박 위치 조회 뒤(2차)</dd>
+                </>
+              ) : (
+                <VesselCells c={c} />
+              )}
             </dl>
           )}
           <p className="meta">
```
```diff
--- a/web/e2e/flows.spec.ts
+++ b/web/e2e/flows.spec.ts
@@ -4,9 +4,13 @@ import AxeBuilder from "@axe-core/playwright";
 import { expect, type Page, test } from "@playwright/test";
 
 const TOKEN = process.env.E2E_DEV_TOKEN ?? "e2e-token";
+// 서버의 배 식별 스위치와 같은 값 (compose의 E2E_VESSEL, 계획 8b). off(기본)면 "배 식별" 묶음을 건너뛰고,
+// on이면 그 묶음만 돈다. [왜] 켜면 화물 카드에 칸이 늘어 기존 그림(answer.png)이 달라진다. 기존 흐름은 off에서만 찍는다
+const VESSEL = process.env.E2E_VESSEL === "on";
 const outside: string[] = [];
 
-test.beforeEach(async ({ page }) => {
+test.beforeEach(async ({ page }, testInfo) => {
+  test.skip(testInfo.titlePath.includes("배 식별") !== VESSEL, "E2E_VESSEL에 맞는 묶음만 돈다");
   // [왜] 화면이 모델·임베딩 공급자에 닿지 않는지 센다. 닿으면 막고 적는다 (바깥 호출 0건)
   await page.route(/(anthropic\.com|voyageai\.com)/, (route) => {
     outside.push(route.request().url());
@@ -34,6 +38,84 @@ async function accessible(page: Page) {
 
 const answers = (page: Page) => page.locator('.chat li[data-role="assistant"]');
 
+test.describe("배 식별", () => {
+  const card = (page: Page, number: string) => page.locator(".cargo", { has: page.getByRole("heading", { name: number }) });
+
+  test("배를 확정하면 화물 카드에 배와 판정 네 칸이 보인다", async ({ page }) => {
+    await ask(page, "TESTVSL0001 어디쯤 왔어요?");
+    await expect(answers(page)).toContainText("정리했어요");
+    const cargo = card(page, "TESTVSL0001");
+    await expect(cargo).toContainText("TEST CARGO A (호출부호 QQTST1 · 배 번호 999000001)");
+    await expect(cargo.locator("dd[data-grade]")).toHaveText("순항");
+    await expect(cargo).toContainText("일정 모름"); // 처음 알던 도착 예정을 받지 않아 지연을 보지 못했다
+    await expect(cargo).toContainText("처음 알던 도착 예정이 없어 지연은 보지 못했어요");
+    await expect(cargo).toContainText("판매 예정일을 받지 않아 여유 일수는 세지 않았어요");
+    await expect(cargo).toContainText("확실");
+    await expect(cargo).toContainText("해수부 입항 예정");
+    await expect(cargo).not.toContainText("선박 위치 조회 뒤(2차)");
+    await accessible(page);
+    await page.screenshot({ path: "e2e/screenshots/vessel-confirmed.png", fullPage: true, mask: [page.locator(".cargo .meta")] });
+  });
+
+  test("같은 이름의 배가 여럿이면 선택 카드로 묻고, 고른 배로 판정한다", async ({ page }) => {
+    await ask(page, "TESTVSL0002 어디쯤 왔어요?");
+    await expect(page.getByRole("heading", { name: /TESTVSL0002 화물을 실은 배를 가리지 못했어요/ })).toBeVisible();
+    await expect(page.getByRole("button", { name: /모르겠어요 \(권장\)/ })).toBeVisible();
+    await expect(card(page, "TESTVSL0002")).toContainText("배를 확인한 뒤에 보여 드려요");
+    // 선택지의 이름과 설명은 서버가 자리표를 후보로 바꿔 채운다. 서류로 본 결과가 함께 보인다
+    await expect(page.getByRole("button", { name: /호출부호 QQTST1 · 배 번호 999000001/ })).toContainText("MRN)로 찾은 입항 신고가 없어 서류로 확정하지 않았어요");
+    await expect(page.locator(".card")).not.toContainText("{ship");
+    await accessible(page);
+    await page.screenshot({ path: "e2e/screenshots/vessel-choice.png", fullPage: true, mask: [page.locator(".cargo .meta")] });
+    await page.getByRole("button", { name: /배 번호 999000001/ }).click();
+    await expect(answers(page)).toContainText("정리했어요");
+    await expect(card(page, "TESTVSL0002")).toContainText("고르신 배로 봤어요");
+    await expect(card(page, "TESTVSL0002").locator("dd[data-grade]")).toHaveText("순항");
+    await expect(card(page, "TESTVSL0002")).toContainText("호출부호를 맞춰 보지 못해 확신을 부분으로 낮췄어요");
+  });
+
+  test("호출부호가 같은 두 배는 자동 확정하지 않고, 고르면 확신이 부분이다", async ({ page }) => {
+    await ask(page, "TESTVSL0007 어디쯤 왔어요?");
+    await expect(page.getByRole("heading", { name: /TESTVSL0007 화물을 실은 배를 가리지 못했어요/ })).toBeVisible();
+    await expect(page.getByRole("button", { name: /배 번호 999000007/ })).toContainText("같은 호출부호의 배가 여럿이에요");
+    await page.getByRole("button", { name: /배 번호 999000008/ }).click();
+    await expect(answers(page)).toContainText("정리했어요");
+    const cargo = card(page, "TESTVSL0007");
+    await expect(cargo).toContainText("고르신 배로 봤어요");
+    await expect(cargo).not.toContainText("확신 확실");
+  });
+
+  test("모르겠다고 하면 배 없이 진행하고 등급을 지어내지 않는다", async ({ page }) => {
+    await ask(page, "TESTVSL0002 어디쯤 왔어요?");
+    await page.getByRole("button", { name: /모르겠어요 \(권장\)/ }).click();
+    await expect(answers(page)).toContainText("정리했어요");
+    const cargo = card(page, "TESTVSL0002");
+    await expect(cargo).toContainText("배를 모른다고 하셔서 배 없이 진행했어요");
+    await expect(cargo.locator("dd[data-grade]")).toHaveText("등급 없음");
+  });
+
+  test("배에서 내린 화물은 배 위치를 보지 않았다고 말한다", async ({ page }) => {
+    await ask(page, "TESTVSL0006 어디쯤 왔어요?");
+    await expect(answers(page)).toContainText("정리했어요");
+    const cargo = card(page, "TESTVSL0006");
+    await expect(cargo).toContainText("배에서 내린 화물이라 배 위치는 보지 않았어요");
+    await expect(cargo.locator("dd[data-grade]")).toHaveText("순항");
+    await expect(cargo).not.toContainText("도착 예정");
+  });
+
+  test("배를 찾지 못하면 '등급 없음'과 그 까닭을 보인다", async ({ page }) => {
+    await ask(page, "TESTVSL0003 어디쯤 왔어요?");
+    await expect(answers(page)).toContainText("정리했어요");
+    const cargo = card(page, "TESTVSL0003");
+    await expect(cargo).toContainText("배 후보를 찾지 못했어요");
+    await expect(cargo.locator("dd[data-grade]")).toHaveText("등급 없음");
+    await expect(cargo).toContainText("도착 시각을 알 출처가 없어 등급을 내지 않았어요");
+    await accessible(page);
+    await page.screenshot({ path: "e2e/screenshots/vessel-no-grade.png", fullPage: true, mask: [page.locator(".cargo .meta")] });
+  });
+});
+
+// 아래 기존 흐름은 스위치가 꺼진 서버에서만 돈다. 그림(answer·choice·approval.png)이 계획 8b 전과 같아야 한다
 test("질문하면 계획이 답보다 먼저 보이고, 답·근거·화물 카드가 뜬다", async ({ page }) => {
   await ask(page, "DEMO0001 언제까지 수입신고 해야 해요?");
   // 가짜 검색이 2초 늦다. 그동안 진행 중인 할 일이 보이고 답은 아직 없다 (실시간 계획)
```
```diff
--- a/web/lib/agui.ts
+++ b/web/lib/agui.ts
@@ -14,6 +14,32 @@ export type Cargo = {
   source: string | null;
   fetched_at: string | null;
   error: string | null;
+  // 아래 두 칸은 서버의 배 식별 스위치(MARVIA_VESSEL)가 켜졌을 때만 온다 (계획 8b). 없으면 카드가 그대로다
+  ship?: Ship | null; // 스위치가 꺼진 서버는 이 칸을 보내지 않는다(undefined)
+  verdict?: Verdict | null;
+};
+// 배 확인 결과. 글은 서버 규칙(rules/vessel.yaml)이 정한다
+export type Ship = {
+  status: "confirmed" | "user_choice" | "ask" | "none" | "unknown";
+  reason: string; // 서버 규칙(rules/vessel.yaml)이 정한 글
+  detail: string | null; // 조회 서비스의 정한 오류 글(한도 소진과 일시 실패가 갈린다)
+  check: string | null; // 사용자가 고른 배를 서류로 맞춰 본 결과
+  name: string | null;
+  call_sign: string | null;
+  mmsi: string | null;
+};
+// 판정 칸. 등급·일정·확신은 서버 코드가 냈다. grade가 null이면 grade_label은 "등급 없음"이다
+export type Verdict = {
+  grade: "fine" | "watch" | "alert" | "act" | null;
+  grade_label: string;
+  confidence: string;
+  schedule: string;
+  eta: string | null;
+  eta_source: string | null;
+  margin_days: number | null;
+  signals: string[];
+  notes: string[];
+  info: string[];
 };
 export type EvidenceUnit = {
   unit_id: string;
```

- [ ] **Step 3: 확인**: 명령 A. Expected: `1271 passed, 8 skipped`, 오류 0, 명령 B 셋 모두 깨끗함.

- [ ] **Step 4: 커밋**

```bash
git add .dockerignore Dockerfile docker-compose.yml web/components/CargoCards.tsx web/e2e/flows.spec.ts web/lib/agui.ts tests/test_docker.py
git commit -m "feat(web): 화물 카드에 배와 판정 칸. 화면 시험은 E2E_VESSEL=on일 때 배 식별 흐름 다섯을 돌림"
```

### Task 10: 문서

**배울 것:** 코드가 바뀌면 "아직 연결 전"이라고 적은 주석부터 거짓이 된다. 연결한 커밋이 그 글을 함께 고친다.

#### 커밋 10: docs: 배 추적 모듈의 '아직 연결 전' 주석을 배 식별 단계 연결로 고치고 README와 설계에 스위치 뒤의 화물 카드 칸을 적음

**Files:**
- Modify/Create: `README.md`, `docs/specs/2026-10-28-marvia-v2-design.md`, `src/marvia/tools/judge.py`, `src/marvia/tools/mof.py`, `src/marvia/tools/shipfinder.py`, `src/marvia/tools/vessel_match.py`
- Test: `tests/graph/test_vessel_off.py`

**Interfaces:**
- Produces: 없음(주석과 문서 글만). `README.md`의 배 추적 줄, 설계 10절의 화물 카드 줄과 변경 기록 한 줄, 8a 네 모듈(`judge`, `mof`, `shipfinder`, `vessel_match`) 머리의 "연결 전" 주석, `test_vessel_off.py` 머리말.

명령 A의 수는 T9와 같다. 두 문서 파일에 em dash가 없는지 본다: `grep -c $'\u2014' README.md docs/specs/2026-10-28-marvia-v2-design.md` → 둘 다 `0`.

- [ ] **Step 1: 실패하는 시험**

```diff
--- a/tests/graph/test_vessel_off.py
+++ b/tests/graph/test_vessel_off.py
@@ -4,7 +4,7 @@
 계획 8b는 그 가운데 다섯 파일(graph/main.py, graph/state.py, server.py, view.py, trace.py)을 고친다.
 그 다섯은 해시 묶음에서 빼고 여기서 "스위치가 꺼져 있으면 동작이 같다"로 묶는다.
 나머지 파일은 해시 묶음에 그대로 남는다.
-아래 값은 계획 8b의 첫 코드 커밋 전(a632dff, 다섯 파일은 48ca3c5와 같다)에 낸 값이다.
+아래 값은 계획 8b의 첫 코드 커밋 전 상태(ad17004와 같은 코드, 다섯 파일은 48ca3c5와 같다)에서 낸 값이다.
 값이 달라지면 고치기 전에 무엇이 달라졌는지부터 본다.
 """
 
```

Run: `uv run pytest tests/graph/test_vessel_off.py -q`
Expected: `6 passed in 2.01s`. 지금 상태를 묶는 시험이라 처음부터 통과한다.

- [ ] **Step 2: 코드**

```diff
--- a/README.md
+++ b/README.md
@@ -100,7 +100,8 @@ v1(B/L 하나로 순항·주의·긴급 판정)은 태그 `v1-final`에 있다.
 - 배포: 손으로 시작하는 워크플로와 절차서([`docs/deploy.md`](docs/deploy.md))까지 준비했고 이미지·compose는 이 컴퓨터에서 확인했다. Cloud Run, Vercel, Supabase, AuraDB에는 아직 올리지 않았고 실제 Supabase 로그인도 보지 않았다.
 - 지난 시점의 법령 고르기: 코퍼스는 문서마다 현행판 하나라 "그 시점에 유효한 법령"을 고르는 동작은 없고 재지도 않았다. 설계의 목표로 남는다.
 - 계획 3b 측정: GraphRAG 켜고 끈 비교는 첫 시도에서 API 계정 잔액이 떨어져(스스로 정한 상한과 따로) 채점된 문항이 없었다. 충전 뒤 사전 등록 규칙대로 재고, 그때까지 그래프는 꺼 둔다.
-- 선박명·항차로 화물 찾기와 선박 위치(화물 카드의 ETA·등급)는 2차로 미뤘다.
+- 배 추적: 화물을 식별한 뒤 실은 배를 코드가 찾아 확정하거나 선택 카드로 되묻고, 화물 카드에 판정 네 칸과 믿을 ETA, 등급이 없을 때의 까닭을 보인다(계획 8a, 8b). 스위치 `MARVIA_VESSEL=on`일 때만 돌고 기본은 꺼져 있다. 자동 확정은 MRN으로 얻은 호출부호가 후보와 같거나, 호출부호가 없을 때 입항일·적재항이 둘 다 맞을 때뿐이다(후자는 확신이 많아야 부분). 배에서 내린 단계의 화물은 배를 보지 않는다. 모델은 배와 판정을 보지 않으므로 답 글에는 아직 나오지 않는다. 해수부와 ShipFinder의 실제 응답, 부산 밖 항만, 키의 유효 여부는 확인하지 못했다(재생 데이터만). 판매 예정일과 처음 알던 도착 예정을 받는 통로가 없어 여유 일수로 오르는 등급과 일정 칸은 나오지 않는다.
+- 선박명·항차로 화물 찾기는 2차로 미뤘다.
 - 화면은 가짜 모델로만 시험했다.
 
 ## 어떻게 만들고 통제했나 (초안)
```
```diff
--- a/docs/specs/2026-10-28-marvia-v2-design.md
+++ b/docs/specs/2026-10-28-marvia-v2-design.md
@@ -295,6 +295,7 @@ UNI-PASS 같은 외부 조회 호출은 타임아웃, 재시도 2회, 실패하
 - Next.js(App Router). AG-UI 이벤트를 받아 그린다.
 - 구성: 채팅 / 계획 진행(할 일 목록과 현재 단계) / "이렇게 읽었어요" 표시 / 선택지 카드 / 승인 카드 / 답변과 근거 패널(조문 원문, 시행일, 출처 링크) / 화물 카드(통관 단계, ETA, 등급).
 - 로그인: Supabase Auth. 사용자 id로 thread와 Store를 나눈다.
+- 화물 카드의 배와 판정 (11-15, 계획 8b): 스위치 `MARVIA_VESSEL=on`이면 화물 조회 뒤에 배 식별 단계(vessel, ask_vessel, verdict)가 돌고 화물 카드에 배(이름, 호출부호, 배 번호, 확인한 까닭)와 판정(등급, 일정, 확신, 믿을 ETA와 출처, 까닭)이 보인다. 가르지 못하면 선택 카드로 묻고 권장안은 "배 없이 진행"이다. 배에서 내린 단계의 화물은 배를 조회하지 않는다. 이 값들은 모델을 거치지 않는다.
 - 구현 (11-07, 계획 4b): 서버는 ag-ui-langgraph 어댑터 없이 `ag-ui-protocol` 1.0.0의 이벤트로 `POST /agui` 하나를 직접 쓴다(어댑터는 화면이 보낸 메시지·state를 그래프 입력에 합치고 공책 전체를 보낸다). 받는 값은 마지막 사용자 글과 재개 값뿐이고, 보내는 값은 허용 목록(할 일, 읽은 번호, 화물 카드, 근거 패널, 카드)뿐이다. 사용자는 서명을 확인한 토큰(ES256, 공개키 목록 JWKS)과 소유자 목록에서만 꺼내고, 대화 키는 서버가 "사용자/이름"으로 만든다. 토큰은 aud·iss·exp·sub가 모두 있어야 하고 시계 차이는 30초까지 봐주며, 공개키 목록 받기는 5초에 끊고, Supabase 주소는 https여야 서버가 뜬다. 목록 밖 사용자는 403, 그 밖의 실패는 사유 글 없이 401이다. 서버는 마지막 사용자 메시지 하나만 읽고(그 메시지가 사용자 글이 아니면 422), 선택지 번호는 멈춘 카드의 선택지 안에서만 받고(밖이면 422), 취소한 카드는 payload를 읽지 않고 권장안(승인 카드는 거절)으로 간다. 지난 카드 id로 재개하거나 답하는 중인 대화에 또 보내면 409다. 409 본문은 서버가 정한 글이고 화면은 그 글을 그대로 보이며, 지난 카드(`code: stale_card`)일 때만 카드를 치운다(11-08, 계획 6c). 화면이 정하는 대화 id의 길이 상한은 `rules/server.yaml`의 `request.max_thread_id`(64)다. 서버는 `MARVIA_HOST`(기본 127.0.0.1)에서 듣고, 컨테이너만 0.0.0.0으로 연다. 같은 대화 잠금이 프로세스 안에서만 지켜지므로 Cloud Run은 인스턴스 하나로 배포한다(`--max-instances 1`, 늘릴 때는 thread 키에 `pg_try_advisory_lock`, R-073). 화면은 Next.js 16 한 쪽이고 SSE를 `fetch`로 읽는다(CopilotKit·`@ag-ui/client` 없이). 화물 카드의 ETA·등급은 선박 위치 조회와 함께 2차로 미루고 카드에 그렇게 적는다. 승인 카드에서 고친 값과 거절 글은 서버가 그 대화의 가림 표로 다시 가린 뒤 재개한다. 고친 인자는 JSON 글로 모델에 가므로 키와 숫자 값까지 번호 검사를 하고, 대화에 없던 번호가 하나라도 있으면 실행하지 않고 정해 둔 거절로 바꾼다. 승인 카드 글은 도구 이름 대신 한국어 이름(`rules/agent.yaml`의 `approval.labels`)을 쓴다. 바깥으로 메시지를 보내는 도구는 만들지 않았다(보낼 통로가 없고 6.3에서 2차로 둔 일이다). 주요 흐름 넷과 접근성(axe)은 공식 Playwright 이미지 안에서 가짜 모델로 시험한다. 11-08(계획 6c): 409 안내, 계정 삭제(확인에 초점, 지운 뒤 대화를 비움, 401이면 로그아웃) 흐름을 더했고, Playwright 이미지는 root가 아닌 `pwuser`로 돈다
 
 ## 11. 평가와 관측
@@ -403,3 +404,4 @@ UNI-PASS 같은 외부 조회 호출은 타임아웃, 재시도 2회, 실패하
 - 11-08: 계획 6b. Langfuse 트레이스 연결(기본 꺼짐, 네 겹 가림, `LANGFUSE_*` 시작 거절) (11절, 12절, 15절)
 - 11-08: 계획 6c. 지난 검토에서 넘긴 고침: 계정 삭제 중 409, 409 안내와 카드, 대화 id 상한 규칙, 로컬 화면 127.0.0.1·e2e pwuser, 계정 삭제 화면, 같은 번호 다시 조회 안 함과 중복 빼기, 식별 질문 글 규칙, ② JSON 가림, Langfuse 주소 거절, 컨테이너 카드 화면 (4.1, 4.2, 6.3, 8, 10, 11, 13절)
 - 11-08: 계획 5. 만든 에이전트가 하는 일(1절), 작업 방식을 실제로 한 방식으로(2절 결정 12), 검토 방법과 측정 뒤 바뀐 도구 설명(11절), 계획별 실제 날짜(14절)
+- 11-15: 10절에 화물 카드의 배와 판정 칸(스위치 뒤)을 계획 8b 기준으로 더함.
```
```diff
--- a/src/marvia/tools/judge.py
+++ b/src/marvia/tools/judge.py
@@ -3,8 +3,8 @@
 하지 않는 일: 바깥 조회, 배 고르기, 답 글. 등급·확신·일정은 tools/verdict.py가, 신호는
 tools/signals.py가 정한다.
 여기는 그 둘을 잇고, 항만 값이나 조회 결과가 없을 때 "판정을 미루지 않고 확신을 낮추며 이유를 적는" 일만 한다.
-[주의] 아직 그래프의 어느 노드도 이 함수를 부르지 않는다. 연결은 다음 계획이다
-       (tests/test_vessel_base_not_wired.py).
+[주의] 그래프에서는 배 식별 단계(graph/vessel.py)만 부른다. MARVIA_VESSEL=on일 때만 돈다 (계획 8b).
+       다른 파일이 부르면 tests/test_vessel_base_not_wired.py가 막는다.
 """
 
 from __future__ import annotations
```
```diff
--- a/src/marvia/tools/mof.py
+++ b/src/marvia/tools/mof.py
@@ -7,7 +7,7 @@
 [주의] 응답의 배 이름·시설 이름·MRN은 바깥에서 온 값이다. MRN은 화물 번호처럼 다룬다(모델·로그에 넣지 않는다).
 [주의] 실제 응답으로 확인하지 않았다(키와 실제 호출은 직접 할 일). 응답 모양은 v1 코드와 가공 fixture다.
        부산 밖 청코드의 응답이 같은 모양인지도 확인하지 못했다.
-[주의] 아직 그래프의 어느 노드도 이 모듈을 부르지 않는다. 연결은 다음 계획이다.
+[주의] 그래프에서는 배 식별 단계(graph/vessel.py)만 부른다. MARVIA_VESSEL=on일 때만 돈다 (계획 8b).
 """
 
 from __future__ import annotations
```
```diff
--- a/src/marvia/tools/shipfinder.py
+++ b/src/marvia/tools/shipfinder.py
@@ -6,7 +6,7 @@
 [주의] 요청 주소에 키(key)가 들어간다. 주소·예외 글·바깥 응답 글을 로그·오류 글·LLM에 넣지 않는다.
 [주의] 응답의 배 이름과 목적지 글(dest)은 바깥에서 온 자유 글이다. 목적지 글은 코드 밖으로 내보내지 않는다.
 [주의] 실제 응답으로 확인하지 않았다(키와 실제 호출은 직접 할 일). 응답 모양은 v1 코드와 가공 fixture다.
-[주의] 아직 그래프의 어느 노드도 이 모듈을 부르지 않는다. 연결은 다음 계획이다.
+[주의] 그래프에서는 배 식별 단계(graph/vessel.py)만 부른다. MARVIA_VESSEL=on일 때만 돈다 (계획 8b).
 """
 
 from __future__ import annotations
```
```diff
--- a/src/marvia/tools/vessel_match.py
+++ b/src/marvia/tools/vessel_match.py
@@ -5,7 +5,7 @@ v1 backend/app/services/judge/identify.py match_by_papers와 routers/agent.py _i
 코드 판단을 옮겼다. v1이 되묻기 답을 받은 뒤 LLM에게 고르게 하던 길은 옮기지 않았다(11-13 결정).
 [왜] 배 이름·배 신호의 목적지·위치는 "어느 배가 내 화물을 실었나"의 근거가 아니다. v1에서 근거 없이
      고르게 했더니 남의 배를 확정했다(평가 문항 B01, B12). 틀린 배를 확정하는 것보다 되묻는 쪽이 낫다.
-[주의] 아직 그래프의 어느 노드도 이 함수를 부르지 않는다. 연결은 다음 계획이다.
+[주의] 그래프에서는 배 식별 단계(graph/vessel.py)만 부른다. MARVIA_VESSEL=on일 때만 돈다 (계획 8b).
 """
 
 from __future__ import annotations
```

- [ ] **Step 3: 확인**: 명령 A. Expected: `1271 passed, 8 skipped`, 오류 0, 명령 B 셋 모두 깨끗함.

- [ ] **Step 4: 커밋**

```bash
git add README.md docs/specs/2026-10-28-marvia-v2-design.md src/marvia/tools/judge.py src/marvia/tools/mof.py src/marvia/tools/shipfinder.py src/marvia/tools/vessel_match.py tests/graph/test_vessel_off.py
git commit -m "docs: 배 추적 모듈의 '아직 연결 전' 주석을 배 식별 단계 연결로 고치고 README와 설계에 스위치 뒤의 화물 카드 칸을 적음"
```

---

## 끝나면 되는 것

- `MARVIA_VESSEL`을 주지 않으면 그래프, 평가 줄, 화면이 지금과 같다(`tests/graph/test_vessel_off.py`, 화면 시험의 기본 실행과 그림 셋이 바이트까지 같음).
- `MARVIA_VESSEL=on`으로 띄운 서버에서 재생 화물 `TESTVSL0001`을 물으면 화물 카드에 배(TEST CARGO A, 호출부호, 배 번호, 맞춰 본 칸)와 판정(순항, 확실, 일정 모름), 믿을 ETA와 그 출처, 참고 글이 보인다. `TESTVSL0002`는 선택 카드가 뜨고 후보마다 서류로 본 결과가 보이며, 고르면 "고르신 배로 봤어요"로(확신은 부분), "모르겠어요"나 시간 초과면 배 없이 진행한다. `TESTVSL0003`은 "등급 없음"과 까닭이 보인다. `TESTVSL0006`은 "배에서 내린 화물이라 배 위치는 보지 않았어요"가 보이고 바깥 조회가 없다.
- 모델이 보는 것(지시문, 도구 목록과 설명, 화물 줄, 작성자 입력의 화물 부분)은 스위치와 무관하게 그대로다. 시간 초과로 넘어간 차례에만 가정 한 줄(이름표와 정한 글)이 작성자 입력에 더해진다.
- 판정 평가 문항 118개와 배 확정 문항 22개가 모두 통과한다(이 부분은 문항을 더하지 않는다. A부분이 고정했다).

## 설계와 대조

| 설계 | 이 계획 | 남은 것 |
|---|---|---|
| 2절 결정 3: 숫자·등급은 코드, LLM이 고르지 않는다 | 배 찾기, 되묻기 답 처리, 판정, 확신 상한 모두 코드 (T4, T5) | |
| 2절 결정 4: 선택지 2~3개, 권장안 맨 앞, 답이 없으면 권장안으로 진행하고 가정으로 남김 | 선택 카드 셋(권장 "모르겠어요"), 시간 초과·취소는 가정 한 줄 (T5) | |
| 2절 결정 13: 판정 네 칸 | 화물 카드에 등급·단계·일정·확신. 일정 칸은 처음 알던 예정이 있을 때만 (T5, T6, T9) | 답 글에 판정을 쓰기(8c) |
| 4.1 ②: 가르지 못하면 후보 제시 | 같은 이름의 배 후보를 선택 카드로. 한 척도 근거가 없으면 묻는다 (T4, T5) | 항차·포워더 입항 예정일로 좁히기 |
| 4.2: MRN으로 배를 특정 | `plans_near` + `plan_by_mrn`, 호출부호가 글자까지 같을 때 확정 (T4) | |
| 4.3: `CargoIdentity.vessel`, `candidates` | 손대지 않았다. 배는 공책의 `vessels` 칸에 따로 둔다 | 식별 결과 모델에 합칠지(8c) |
| 6.3: 질문 통로, 재개 | 기존 선택 카드와 `Command(resume=...)` 그대로. 서버의 재개 검사도 그대로이고 직접 입력은 서버가 번호로 바꿔 넘긴다 | |
| 7.1: 판정 | 배를 보는 단계만 배 신호를 쓰고, 입항한 배는 ETA 어긋남을 해당 없음으로 둔다 (A부분) | 실제 단계 이름 확인 |
| 7.2: `vessel_position`, `port_schedule` | verdict 노드가 부른다. 에이전트 도구로 등록하지는 않았다 | 도구로 등록(8c) |
| 10절: 화물 카드(통관 단계, ETA, 등급) | 스위치가 켜지면 "ETA·등급: 선박 위치 조회 뒤(2차)" 자리에 배와 판정 칸 | 등급 색, 지도 |
| 12절: 실제 번호는 가린다, 도구 응답은 데이터 | 배 식별자와 MRN은 모델에 가지 않고, 목적지 원문은 어디에도 없다. 끼어들기 값에는 자리표만 싣는다 (CB12) | 배 식별자를 모델에 줄지와 그때의 이름표(8c) |

## 확인하지 못한 것

| 무엇 | 왜 못 했나 | 직접 할 일 |
|---|---|---|
| 화면 시험(Playwright) 두 실행과 새 그림 넷, `next build` | 이 문서를 쓸 때 Docker를 띄우지 않았다. 타입 검사와, 가짜 API 그래프를 프로세스 안에서 돌려 화면 시험이 기대하는 글이 스냅샷에 나오는 것까지만 봤다 | T9의 확인에서 두 실행을 돌리고 `git status --short web/e2e/screenshots`가 비었는지(기존 그림 셋이 같은지) 본다. 켠 실행이 만든 그림 셋은 눈으로 본 뒤 넣는다 |
| 화물 카드의 새 칸이 화면에서 읽기 좋은지(줄 길이, 까닭 목록의 모양) | 화면을 띄워 보지 않았다. 새 CSS는 넣지 않았다(기존 `dl`, `.hint` 모양을 쓴다) | `E2E_VESSEL=on` 실행의 그림 넷을 눈으로 본다 |
| 해수부·ShipFinder의 실제 응답으로 이 단계가 도는지 | 실제 호출은 하지 않았다(8a와 같다). 재생 데이터만 | 키와 `live`는 주인이 정할 일. 부산 화물 한 건으로 켜 본다 |
| 해수부 입항 신고 조회가 기간을 무엇으로 거르는지(입항 예정일, 신고일 등)와 실제 쪽 수 | 실제 호출을 하지 않았다. 쪽 수 8은 v1 실측(부산 5일치 12쪽)에서 셈한 [추정]이다 | 부산 화물 한 건으로 `plans_near`와 `port_schedule`의 쪽 수와 기간 적용을 본다. 맞으면 `rules/vessel.yaml max_mrn_pages`를 고친다 |
| 실제 UNI-PASS 응답에서 MRN, 양륙항 코드, 입항일, 적재항이 얼마나 비는지 | 실제 호출을 하지 않았다. MRN이 비면 배 이름 검색으로 떨어져 되묻는 일이 늘고, 양륙항 코드가 비면 서류 대조를 하지 못한다 | UNI-PASS 실제 조회 확인 때 함께 |
| 실제 통관 단계 이름과 "배를 보는 단계"의 경계 | 단계 이름은 8a와 같이 확인하지 못했다 | UNI-PASS 확인 때 `rules/verdict.yaml ship_stages`, `known_stages`를 맞춘다 |
| Postgres 대화 저장소에서 새 공책 칸 셋과 자리표를 실은 끼어들기 값의 저장·재개, 암호화 직렬화기 통과 | 새 시험은 메모리 저장소만 쓴다. 칸의 값은 글·수·목록·dict뿐이라 기존 칸(`cargos`)과 같은 길을 지날 것으로 본다 [추정] | 스위치를 켠 서버를 개발 DB에 붙여 선택 카드에서 한 번 재개해 본다 |
| 시험용 Neo4j를 켠 전체 시험 | 사본에서는 꺼 둔 채 돌렸다(8개 건너뜀). 이 계획은 그래프 검색을 건드리지 않는다 | 커밋 때 한 번 |
| 수퍼바이저 길과 계획자 길에서 스위치를 켠 한 차례 | 켠 시험은 에이전트 길만 돈다. 노드 셋은 길과 무관하게 같은 자리에 붙고, 꺼진 모양과 한 차례는 길 셋 모두 묶었다 | 필요하면 `graph_on`에 `loop`을 넘겨 한 번씩 |
| 가림의 남는 구멍 | 화물 사실의 `vessel_name`(8b 전부터), 사용자 글에 직접 적은 배 이름, 대화 저장소의 평문 | 가리려면 `trace.py`에 열쇠 이름 기준을 더하는 일이고 꺼진 동작도 바꾼다(이 계획 밖) |

## 정할 것과 권고

| 무엇 | 지금 계획의 값 | 권고 |
|---|---|---|
| 판매 예정일과 처음 알던 도착 예정을 어디서 받아 판정에 넘길지 | 받는 통로가 없다. 카드가 그렇다고 말한다(결정 7, 15) | 8c에서 품목 사실 뽑기와 함께. 그때 "지연", 여유 일수 등급이 열린다 |
| 틀린 확정과 "모르겠어요"를 되돌리는 길 | 없다. 그 대화 안에서는 다시 묻지 않는다(결정 13) | 8c에서 "배를 다시 찾아 줘"를 도구로 받는다 |
| 쪽 수 상한 8이 실제 응답에서 맞는지 | [추정] 8(결정 12) | 실제 응답을 한 번 본 뒤 정한다. 모자라면 MRN 길이 `too_many`로 끝나 되묻는다(지어내지 않는다) |
| 서류와 어긋난 후보를 카드에서 숨길지 | 보이고 "서류로 본 결과"를 적는다 | 그대로. 숨기면 사용자가 왜 후보가 줄었는지 모른다 |
| 확정한 배를 장기 기억이나 감시 표에 저장할지 | 저장하지 않는다. 그 대화의 공책에만 둔다(결정 13) | 이 계획에서는 그대로. 감시 표에 넣는다면 암호화 칸, 계정 삭제 때 지우기, 감시 재조회의 ShipFinder 한도를 함께 정하는 따로 된 계획으로 |
| 화물 사실의 `vessel_name`을 트레이스에서 가릴지 | 가리지 않는다(8b 전부터의 동작) | 받아들인다. 가리면 꺼진 동작이 바뀐다 |

## 다음 계획이 정할 것

- 판매 예정일, 포워더가 알려 준 날, 처음 알던 도착 예정을 어디서 받아 판정에 넘길지(지금은 넘기지 않는다).
- 판정 칸과 배를 답 글에 쓸지, 쓴다면 작성자와 검증자가 코드 값을 어떻게 받는지. 배 식별자를 모델에 줄지와 이름표.
- 조회 도구를 에이전트 도구 목록에 더할지(루프 안에서 새로 찾은 화물의 배, "배를 다시 찾아 줘", 틀린 확정 되돌리기).
- 평가에서 배 식별을 볼 문항과 실행기의 스위치.
- 위치 이력 모으기와 감시 재조회에서 배 보기.
