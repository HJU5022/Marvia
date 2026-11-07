"use client";
// 선택지 카드 (설계 6.3 질문 통로): 선택지, "기타" 직접 입력, 권장안으로 진행, 시간이 지나면 권장안으로 진행.
import { useEffect, useRef, useState } from "react";

import type { ChoiceCard } from "@/lib/agui";

type Reply = { selected: number } | { custom: string } | { timeout: true };

export function ChoiceCardView({ card, onReply }: { card: ChoiceCard; onReply: (reply: Reply) => void }) {
  const [custom, setCustom] = useState("");
  const [left, setLeft] = useState(card.timeout_s);
  const box = useRef<HTMLElement>(null);

  // 새 카드가 뜨면 초점을 옮긴다. 키보드·화면 낭독 사용자가 시간 제한 안에 카드를 찾게 한다
  useEffect(() => box.current?.focus(), []);

  // [왜] 그래프에는 시간 제한이 없다. 화면이 시간을 재고 {"timeout": true}로 재개한다(설계 6.3)
  useEffect(() => {
    if (left <= 0) {
      onReply({ timeout: true });
      return;
    }
    const timer = setTimeout(() => setLeft(left - 1), 1000);
    return () => clearTimeout(timer);
  }, [left, onReply]);

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
        <input id="choice-custom" value={custom} onChange={(e) => setCustom(e.target.value)} />
        <button type="button" disabled={!custom.trim()} onClick={() => onReply({ custom: custom.trim() })}>
          보내기
        </button>
      </div>
      <button type="button" className="secondary" onClick={() => onReply({ timeout: true })}>
        권장안으로 진행 ({left}초 뒤 자동)
      </button>
    </section>
  );
}
