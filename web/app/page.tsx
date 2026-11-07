"use client";
// Marvia 화면 한 쪽 (설계 10절): 채팅, 계획 진행, 이렇게 읽었어요, 선택지·승인 카드, 답과 근거, 화물 카드.
// 상태는 서버가 보낸 STATE_SNAPSHOT(허용 목록)과 답 글뿐이다. 서버에 state를 보내지 않는다.
import { useCallback, useEffect, useState } from "react";

import { ApprovalCardView } from "@/components/ApprovalCardView";
import { ChoiceCardView } from "@/components/ChoiceCardView";
import { EvidencePanel, PlanList, ReadingList } from "@/components/Panels";
import { type AgUiEvent, type Card, EMPTY_VIEW, newId, runTurn, type View } from "@/lib/agui";
import { AUTH_MODE, currentToken, signIn, signOut } from "@/lib/auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";
type Line = { role: "user" | "assistant"; text: string };

export default function Home() {
  const [token, setToken] = useState<string | null>(null);
  const [devToken, setDevToken] = useState("");
  const [threadId] = useState(newId);
  const [lines, setLines] = useState<Line[]>([]);
  const [view, setView] = useState<View>(EMPTY_VIEW);
  const [card, setCard] = useState<Card | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    currentToken().then(setToken);
  }, []);

  const onEvent = useCallback((event: AgUiEvent) => {
    if (event.type === "STATE_SNAPSHOT") setView(event.snapshot);
    if (event.type === "TEXT_MESSAGE_CONTENT") setLines((old) => [...old, { role: "assistant", text: event.delta }]);
    if (event.type === "RUN_ERROR") setError(event.message);
    if (event.type === "RUN_FINISHED" && event.outcome?.type === "interrupt") {
      const pending = event.outcome.interrupts[0];
      setCard({ ...pending.metadata, id: pending.id });
    }
  }, []);

  const turn = useCallback(
    async (input: { text?: string; resume?: { interruptId: string; payload: unknown } }) => {
      if (!token) return;
      setBusy(true);
      setError("");
      setCard(null);
      try {
        await runTurn(API_URL, token, { threadId, ...input }, onEvent);
      } catch (failure) {
        setError(failure instanceof Error ? failure.message : "요청이 실패했어요");
      } finally {
        setBusy(false);
      }
    },
    [token, threadId, onEvent],
  );

  function send() {
    const text = draft.trim();
    if (!text || busy) return;
    setLines((old) => [...old, { role: "user", text }]);
    setDraft("");
    turn({ text });
  }

  const reply = useCallback(
    (payload: unknown) => {
      if (card) turn({ resume: { interruptId: card.id, payload } });
    },
    [card, turn],
  );

  if (!token) {
    return (
      <main>
        <h1>Marvia</h1>
        {AUTH_MODE === "dev" ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              signIn(devToken).then(() => currentToken().then(setToken));
            }}
          >
            <label htmlFor="dev-token">개발 로그인 토큰</label>
            <div className="row">
              <input id="dev-token" type="password" value={devToken} onChange={(e) => setDevToken(e.target.value)} />
              <button type="submit">들어가기</button>
            </div>
          </form>
        ) : (
          <button type="button" onClick={() => signIn()}>
            구글로 로그인
          </button>
        )}
      </main>
    );
  }

  return (
    <main>
      <header className="row">
        <h1>Marvia</h1>
        <button type="button" className="secondary" onClick={() => signOut().then(() => setToken(null))}>
          로그아웃
        </button>
      </header>
      <section aria-labelledby="chat-title" className="panel">
        <h2 id="chat-title">대화</h2>
        <ol className="chat">
          {lines.map((line, i) => (
            <li key={i} data-role={line.role}>
              <span className="who">{line.role === "user" ? "나" : "Marvia"}</span>
              <p className="text">{line.text}</p>
            </li>
          ))}
        </ol>
        <p role="status" aria-live="polite" className="meta">
          {busy ? "답하는 중이에요" : ""}
        </p>
        {error ? <p role="alert">{error}</p> : null}
      </section>
      {card?.kind === "choice" ? <ChoiceCardView key={card.id} card={card} onReply={reply} /> : null}
      {card?.kind === "approval" ? <ApprovalCardView key={card.id} card={card} onReply={reply} /> : null}
      <PlanList plan={view.plan} />
      <ReadingList reading={view.reading} />
      <EvidencePanel evidence={view.evidence} />
      <form
        className="ask"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <label htmlFor="question">질문이나 화물 단서 (B/L·화물관리번호)</label>
        <textarea
          id="question"
          rows={3}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            // [주의] 한글 조합 중 Enter는 글자를 확정하는 키다. 그때 보내면 마지막 글자가 남거나 두 번 간다
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button type="submit" disabled={busy || !draft.trim()}>
          보내기
        </button>
      </form>
    </main>
  );
}
