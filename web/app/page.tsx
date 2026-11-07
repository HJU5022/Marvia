"use client";
// Marvia 화면 한 쪽 (설계 10절): 채팅, 계획 진행, 이렇게 읽었어요, 선택지·승인 카드, 답과 근거, 화물 카드.
// 상태는 서버가 보낸 STATE_SNAPSHOT(허용 목록)과 답 글뿐이다. 서버에 state를 보내지 않는다.
import { useCallback, useEffect, useRef, useState } from "react";

import { ApprovalCardView } from "@/components/ApprovalCardView";
import { CargoCards } from "@/components/CargoCards";
import { ChoiceCardView } from "@/components/ChoiceCardView";
import { EvidencePanel, PlanList, ReadingList } from "@/components/Panels";
import { type AgUiEvent, type Card, deleteAccount, EMPTY_VIEW, HttpError, newId, runTurn, type View } from "@/lib/agui";
import { AUTH_MODE, currentToken, signIn, signOut } from "@/lib/auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";
type Line = { role: "user" | "assistant"; text: string; id?: string };

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
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const running = useRef<AbortController | null>(null);
  const sending = useRef(false); // [왜] busy는 상태라 빠른 두 번 입력 사이에 아직 안 바뀐다

  // 화면을 떠나면 진행 중인 차례를 멈춘다
  useEffect(() => () => running.current?.abort(), []);

  useEffect(() => {
    currentToken().then(setToken);
  }, []);

  const onEvent = useCallback((event: AgUiEvent) => {
    // [왜] 카드는 이어받은 차례의 첫 이벤트가 올 때 치운다. 연결이 실패하면 카드가 남아 다시 할 수 있다
    if (event.type === "RUN_STARTED") setCard(null);
    if (event.type === "STATE_SNAPSHOT") setView(event.snapshot);
    if (event.type === "TEXT_MESSAGE_CONTENT") {
      // 같은 messageId의 조각은 한 줄에 이어 붙인다
      setLines((old) =>
        old.some((l) => l.id === event.messageId)
          ? old.map((l) => (l.id === event.messageId ? { ...l, text: l.text + event.delta } : l))
          : [...old, { role: "assistant", text: event.delta, id: event.messageId }],
      );
    }
    if (event.type === "RUN_ERROR") setError(event.message);
    if (event.type === "RUN_FINISHED" && event.outcome?.type === "interrupt") {
      const pending = event.outcome.interrupts[0];
      setCard({ ...pending.metadata, id: pending.id });
    }
  }, []);

  const turn = useCallback(
    async (input: { text?: string; resume?: { interruptId: string; payload: unknown } }) => {
      if (!token || sending.current) return;
      sending.current = true;
      setBusy(true);
      setError("");
      // [왜] 토큰은 차례마다 새로 받는다. Supabase는 만료 직전이면 갱신한 토큰을 주므로 1시간 뒤에도 로그인이 이어진다
      const fresh = await currentToken();
      if (!fresh) {
        sending.current = false;
        setBusy(false);
        setToken(null);
        setError("다시 로그인해 주세요");
        return;
      }
      running.current?.abort();
      const controller = new AbortController();
      running.current = controller;
      try {
        await runTurn(API_URL, fresh, { threadId, ...input }, onEvent, controller.signal);
      } catch (failure) {
        if (controller.signal.aborted) return; // 멈춘 차례는 아무것도 보이지 않는다
        // [왜] fetch가 연결 실패로 던지는 TypeError는 영어 글이다. 정해 둔 한글로 바꾼다
        setError(
          failure instanceof Error && !(failure instanceof TypeError)
            ? failure.message
            : "서버에 닿지 못했어요. 잠시 뒤 다시 해 주세요",
        );
        // [왜] 카드는 서버가 지난 카드라고 할 때(stale_card)만 치운다. 답하는 중·계정 삭제 중(409)과
        //      422는 카드가 아직 살아 있어 다시 보낼 수 있다
        if (failure instanceof HttpError && failure.code === "stale_card") setCard(null);
        if (failure instanceof HttpError && failure.status === 401) signOut().then(() => setToken(null));
      } finally {
        sending.current = false;
        if (running.current === controller) setBusy(false);
      }
    },
    [token, threadId, onEvent],
  );

  function send() {
    const text = draft.trim();
    if (!text || busy || sending.current) return;
    setLines((old) => [...old, { role: "user", text }]);
    setDraft("");
    turn({ text });
  }

  async function removeAccount() {
    setConfirmingDelete(false);
    const fresh = await currentToken();
    if (!fresh) return setToken(null);
    try {
      await deleteAccount(API_URL, fresh);
      running.current?.abort();
      await signOut();
      setToken(null);
      setError("계정을 지웠어요. 대화 기록과 저장한 값이 모두 지워졌어요");
    } catch (failure) {
      setError(
        failure instanceof HttpError && failure.status === 409
          ? "답하는 중인 대화가 있어요. 끝난 뒤 다시 눌러 주세요"
          : failure instanceof HttpError
            ? failure.message
            : "서버에 닿지 못했어요. 잠시 뒤 다시 해 주세요",
      );
    }
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
        {error ? <p role="alert">{error}</p> : null}
        {AUTH_MODE === "dev" ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              signIn(devToken)
                .then(() => currentToken().then(setToken))
                .catch((failure: Error) => setError(failure.message));
            }}
          >
            <label htmlFor="dev-token">개발 로그인 토큰</label>
            <div className="row">
              <input id="dev-token" type="password" value={devToken} onChange={(e) => setDevToken(e.target.value)} />
              <button type="submit">들어가기</button>
            </div>
          </form>
        ) : (
          <button type="button" onClick={() => signIn().catch((failure: Error) => setError(failure.message))}>
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
        <button type="button" className="secondary" onClick={() => {
            running.current?.abort();
            signOut().then(() => setToken(null));
          }}>
          로그아웃
        </button>
      </header>
      <section aria-labelledby="chat-title" className="panel">
        <h2 id="chat-title">대화</h2>
        <ol className="chat" aria-live="polite">
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
      <CargoCards cargos={view.cargos} />
      <EvidencePanel evidence={view.evidence} />
      <section aria-labelledby="account-title" className="panel">
        <h2 id="account-title">계정</h2>
        {confirmingDelete ? (
          <div role="group" aria-label="계정 삭제 확인">
            <p>계정을 지우면 대화 기록, 저장한 값, 감시 목록이 모두 지워지고 되돌릴 수 없어요. 지울까요?</p>
            <div className="row">
              <button type="button" onClick={removeAccount}>
                지우기
              </button>
              <button type="button" className="secondary" onClick={() => setConfirmingDelete(false)}>
                그만두기
              </button>
            </div>
          </div>
        ) : (
          <button type="button" className="secondary" onClick={() => setConfirmingDelete(true)}>
            계정 삭제
          </button>
        )}
      </section>
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
