"use client";
// 선택지 카드 (설계 6.3 질문 통로): 선택지, "기타" 직접 입력, 권장안으로 진행, 시간이 지나면 권장안으로 진행.
import { useEffect, useRef, useState } from "react";

import type { ChoiceCard } from "@/lib/agui";

type Reply = { selected: number } | { custom: string } | { timeout: true };

export function ChoiceCardView({ card, onReply }: { card: ChoiceCard; onReply: (reply: Reply) => void }) {
  const [custom, setCustom] = useState("");
  const [left, setLeft] = useState(card.timeout_s);
  const [focused, setFocused] = useState(false);
  const box = useRef<HTMLElement>(null);
  const latest = useRef(onReply);
  latest.current = onReply;
  // [왜] 직접 입력하는 동안은 시간을 멈춘다. 쓰던 답이 권장안으로 바뀌지 않게 한다
  const paused = focused || custom !== "";

  // 새 카드가 뜨면 초점을 옮긴다. 키보드·화면 낭독 사용자가 시간 제한 안에 카드를 찾게 한다
  useEffect(() => box.current?.focus(), []);

  // [왜] 그래프에는 시간 제한이 없다. 화면이 시간을 재고 {"timeout": true}로 재개한다(설계 6.3)
  useEffect(() => {
    if (paused) return;
    if (left <= 0) {
      latest.current({ timeout: true }); // 한 번만 보낸다. 실패하면 아래 버튼으로 다시 한다
      return;
    }
    const timer = setTimeout(() => setLeft(left - 1), 1000);
    return () => clearTimeout(timer);
  }, [left, paused]);

  return (
    <section ref={box} tabIndex={-1} aria-labelledby="choice-title" className="card">
      <h2 id="choice-title">{card.question}</h2>
      <div className="options">
        {card.options.map((option, i) => (
          <button key={i} type="button" onClick={() => onReply({ selected: i })}>
            {option.label}
            {i === card.recommended ? " (권장)" : ""}
            <span className="hint">{option.description}</span>
          </button>
        ))}
      </div>
      <label htmlFor="choice-custom">기타 (직접 입력)</label>
      <div className="row">
        <input
          id="choice-custom"
          value={custom}
          onChange={(e) => setCustom(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
        />
        <button type="button" disabled={!custom.trim()} onClick={() => onReply({ custom: custom.trim() })}>
          보내기
        </button>
      </div>
      <button type="button" className="secondary" onClick={() => onReply({ timeout: true })}>
        권장안으로 진행 ({paused ? "입력하는 동안 멈춤" : `${left}초 뒤 자동`})
      </button>
    </section>
  );
}
