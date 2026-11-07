"use client";
// 승인 카드 (설계 6.3 승인 통로): 할 일마다 승인·거절·고치기. 고치기는 도구별 칸만 연다.
// [왜] 자유 JSON 편집을 열면 모르는 인자가 그대로 도구에 간다. 서버가 고친 값을 다시 가리고 도구가 같은 검사를 한다
import { useState } from "react";

import type { ApprovalCard } from "@/lib/agui";

type Decision =
  | { type: "approve" }
  | { type: "reject"; message: string }
  | { type: "edit"; edited_action: { name: string; args: Record<string, unknown> } };

// 고칠 수 있는 도구와 칸. 모르는 도구는 승인·거절만 보인다
const EDITABLE: Record<string, { field: string; label: string; choices?: string[] }> = {
  save_preference: { field: "depth", label: "설명 깊이", choices: ["짧게", "보통", "자세히"] },
  save_item_card: { field: "name", label: "품목 이름" },
};

export function ApprovalCardView({
  card,
  onReply,
}: {
  card: ApprovalCard;
  onReply: (reply: { decisions: Decision[] }) => void;
}) {
  const [kinds, setKinds] = useState(card.actions.map(() => "approve"));
  const [values, setValues] = useState(card.actions.map((a) => String(a.args[EDITABLE[a.name]?.field] ?? "")));
  const [reasons, setReasons] = useState(card.actions.map(() => ""));
  const set = (list: string[], i: number, value: string) => list.map((old, j) => (j === i ? value : old));

  function send() {
    const decisions = card.actions.map((action, i): Decision => {
      if (kinds[i] === "reject") return { type: "reject", message: reasons[i] || "사용자가 거절했어요" };
      if (kinds[i] === "edit") {
        const field = EDITABLE[action.name].field;
        return { type: "edit", edited_action: { name: action.name, args: { ...action.args, [field]: values[i] } } };
      }
      return { type: "approve" };
    });
    onReply({ decisions });
  }

  return (
    <section aria-labelledby="approval-title" className="card">
      <h2 id="approval-title">승인이 필요해요</h2>
      {card.actions.map((action, i) => {
        const edit = EDITABLE[action.name] && action.allowed.includes("edit") ? EDITABLE[action.name] : null;
        return (
          <fieldset key={i}>
            <legend>{action.name}</legend>
            <p className="text">{action.description}</p>
            <label>
              <input type="radio" name={`d${i}`} checked={kinds[i] === "approve"} onChange={() => setKinds(set(kinds, i, "approve"))} />
              승인
            </label>
            <label>
              <input type="radio" name={`d${i}`} checked={kinds[i] === "reject"} onChange={() => setKinds(set(kinds, i, "reject"))} />
              거절
            </label>
            {edit ? (
              <label>
                <input type="radio" name={`d${i}`} checked={kinds[i] === "edit"} onChange={() => setKinds(set(kinds, i, "edit"))} />
                고치기
              </label>
            ) : null}
            {kinds[i] === "reject" ? (
              <label className="block">
                거절 이유 (선택)
                <input value={reasons[i]} onChange={(e) => setReasons(set(reasons, i, e.target.value))} />
              </label>
            ) : null}
            {edit && kinds[i] === "edit" ? (
              <label className="block">
                {edit.label}
                {edit.choices ? (
                  <select value={values[i]} onChange={(e) => setValues(set(values, i, e.target.value))}>
                    {edit.choices.map((choice) => (
                      <option key={choice}>{choice}</option>
                    ))}
                  </select>
                ) : (
                  <input value={values[i]} onChange={(e) => setValues(set(values, i, e.target.value))} />
                )}
              </label>
            ) : null}
          </fieldset>
        );
      })}
      <button type="button" onClick={send}>
        보내기
      </button>
    </section>
  );
}
