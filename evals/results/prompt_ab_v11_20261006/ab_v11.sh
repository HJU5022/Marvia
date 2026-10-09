#!/bin/zsh
# V11 프롬프트 전후 비교: Vertex gemini-3.5-flash-lite, 해설 채점 끔, OpenRouter·Langfuse 키 비움.
# 4문항(N04 N05 N06 B06) x 5회 x 10프로세스 = 200번씩, 수정 전 -> 프롬프트 교체 -> 수정 후.
S=${S:?임시 작업 폴더 경로를 S로 넘긴다}
E=$S/marvia_334f255
PY=.venv/bin/python
export LLM_MODEL=vertex/google/gemini-3.5-flash-lite EVAL_GRADER_MODEL= OPENROUTER_API_KEY= LANGFUSE_PUBLIC_KEY= LANGFUSE_SECRET_KEY=
cd $E

phase() {  # $1 = 결과 폴더 이름
  OUT=$S/$1; rm -rf $OUT; mkdir -p $OUT
  # 첫 묶음 1번을 먼저 돌려 Vertex가 되는지 본다 (따로 확인 호출 없이 이것이 확인)
  $PY -m evals.run_eval --config b --only N04 N05 N06 B06 > $OUT/run_0.txt 2>&1
  if ! grep -q "LLM 실패 종류 -" $OUT/run_0.txt || [ $(grep -cE "^  [NB]0[0-9]  " $OUT/run_0.txt) -lt 4 ]; then
    echo "STOP $1: 첫 묶음 이상"; grep -E "LLM 실패 종류|Traceback|Error" $OUT/run_0.txt | head -5; exit 1
  fi
  echo "ok first batch $1"
  for p in $(seq 1 10); do
    ( for i in $(seq 1 5); do n=$((p*10+i)); [ $n -le 105 ] || continue
        $PY -m evals.run_eval --config b --only N04 N05 N06 B06 > $OUT/run_$n.txt 2>&1; done ) &
  done
  wait
  echo "done $1 files=$(ls $OUT | wc -l | tr -d ' ') llm_fail_lines=$(grep -h 'LLM 실패 종류' $OUT/*.txt | grep -vc 'LLM 실패 종류 -$')"
}

phase v11_vertex_before
cp $S/prompts_v2/marvia-judge.md $S/prompts_v2/marvia-follow-up.md $E/backend/app/prompts/
echo "prompts swapped"
phase v11_vertex_after
echo ALL_DONE
