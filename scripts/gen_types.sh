#!/usr/bin/env sh
# scripts/gen_types.sh 은 backend/app/schemas/ 의 Pydantic 모델에서
# frontend/lib/api-types.ts 를 만든다.
#
#   bash scripts/gen_types.sh          # 생성·덮어쓰기
#   bash scripts/gen_types.sh --check  # CI용. 결과가 현재 파일과 다르면 exit 1
#
# 같은 입력이면 항상 같은 출력이다(선언 순서·이름 정렬·포맷 고정).
# 외부 호출 없이 로컬 pydantic 만으로 돈다. PYTHON 환경변수로 파이썬을 바꿀 수 있다.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT="$ROOT/frontend/lib/api-types.ts"
PYTHONBIN="${PYTHON:-python3}"
CHECK=0

if [ "${1:-}" = "--check" ]; then
  CHECK=1
elif [ $# -gt 0 ]; then
  echo "usage: bash scripts/gen_types.sh [--check]" >&2
  exit 2
fi

TMP=$(mktemp "${TMPDIR:-/tmp}/api-types.XXXXXX")
trap 'rm -f "$TMP"' EXIT INT TERM

"$PYTHONBIN" - "$ROOT" > "$TMP" <<'PYEOF'
import datetime
import json
import sys
import types
import typing
from typing import Any

sys.path.insert(0, sys.argv[1])

from pydantic import BaseModel

import backend.app.schemas.slots as m_slots
import backend.app.schemas.result as m_result
import backend.app.schemas.request as m_request
import backend.app.schemas.session as m_session

MODULES = [m_slots, m_result, m_request, m_session]
ROOTS = ["AgentRequest", "AgentResponse", "Slots", "Result", "ParticipantInput",
         "ParticipantPatchRequest", "ParticipantPatchResponse", "GeocodedPin", "SessionRead"]
UNION_ORIGINS = {typing.Union, types.UnionType}

all_models: dict[str, type[BaseModel]] = {}
for _mod in MODULES:
    for _name in dir(_mod):
        _obj = getattr(_mod, _name)
        if isinstance(_obj, type) and issubclass(_obj, BaseModel) and _obj is not BaseModel:
            all_models.setdefault(_name, _obj)

aliases: dict[str, list[str]] = {}
alias_objs: dict[int, str] = {}
for _mod in MODULES:
    for _name in sorted(vars(_mod)):
        if _name.startswith("_"):
            continue
        _obj = vars(_mod)[_name]
        if typing.get_origin(_obj) is typing.Literal:
            aliases[_name] = [str(_v) for _v in typing.get_args(_obj)]
            alias_objs[id(_obj)] = _name


def _q(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def ts_of(ann: object) -> str:
    if ann is None or ann is type(None):
        return "null"
    if ann is Any:
        return "any"
    if ann is str:
        return "string"
    if ann is bool:
        return "boolean"
    if ann is int or ann is float:
        return "number"
    if ann is datetime.datetime or ann is datetime.date:
        return "string"
    if id(ann) in alias_objs:
        return alias_objs[id(ann)]
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        return ann.__name__
    origin = typing.get_origin(ann)
    if origin is typing.Literal:
        return " | ".join(_q(v) for v in typing.get_args(ann))
    if origin is list:
        (elem,) = typing.get_args(ann)
        return ts_of(elem) + "[]"
    if origin is tuple:
        return "[" + ", ".join(ts_of(a) for a in typing.get_args(ann)) + "]"
    if origin is dict:
        key_t, val_t = typing.get_args(ann)
        return "Record<" + ts_of(key_t) + ", " + ts_of(val_t) + ">"
    if origin in UNION_ORIGINS:
        return " | ".join(ts_of(a) for a in typing.get_args(ann))
    raise TypeError("unmapped annotation: %r" % (ann,))


def own_fields(model: type[BaseModel]) -> list[str]:
    inherited: set[str] = set()
    for base in model.__mro__[1:]:
        if isinstance(base, type) and issubclass(base, BaseModel) and base is not BaseModel:
            inherited.update(base.model_fields)
    return [n for n in model.model_fields if n not in inherited]


lines: list[str] = []
lines.append("// 생성물이다. 손으로 고치지않는다. 고치려면 backend/app/schemas/ 를 고치고 이 스크립트를 다시 돌린다")
lines.append("// scripts/gen_types.sh 가 backend/app/schemas/ 의 Pydantic 모델에서 만듦. API 키 없이 돈다.")
lines.append("")
for _name in sorted(aliases):
    lines.append("export type %s = %s;" % (_name, " | ".join(_q(v) for v in aliases[_name])))
    lines.append("")
ordered = [n for n in ROOTS if n in all_models]
ordered += sorted(n for n in all_models if n not in set(ROOTS))
for _name in ordered:
    _model = all_models[_name]
    _bases = [b.__name__ for b in _model.__mro__[1:]
              if isinstance(b, type) and issubclass(b, BaseModel) and b is not BaseModel
              and b.__name__ in all_models]
    lines.append("export interface %s" % _name + (" extends " + ", ".join(_bases) if _bases else "") + " {")
    for _fname in own_fields(_model):
        lines.append("  %s: %s;" % (_fname, ts_of(_model.model_fields[_fname].annotation)))
    lines.append("}")
    lines.append("")

sys.stdout.write("\n".join(lines))
PYEOF

if [ "$CHECK" -eq 1 ]; then
  if [ ! -f "$OUT" ]; then
    echo "gen_types.sh --check: $OUT 없음" >&2
    exit 1
  fi
  if cmp -s "$TMP" "$OUT"; then
    echo "gen_types.sh --check: 일치"
  else
    echo "gen_types.sh --check: 다름. bash scripts/gen_types.sh 로 다시 생성" >&2
    if command -v diff >/dev/null 2>&1; then
      diff -u "$OUT" "$TMP" || true
    fi
    exit 1
  fi
else
  mkdir -p "$(dirname -- "$OUT")"
  mv -f "$TMP" "$OUT"
  echo "gen_types.sh: $OUT 기록"
fi
