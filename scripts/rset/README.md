# 검색 전용 평가셋을 만든 스크립트

`eval/rset_*.yaml`의 머리말이 말하는 "스크립트로 뽑았다"의 그 스크립트다. 모두 고정 시드로 뽑고 정답은 코드가 정한다.
다시 돌리면 `eval/`에 둔 파일과 글자까지 같은 파일이 나온다(시험 `tests/eval/test_rset_build.py`가 본다).

| 평가셋 | 스크립트(순서대로) | 시드 | 필요한 것 |
|---|---|---|---|
| rset_v1 | `build_rset.py sample` → (질문 쓰기) → `build_rset.py write` → `apply_fixes.py` | 1112 | corpus/units |
| rset_a2 | `build_rset_a2.py` | 1113 | rset_v1 |
| rset_a3, rset_b2 | `build_round2.py sample` → (질문 쓰기) → `build_round2.py write` → `apply_fixes_b2.py` | 1114 | rset_v1, rset_a2 |
| rset_a4 | `build_rset_a4.py` | 1115 | 앞의 네 파일, 로컬 DB(조문 안 단위 순서를 읽는다) |

## 스크립트로 다시 나오지 않는 단계

층 b·c(rset_v1)와 rset_b2의 질문은 모델(sonnet)이 정답 본문만 보고 썼다. 이 단계는 다시 돌려도 같은 글이 나오지 않으므로
입력과 출력을 `eval/rset_build/`에 그대로 둔다.

| 파일 | 무엇 |
|---|---|
| `sample.json`, `b2_sample.json` | `sample` 단계가 뽑은 표본(정답 단위 포함) |
| `for_writer.json`, `b2_for_writer.json` | 질문을 쓰는 쪽에 준 것: 문항 번호와 본문뿐이다. 정답 단위 이름과 검색 결과는 주지 않았다 |
| `questions.json`, `b2_questions.json` | 받은 질문. `write` 단계가 표본과 합친다 |

정답 독립 확인에서 나온 고침(정답 좁힘, also_ok, 질문 고침)은 `apply_fixes.py`와 `apply_fixes_b2.py`에 목록으로 적혀 있다.

## 다시 만들기

    W=<작업 폴더>; mkdir -p $W/set $W/v1 $W/b2
    uv run python scripts/rset/build_rset.py sample $W/v1
    cp eval/rset_build/questions.json $W/v1/
    uv run python scripts/rset/build_rset.py write $W/v1 $W/v1/draft.yaml
    uv run python scripts/rset/apply_fixes.py $W/v1/draft.yaml $W/set/rset_v1.yaml
    uv run python scripts/rset/build_rset_a2.py $W/set/rset_v1.yaml $W/set/rset_a2.yaml
    uv run python scripts/rset/build_round2.py sample $W/set $W/b2
    cp eval/rset_build/b2_questions.json $W/b2/
    uv run python scripts/rset/build_round2.py write $W/set $W/b2
    mv $W/set/rset_b2.yaml $W/b2/draft.yaml
    uv run python scripts/rset/apply_fixes_b2.py $W/b2/draft.yaml $W/set/rset_b2.yaml
    uv run python scripts/rset/build_rset_a4.py $W/set $W/set/rset_a4.yaml
